#!/usr/bin/env python3
"""Consolidate independent review queues and explicit adjudications offline.

An adjudication file is optional JSON with an "adjudications" array. Each entry
must name candidate_id, final_label, adjudicator_id, adjudicated_at (timezone-aware
ISO-8601), and rationale. This report never silently resolves disagreement.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

LABELS = {"relevant", "not_relevant", "uncertain"}
DISPOSITIONS = {"included", "excluded", "duplicate", "out_of_scope"}
EVIDENCE_FIELDS = ("source", "url", "published_at", "summary")


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _group_rows_by_reviewer(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        reviewer_id = str(row.get("reviewer_id", "")).strip()
        if reviewer_id:
            grouped[reviewer_id].append(row)
    return grouped


def consolidate_reviews(
    queues: list[tuple[str, dict[str, Any]]],
    adjudication_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sampling = []
    malformed_entries = []
    for path, queue in queues:
        sampling.append({
            "path": path,
            "run_id": queue.get("run_id", ""),
            "sampling_method": queue.get("sampling_method", ""),
            "sampling_seed": queue.get("sampling_seed", ""),
            "per_disposition_cap": queue.get("per_disposition_cap"),
            "strata": queue.get("strata", {}),
        })
        reviews = queue.get("reviews", [])
        if not isinstance(reviews, list):
            malformed_entries.append({"queue": path, "issue": "reviews_must_be_list"})
            continue
        for index, row in enumerate(reviews):
            if not isinstance(row, dict) or not str(row.get("candidate_id", "")).strip():
                malformed_entries.append({"queue": path, "index": index, "issue": "candidate_id_missing_or_entry_invalid"})
                continue
            candidate_id = str(row["candidate_id"]).strip()
            by_candidate[candidate_id].append({**row, "_queue_path": path})

    raw_adjudications = (adjudication_data or {}).get("adjudications", [])
    if not isinstance(raw_adjudications, list):
        raw_adjudications = []
        malformed_entries.append({"queue": "(adjudication file)", "issue": "adjudications_must_be_list"})
    adjudications: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_adjudications):
        if not isinstance(row, dict):
            malformed_entries.append({"queue": "(adjudication file)", "index": index, "issue": "adjudication_must_be_object"})
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        issues = []
        if not candidate_id:
            issues.append("candidate_id_required")
        if row.get("final_label") not in LABELS:
            issues.append("final_label_invalid")
        if not str(row.get("adjudicator_id", "")).strip():
            issues.append("adjudicator_id_required")
        if not _aware_timestamp(row.get("adjudicated_at")):
            issues.append("adjudicated_at_must_be_timezone_aware_iso8601")
        if not str(row.get("rationale", "")).strip():
            issues.append("rationale_required")
        if issues:
            malformed_entries.append({"queue": "(adjudication file)", "index": index, "candidate_id": candidate_id, "issues": issues})
            continue
        if candidate_id in adjudications:
            malformed_entries.append({"queue": "(adjudication file)", "candidate_id": candidate_id, "issue": "duplicate_adjudication"})
            continue
        adjudications[candidate_id] = row

    duplicate_reviewer_entries = []
    for candidate_id, rows in sorted(by_candidate.items()):
        by_reviewer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            reviewer_id = str(row.get("reviewer_id", "")).strip()
            if reviewer_id:
                by_reviewer[reviewer_id].append(row)
        for reviewer_id, reviewer_rows in sorted(by_reviewer.items()):
            if len(reviewer_rows) > 1:
                duplicate_reviewer_entries.append({
                    "candidate_id": candidate_id,
                    "reviewer_id": reviewer_id,
                    "entry_count": len(reviewer_rows),
                    "labels": sorted({
                        str(row.get("relevance_label", "")).strip()
                        for row in reviewer_rows
                        if row.get("relevance_label") in LABELS
                    }),
                    "queues": sorted({row["_queue_path"] for row in reviewer_rows}),
                })

    candidate_rows = []
    disagreements = []
    uncertain = []
    evidence_gaps = []
    incomplete_reviews = []
    unresolved = []
    for candidate_id, rows in sorted(by_candidate.items()):
        labels = sorted({
            row.get("relevance_label") for row in rows
            if row.get("relevance_label") in LABELS
        })
        reviewers = sorted({str(row.get("reviewer_id", "")).strip() or "(missing)" for row in rows})
        labels_by_reviewer: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            reviewer_id = str(row.get("reviewer_id", "")).strip() or "(missing)"
            label = row.get("relevance_label")
            if label in LABELS:
                labels_by_reviewer[reviewer_id].add(label)
        distinct_reviewer_labels = {
            label
            for reviewer_id, reviewer_labels in labels_by_reviewer.items()
            if reviewer_id != "(missing)" and len(reviewer_labels) == 1
            for label in reviewer_labels
        }
        has_duplicate_reviewer_entry = any(
            reviewer_id != "(missing)" and len(reviewer_rows) > 1
            for reviewer_id, reviewer_rows in _group_rows_by_reviewer(rows).items()
        )
        gaps = sorted({field for row in rows for field in EVIDENCE_FIELDS
                       if not str(row.get(field, "") or "").strip()})
        if gaps:
            evidence_gaps.append({"candidate_id": candidate_id, "missing_fields": gaps})
        for row in rows:
            missing = []
            if row.get("relevance_label") not in LABELS:
                missing.append("relevance_label")
            if not str(row.get("reviewer_id", "")).strip():
                missing.append("reviewer_id")
            if not _aware_timestamp(row.get("reviewed_at")):
                missing.append("reviewed_at")
            if not str(row.get("rationale", "")).strip():
                missing.append("rationale")
            if missing:
                incomplete_reviews.append({"candidate_id": candidate_id, "queue": row["_queue_path"], "missing_fields": missing})
        is_disagreement = len(distinct_reviewer_labels) > 1
        if is_disagreement:
            disagreements.append({"candidate_id": candidate_id, "labels": sorted(distinct_reviewer_labels), "reviewers": reviewers})
        if "uncertain" in labels:
            uncertain.append({"candidate_id": candidate_id, "labels": labels, "reviewers": reviewers})
        adjudication = adjudications.get(candidate_id)
        status = (
            "adjudicated" if adjudication else
            "duplicate_reviewer_entries" if has_duplicate_reviewer_entry else
            "unresolved_disagreement" if is_disagreement else
            "uncertain" if "uncertain" in labels else
            "evidence_incomplete" if gaps else
            "reviewed" if labels else "pending_review"
        )
        if status in {"duplicate_reviewer_entries", "unresolved_disagreement", "uncertain", "evidence_incomplete", "pending_review"}:
            unresolved.append({"candidate_id": candidate_id, "status": status})
        candidate_rows.append({
            "candidate_id": candidate_id,
            "review_count": len(rows),
            "unique_reviewer_count": len({str(row.get("reviewer_id", "")).strip() for row in rows if str(row.get("reviewer_id", "")).strip()}),
            "valid_labels": labels,
            "reviewers": reviewers,
            "status": status,
            "adjudication": adjudication,
            "evidence_gaps": gaps,
        })

    orphan_adjudications = sorted(set(adjudications) - set(by_candidate))
    return {
        "report_type": "consolidated_human_evaluation",
        "queue_files_seen": len(queues),
        "unique_candidates_seen": len(by_candidate),
        "candidate_summaries": candidate_rows,
        "review_disagreements": disagreements,
        "review_disagreement_count": len(disagreements),
        "duplicate_reviewer_entries": duplicate_reviewer_entries,
        "duplicate_reviewer_entry_count": len(duplicate_reviewer_entries),
        "uncertain_candidates": uncertain,
        "uncertain_candidate_count": len(uncertain),
        "evidence_gaps": evidence_gaps,
        "evidence_gap_count": len(evidence_gaps),
        "incomplete_reviews": incomplete_reviews,
        "incomplete_review_count": len(incomplete_reviews),
        "unresolved_candidates": unresolved,
        "unresolved_candidate_count": len(unresolved),
        "adjudications_accepted": len(adjudications),
        "orphan_adjudications": orphan_adjudications,
        "malformed_entries": malformed_entries,
        "sampling_metadata": sampling,
        "limitations": [
            "Repeated entries from one reviewer are flagged and must not be interpreted as independent opinions.",
            "Only explicit, schema-shaped adjudications are accepted; reviewer disagreement is never auto-resolved.",
            "An adjudication is an accountable human decision, not an independent proof of truth.",
            "Unresolved, uncertain, pending, or evidence-incomplete cases should be excluded from definitive metrics unless the evaluation protocol explicitly defines their treatment.",
            "Sampling and review coverage can bias metrics; this report does not compute accuracy or apply sampling weights.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queues", nargs="+", type=Path, help="completed reviewer queue JSON files")
    parser.add_argument("--adjudications", type=Path, help="JSON file with an adjudications array")
    parser.add_argument("--output", type=Path, help="output report path; defaults to stdout")
    args = parser.parse_args()
    try:
        queues = []
        for path in args.queues:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"{path}: queue root must be an object")
            queues.append((str(path), value))
        adjudication_data = None
        if args.adjudications:
            adjudication_data = json.loads(args.adjudications.read_text(encoding="utf-8"))
            if not isinstance(adjudication_data, dict):
                raise ValueError("adjudication root must be an object")
        report = consolidate_reviews(queues, adjudication_data)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
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
