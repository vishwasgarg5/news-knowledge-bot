#!/usr/bin/env python3
"""Offline metrics for independently reviewed historical candidate-pool records.

Only explicit candidate relevance labels are used for inclusion precision/recall.
Story support labels are a separate claim-truth measure and are never substituted.
No network, production pipeline, ranking, or notification calls are made.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.validate_evaluation_record import validate_record


def evaluate_record(record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_record(record)
    candidates = record.get("candidate_articles", []) if isinstance(record, dict) else []
    reviews = record.get("candidate_reviews", []) if isinstance(record, dict) else []
    labels_by_id = {
        item.get("candidate_id"): item.get("relevance_label")
        for item in reviews
        if isinstance(item, dict) and item.get("candidate_id") and item.get("relevance_label") in {"relevant", "not_relevant", "uncertain"}
    }
    dispositions = {"included": 0, "excluded": 0, "duplicate": 0, "out_of_scope": 0}
    field_coverage = {key: 0 for key in ("title", "source", "url", "published_at", "summary")}
    reviewed_included = reviewed_excluded = 0
    true_positive = false_positive = false_negative = 0
    relevance_label_counts = {"relevant": 0, "not_relevant": 0, "uncertain": 0}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        disposition = candidate.get("disposition")
        if disposition in dispositions:
            dispositions[disposition] += 1
        for field in field_coverage:
            if isinstance(candidate.get(field), str) and candidate[field].strip():
                field_coverage[field] += 1
        label = labels_by_id.get(candidate.get("candidate_id"))
        if label not in relevance_label_counts:
            continue
        relevance_label_counts[label] += 1
        if disposition == "included":
            reviewed_included += 1
            if label == "relevant":
                true_positive += 1
            elif label == "not_relevant":
                false_positive += 1
        elif disposition == "excluded":
            reviewed_excluded += 1
            if label == "relevant":
                false_negative += 1

    relevant_total = true_positive + false_negative
    predicted_included_reviewed = true_positive + false_positive
    return {
        "run_id": record.get("run_id", ""),
        "schema_valid": not errors,
        "validation_errors": errors,
        "candidate_count": len(candidates),
        "candidate_dispositions": dispositions,
        "candidate_reviews": len(labels_by_id),
        "candidate_relevance_labels": relevance_label_counts,
        "reviewed_included_candidates": reviewed_included,
        "reviewed_excluded_candidates": reviewed_excluded,
        "false_positives": false_positive,
        "missed_relevant_candidates": false_negative,
        "true_positives": true_positive,
        "inclusion_precision": true_positive / predicted_included_reviewed if predicted_included_reviewed else None,
        "inclusion_recall": true_positive / relevant_total if relevant_total else None,
        "candidate_field_coverage": {
            key: {"present": count, "total": len(candidates), "rate": count / len(candidates) if candidates else None}
            for key, count in field_coverage.items()
        },
        "story_claim_labels": len(record.get("story_labels", [])),
        "interpretation": "Precision/recall use only explicit candidate_reviews relevance labels; story_labels measure claim support separately.",
    }


def evaluate_paths(paths: list[Path]) -> dict[str, Any]:
    results = []
    errors = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("record root must be a JSON object")
            result = evaluate_record(value)
            result["path"] = str(path)
            results.append(result)
            if not result["schema_valid"]:
                errors.append({"path": str(path), "errors": result["validation_errors"]})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append({"path": str(path), "errors": [str(exc)]})
    valid_results = [row for row in results if row["schema_valid"]]
    total_candidates = sum(row["candidate_count"] for row in valid_results)
    total_reviews = sum(row["candidate_reviews"] for row in valid_results)
    total_tp = sum(row["true_positives"] for row in valid_results)
    total_fp = sum(row["false_positives"] for row in valid_results)
    total_fn = sum(row["missed_relevant_candidates"] for row in valid_results)
    reviewed_predicted = total_tp + total_fp
    reviewed_relevant = total_tp + total_fn
    return {
        "evaluation_type": "offline_historical_candidate_relevance",
        "records_seen": len(paths),
        "schema_valid_records": len(valid_results),
        "invalid_records": len(errors),
        "candidate_count": total_candidates,
        "candidate_reviews": total_reviews,
        "false_positives": total_fp,
        "missed_relevant_candidates": total_fn,
        "true_positives": total_tp,
        "inclusion_precision": total_tp / reviewed_predicted if reviewed_predicted else None,
        "inclusion_recall": total_tp / reviewed_relevant if reviewed_relevant else None,
        "records": results,
        "errors": errors,
        "limitations": [
            "Metrics describe only independently reviewed candidates, not unreviewed items.",
            "Uncertain labels and duplicate/out-of-scope dispositions are excluded from precision/recall denominators.",
            "Story claim-support labels are distinct from candidate relevance labels.",
            "Field coverage measures presence only, not correctness or factual truth.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="a record JSON file or directory of record JSON files")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    if args.path.is_dir():
        paths = sorted(args.path.glob("*.json"))
    else:
        paths = [args.path]
    if not paths:
        print("No JSON evaluation records found.", file=sys.stderr)
        return 2
    result = evaluate_paths(paths)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["invalid_records"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
