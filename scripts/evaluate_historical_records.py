#!/usr/bin/env python3
"""Offline metrics for independently reviewed historical candidate-pool records.

Only explicit candidate relevance labels are used for inclusion metrics.
Story support labels are a separate claim-truth measure and are never substituted.
This script is read-only and never runs production ranking, fetching, or delivery.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.validate_evaluation_record import validate_record

FIELDS = ("title", "source", "url", "published_at", "summary")


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_record(record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_record(record)
    candidates = record.get("candidate_articles", []) if isinstance(record, dict) else []
    reviews = record.get("candidate_reviews", []) if isinstance(record, dict) else []
    labels_by_id = {
        item.get("candidate_id"): item.get("relevance_label")
        for item in reviews
        if isinstance(item, dict) and item.get("candidate_id")
        and item.get("relevance_label") in {"relevant", "not_relevant", "uncertain"}
    }
    dispositions = {"included": 0, "excluded": 0, "duplicate": 0, "out_of_scope": 0}
    field_coverage = {key: 0 for key in FIELDS}
    reviewed_by_disposition = {key: 0 for key in dispositions}
    label_counts = {"relevant": 0, "not_relevant": 0, "uncertain": 0}
    tp = fp = tn = fn = 0
    metric_eligible_reviews = 0

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
        if label not in label_counts:
            continue
        label_counts[label] += 1
        if disposition in reviewed_by_disposition:
            reviewed_by_disposition[disposition] += 1
        # Only binary inclusion decisions and definitive relevance labels enter
        # the confusion matrix. Uncertain/duplicate/out-of-scope are not guessed.
        if disposition not in {"included", "excluded"} or label not in {"relevant", "not_relevant"}:
            continue
        metric_eligible_reviews += 1
        predicted_included = disposition == "included"
        truly_relevant = label == "relevant"
        tp += int(predicted_included and truly_relevant)
        fp += int(predicted_included and not truly_relevant)
        fn += int(not predicted_included and truly_relevant)
        tn += int(not predicted_included and not truly_relevant)

    reviewed_total = sum(reviewed_by_disposition.values())
    eligible_predicted_included = tp + fp
    eligible_relevant = tp + fn
    eligible_not_relevant = tn + fp
    accuracy = _rate(tp + tn, metric_eligible_reviews)
    precision = _rate(tp, eligible_predicted_included)
    recall = _rate(tp, eligible_relevant)
    specificity = _rate(tn, eligible_not_relevant)
    balanced_accuracy = ((recall + specificity) / 2
                         if recall is not None and specificity is not None else None)
    pending_metadata_suffixes = (
        "_title_required", "_source_required", "_url_required",
        "_published_at_required", "_summary_required",
    )
    pending_errors_only = all(
        error == "story_labels_must_be_nonempty_list"
        or (error.startswith("candidate_articles[")
            and any(error.endswith(suffix) for suffix in pending_metadata_suffixes)
            and "]_" in error)
        for error in errors
    )
    unreviewed_capture = (
        not record.get("candidate_reviews") and not record.get("story_labels")
        and pending_errors_only
    )
    return {
        "run_id": record.get("run_id", ""),
        "record_status": "evaluated" if not errors else ("awaiting_review" if unreviewed_capture else "invalid"),
        "schema_valid": not errors,
        "validation_errors": errors,
        "candidate_count": len(candidates),
        "candidate_dispositions": dispositions,
        "candidate_reviews": len(labels_by_id),
        "metric_eligible_reviews": metric_eligible_reviews,
        "evaluation_sampling": record.get("evaluation_sampling"),
        "candidate_review_coverage": {
            "reviewed": reviewed_total,
            "total_candidates": len(candidates),
            "rate": _rate(reviewed_total, len(candidates)),
            "by_disposition": {
                key: {"reviewed": reviewed_by_disposition[key], "total": dispositions[key],
                      "rate": _rate(reviewed_by_disposition[key], dispositions[key])}
                for key in dispositions
            },
            "warning": "Review coverage is descriptive; non-random or partial review may bias metrics.",
        },
        "candidate_relevance_labels": label_counts,
        "confusion_matrix": {"true_positives": tp, "false_positives": fp,
                             "true_negatives": tn, "false_negatives": fn},
        "false_positives": fp,
        "missed_relevant_candidates": fn,
        "true_positives": tp,
        "true_negatives": tn,
        "accuracy": accuracy,
        "inclusion_precision": precision,
        "inclusion_recall": recall,
        "specificity": specificity,
        "balanced_accuracy": balanced_accuracy,
        "f1": _rate(2 * tp, 2 * tp + fp + fn),
        "candidate_field_coverage": {
            key: {"present": count, "total": len(candidates), "rate": _rate(count, len(candidates))}
            for key, count in field_coverage.items()
        },
        "story_claim_labels": len(record.get("story_labels", [])),
        "interpretation": (
            "Binary inclusion metrics use only explicit candidate_reviews relevance labels "
            "on included/excluded candidates. story_labels are separate claim-support labels."
        ),
    }


def evaluate_paths(
    paths: list[Path], *, min_reviewed_candidates: int = 30, min_per_class: int = 10,
) -> dict[str, Any]:
    if min_reviewed_candidates < 1:
        raise ValueError("min_reviewed_candidates must be at least 1")
    if min_per_class < 1:
        raise ValueError("min_per_class must be at least 1")
    results = []
    errors = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("record root must be an object")
            result = evaluate_record(value)
            result["path"] = str(path)
            results.append(result)
            if not result["schema_valid"] and result.get("record_status") != "awaiting_review":
                errors.append({"path": str(path), "errors": result["validation_errors"]})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append({"path": str(path), "errors": [str(exc)]})

    valid = [row for row in results if row["schema_valid"]]
    awaiting_review = [row for row in results if row.get("record_status") == "awaiting_review"]
    reportable_records = valid + awaiting_review
    total_candidates = sum(row["candidate_count"] for row in reportable_records)
    total_reviews = sum(row["candidate_reviews"] for row in reportable_records)
    tp = sum(row["true_positives"] for row in valid)
    fp = sum(row["false_positives"] for row in valid)
    tn = sum(row["true_negatives"] for row in valid)
    fn = sum(row["missed_relevant_candidates"] for row in valid)
    eligible = sum(row["metric_eligible_reviews"] for row in valid)
    relevant_support = tp + fn
    not_relevant_support = tn + fp
    predicted_included = tp + fp
    precision = _rate(tp, predicted_included)
    recall = _rate(tp, relevant_support)
    specificity = _rate(tn, not_relevant_support)
    accuracy = _rate(tp + tn, eligible)
    balanced_accuracy = ((recall + specificity) / 2
                         if recall is not None and specificity is not None else None)
    gate_reasons = []
    if eligible < min_reviewed_candidates:
        gate_reasons.append("insufficient_metric_eligible_reviews")
    if relevant_support < min_per_class:
        gate_reasons.append("insufficient_relevant_class_support")
    if not_relevant_support < min_per_class:
        gate_reasons.append("insufficient_not_relevant_class_support")
    gate_status = "BLOCKED_INSUFFICIENT_SAMPLE" if gate_reasons else "SAMPLE_THRESHOLDS_MET"
    return {
        "evaluation_type": "offline_historical_candidate_relevance",
        "records_seen": len(paths),
        "schema_valid_records": len(valid),
        "records_awaiting_review": len(awaiting_review),
        "review_readiness_candidate_count": sum(row["candidate_count"] for row in awaiting_review),
        "invalid_records": len(errors),
        "candidate_count": total_candidates,
        "candidate_reviews": total_reviews,
        "metric_eligible_reviews": eligible,
        "class_support": {"relevant": relevant_support, "not_relevant": not_relevant_support},
        "evaluation_gate": {
            "status": gate_status,
            "minimum_metric_eligible_reviews": min_reviewed_candidates,
            "minimum_per_truth_class": min_per_class,
            "reasons": gate_reasons,
            "interpretation": "Meeting count thresholds does not prove representativeness or justify population-level claims.",
        },
        "evaluation_sampling": {
            "note": "Sampling metadata is retained per record; pooled metrics may combine different designs.",
            "per_record": [
                {"run_id": row.get("run_id", ""), "path": row.get("path", ""),
                 "sampling": row.get("evaluation_sampling")}
                for row in valid if row.get("evaluation_sampling") is not None
            ],
        },
        "candidate_review_coverage": {
            "reviewed": total_reviews, "total_candidates": total_candidates,
            "rate": _rate(total_reviews, total_candidates),
            "warning": "Coverage is pooled across valid records and does not establish representativeness.",
        },
        "confusion_matrix": {"true_positives": tp, "false_positives": fp,
                             "true_negatives": tn, "false_negatives": fn},
        "false_positives": fp,
        "missed_relevant_candidates": fn,
        "true_positives": tp,
        "true_negatives": tn,
        "accuracy": accuracy,
        "inclusion_precision": precision,
        "inclusion_recall": recall,
        "specificity": specificity,
        "balanced_accuracy": balanced_accuracy,
        "f1": _rate(2 * tp, 2 * tp + fp + fn),
        "records": results,
        "errors": errors,
        "limitations": [
            "Metrics describe only independently reviewed candidates, not unreviewed items.",
            "Uncertain labels and duplicate/out-of-scope dispositions are excluded from binary metrics.",
            "Story claim-support labels are distinct from candidate relevance labels.",
            "Sample thresholds are minimum safeguards, not proof of statistical power or representativeness.",
            "Field coverage measures presence only, not correctness or factual truth.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="a record JSON file or directory of record JSON files")
    parser.add_argument("--min-reviewed-candidates", type=int, default=30,
                        help="minimum binary, metric-eligible human reviews (default: 30)")
    parser.add_argument("--min-per-class", type=int, default=10,
                        help="minimum independently labelled examples in each truth class (default: 10)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    if args.min_reviewed_candidates < 1 or args.min_per_class < 1:
        parser.error("sample-size thresholds must be positive integers")
    paths = sorted(args.path.glob("*.json")) if args.path.is_dir() else [args.path]
    if not paths:
        print("No JSON evaluation records found.", file=sys.stderr)
        return 2
    result = evaluate_paths(paths, min_reviewed_candidates=args.min_reviewed_candidates,
                            min_per_class=args.min_per_class)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Insufficient human labels is a report status, not a CI failure. Invalid
    # schema/data is a failure. The report never promotes itself to a claim.
    return 1 if result["invalid_records"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
