#!/usr/bin/env python3
"""Offline precision/recall from explicitly adjudicated, evidence-complete reviews.

Only candidates with an explicit valid adjudication, valid disposition, and
complete source evidence are eligible. All other cases remain visible with a
specific exclusion reason. No production pipeline or network calls are made.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

LABELS = {"relevant", "not_relevant", "uncertain"}


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None
DISPOSITIONS = {"included", "excluded", "duplicate", "out_of_scope"}
EVIDENCE_FIELDS = ("source", "url", "published_at", "summary")


def evaluate_adjudicated_reviews(
    queues: list[tuple[str, dict[str, Any]]],
    adjudication_data: dict[str, Any],
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    queue_metadata = []
    exclusions: dict[str, int] = {}
    for path, queue in queues:
        queue_metadata.append({
            "path": path,
            "run_id": queue.get("run_id", ""),
            "policy_version": queue.get("policy_version", ""),
            "sampling_method": queue.get("sampling_method", ""),
            "sampling_seed": queue.get("sampling_seed", ""),
            "per_disposition_cap": queue.get("per_disposition_cap"),
            "strata": queue.get("strata", {}),
        })
        rows = queue.get("reviews", [])
        if not isinstance(rows, list):
            exclusions["invalid_review_list"] = exclusions.get("invalid_review_list", 0) + 1
            continue
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("candidate_id", "")).strip():
                exclusions["invalid_review_entry"] = exclusions.get("invalid_review_entry", 0) + 1
                continue
            cid = str(row["candidate_id"]).strip()
            if cid not in candidates:
                candidates[cid] = dict(row)
            else:
                # Keep first candidate metadata; labels come solely from adjudications.
                for key in EVIDENCE_FIELDS + ("disposition",):
                    if not str(candidates[cid].get(key, "") or "").strip() and str(row.get(key, "") or "").strip():
                        candidates[cid][key] = row[key]

    raw = adjudication_data.get("adjudications", [])
    if not isinstance(raw, list):
        raw = []
    adjudications = {}
    invalid_adjudications = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            invalid_adjudications.append({"index": index, "reason": "entry_not_object"})
            continue
        cid = str(row.get("candidate_id", "")).strip()
        reasons = []
        if not cid:
            reasons.append("candidate_id_required")
        if row.get("final_label") not in LABELS:
            reasons.append("final_label_invalid")
        if not str(row.get("adjudicator_id", "")).strip():
            reasons.append("adjudicator_id_required")
        if not _aware_timestamp(row.get("adjudicated_at")):
            reasons.append("adjudicated_at_must_be_timezone_aware_iso8601")
        if not str(row.get("rationale", "")).strip():
            reasons.append("rationale_required")
        if reasons:
            invalid_adjudications.append({"index": index, "candidate_id": cid, "reasons": reasons})
        elif cid in adjudications:
            invalid_adjudications.append({"index": index, "candidate_id": cid, "reasons": ["duplicate_adjudication"]})
        else:
            adjudications[cid] = row

    candidate_results = []
    tp = fp = fn = 0
    metric_eligible = 0
    for cid, candidate in sorted(candidates.items()):
        adjudication = adjudications.get(cid)
        reasons = []
        if not adjudication:
            reasons.append("no_valid_adjudication")
        missing_evidence = [field for field in EVIDENCE_FIELDS if not str(candidate.get(field, "") or "").strip()]
        if missing_evidence:
            reasons.append("missing_evidence:" + ",".join(missing_evidence))
        disposition = candidate.get("disposition")
        if disposition not in DISPOSITIONS:
            reasons.append("invalid_disposition")
        label = adjudication.get("final_label") if adjudication else None
        if label == "uncertain":
            reasons.append("adjudicated_uncertain")
        if disposition in {"duplicate", "out_of_scope"}:
            reasons.append("disposition_outside_precision_recall_scope")
        eligible = not reasons and label in {"relevant", "not_relevant"} and disposition in {"included", "excluded"}
        if eligible:
            metric_eligible += 1
            if disposition == "included" and label == "relevant":
                tp += 1
            elif disposition == "included" and label == "not_relevant":
                fp += 1
            elif disposition == "excluded" and label == "relevant":
                fn += 1
        for reason in reasons:
            exclusions[reason] = exclusions.get(reason, 0) + 1
        candidate_results.append({
            "candidate_id": cid,
            "disposition": disposition,
            "adjudicated_label": label,
            "adjudication": adjudication,
            "eligible_for_precision_recall": eligible,
            "exclusion_reasons": reasons,
        })

    predicted_included = tp + fp
    independently_relevant = tp + fn
    return {
        "evaluation_type": "offline_adjudicated_candidate_relevance",
        "candidate_count": len(candidates),
        "valid_adjudications_for_known_candidates": sum(1 for cid in adjudications if cid in candidates),
        "metric_eligible_candidates": metric_eligible,
        "metrics": {
            "true_positives": tp,
            "false_positives": fp,
            "missed_relevant_candidates": fn,
            "inclusion_precision": tp / predicted_included if predicted_included else None,
            "inclusion_recall": tp / independently_relevant if independently_relevant else None,
            "precision_denominator": predicted_included,
            "recall_denominator": independently_relevant,
        },
        "exclusion_reason_counts": exclusions,
        "invalid_adjudications": invalid_adjudications,
        "candidate_results": candidate_results,
        "sampling_metadata": queue_metadata,
        "limitations": [
            "Metrics use only explicitly adjudicated, evidence-complete included/excluded candidates.",
            "Uncertain, unresolved, duplicate, out-of-scope, or evidence-incomplete candidates are not silently treated as negatives.",
            "Adjudication is a human decision, not independent proof of truth.",
            "Sampling bias is not corrected; precision/recall may not represent the full candidate population.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queues", nargs="+", type=Path, help="review queue JSON files")
    parser.add_argument("--adjudications", required=True, type=Path, help="explicit adjudication JSON")
    parser.add_argument("--output", type=Path, help="output report file; defaults to stdout")
    args = parser.parse_args()
    try:
        queues = []
        for path in args.queues:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"{path}: queue root must be an object")
            queues.append((str(path), value))
        adjudication_data = json.loads(args.adjudications.read_text(encoding="utf-8"))
        if not isinstance(adjudication_data, dict):
            raise ValueError("adjudication root must be an object")
        report = evaluate_adjudicated_reviews(queues, adjudication_data)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
