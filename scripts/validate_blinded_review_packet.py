#!/usr/bin/env python3
"""Validate completed blinded reviews and compare them with a separate answer key.

Offline only. Does not fetch evidence, create labels, or modify source records.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LABELS = {"relevant", "not_relevant", "uncertain"}
METRIC_DISPOSITIONS = {"included", "excluded"}


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _contains_pipeline_disposition(value: Any) -> bool:
    """Find disposition fields anywhere in a reviewer-facing item."""
    if isinstance(value, dict):
        if "pipeline_disposition" in value or "disposition" in value:
            return True
        return any(_contains_pipeline_disposition(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_pipeline_disposition(child) for child in value)
    return False


def validate_packets(queue: Any, answer_key: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(queue, dict) or queue.get("packet_type") != "blinded_candidate_relevance_review":
        return {"valid": False, "errors": ["review_queue_type_invalid"]}
    if not isinstance(answer_key, dict) or answer_key.get("packet_type") != "candidate_review_answer_key":
        return {"valid": False, "errors": ["answer_key_type_invalid"]}
    if queue.get("packet_version") != answer_key.get("packet_version"):
        errors.append("packet_version_mismatch")
    sampling = queue.get("sampling")
    if not isinstance(sampling, dict):
        errors.append("sampling_metadata_invalid")
    elif sampling.get("seed") != answer_key.get("seed"):
        errors.append("sampling_seed_mismatch")
    queue_items = queue.get("items")
    key_items = answer_key.get("items")
    if not isinstance(queue_items, list) or not isinstance(key_items, list):
        return {"valid": False, "errors": errors + ["items_must_be_lists"]}
    if not queue_items or not key_items:
        errors.append("review_packet_must_not_be_empty")
    queue_map: dict[str, dict[str, Any]] = {}
    key_map: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(queue_items):
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"].strip():
            errors.append(f"queue_item_{index}_invalid")
            continue
        if item["item_id"] in queue_map:
            errors.append(f"queue_item_id_duplicate:{item['item_id']}")
        queue_map[item["item_id"]] = item
        run_id, candidate_id = item.get("run_id"), item.get("candidate_id")
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append(f"queue_run_id_required:{item['item_id']}")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            errors.append(f"queue_candidate_id_required:{item['item_id']}")
        if isinstance(run_id, str) and run_id.strip() and isinstance(candidate_id, str) and candidate_id.strip():
            if item["item_id"] != f"{run_id}::{candidate_id}":
                errors.append(f"queue_item_identity_mismatch:{item['item_id']}")
        if _contains_pipeline_disposition(item):
            errors.append(f"queue_not_blinded:{item['item_id']}")
    for index, item in enumerate(key_items):
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str) or not item["item_id"].strip():
            errors.append(f"key_item_{index}_invalid")
            continue
        if item["item_id"] in key_map:
            errors.append(f"key_item_id_duplicate:{item['item_id']}")
        key_map[item["item_id"]] = item
        run_id, candidate_id = item.get("run_id"), item.get("candidate_id")
        if not isinstance(run_id, str) or not run_id.strip():
            errors.append(f"key_run_id_required:{item['item_id']}")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            errors.append(f"key_candidate_id_required:{item['item_id']}")
        if isinstance(run_id, str) and run_id.strip() and isinstance(candidate_id, str) and candidate_id.strip():
            if item["item_id"] != f"{run_id}::{candidate_id}":
                errors.append(f"key_item_identity_mismatch:{item['item_id']}")
        disposition = item.get("pipeline_disposition")
        if not isinstance(disposition, str) or disposition not in {
            "included", "excluded", "duplicate", "out_of_scope"
        }:
            errors.append(f"key_disposition_invalid:{item['item_id']}")
    if set(queue_map) != set(key_map):
        errors.append("queue_answer_key_item_ids_mismatch")

    # Item IDs alone are not enough: protect the join between the blinded queue
    # and answer key from accidental or malicious run/candidate metadata edits.
    for item_id in sorted(set(queue_map) & set(key_map)):
        queue_item = queue_map[item_id]
        key_item = key_map[item_id]
        for field in ("run_id", "candidate_id"):
            if field in queue_item or field in key_item:
                if queue_item.get(field) != key_item.get(field):
                    errors.append(f"queue_answer_key_{field}_mismatch:{item_id}")

    label_counts = {"relevant": 0, "not_relevant": 0, "uncertain": 0}
    confusion = {"true_positives": 0, "false_positives": 0, "true_negatives": 0, "false_negatives": 0}
    eligible = 0
    unreviewed = []
    for item_id in sorted(set(queue_map) & set(key_map)):
        item = queue_map[item_id]
        review = item.get("review")
        if not isinstance(review, dict):
            errors.append(f"review_object_missing:{item_id}")
            continue
        label = review.get("relevance_label")
        if label == "":
            unreviewed.append(item_id)
            continue
        if not isinstance(label, str) or label not in LABELS:
            errors.append(f"relevance_label_invalid:{item_id}")
            continue
        label_counts[label] += 1
        if not isinstance(review.get("reviewer_id"), str) or not review["reviewer_id"].strip():
            errors.append(f"reviewer_id_required:{item_id}")
        if not _aware_timestamp(review.get("reviewed_at")):
            errors.append(f"reviewed_at_must_be_timezone_aware_iso8601:{item_id}")
        if not isinstance(review.get("rationale"), str) or not review["rationale"].strip():
            errors.append(f"rationale_required:{item_id}")
        evidence_urls = review.get("evidence_urls")
        if not isinstance(evidence_urls, list):
            errors.append(f"evidence_urls_must_be_list:{item_id}")
        elif any(not _valid_http_url(url) for url in evidence_urls):
            errors.append(f"evidence_urls_must_be_http_urls:{item_id}")
        elif label in {"relevant", "not_relevant"} and not evidence_urls:
            errors.append(f"definitive_label_requires_evidence_url:{item_id}")

        disposition = key_map[item_id].get("pipeline_disposition")
        if not isinstance(disposition, str) or disposition not in METRIC_DISPOSITIONS or label == "uncertain":
            continue
        eligible += 1
        predicted = disposition == "included"
        truth = label == "relevant"
        confusion["true_positives"] += int(predicted and truth)
        confusion["false_positives"] += int(predicted and not truth)
        confusion["false_negatives"] += int(not predicted and truth)
        confusion["true_negatives"] += int(not predicted and not truth)

    tp, fp = confusion["true_positives"], confusion["false_positives"]
    tn, fn = confusion["true_negatives"], confusion["false_negatives"]
    return {
        "valid": not errors,
        "complete": not unreviewed and not errors,
        "errors": errors,
        "packet_items": len(queue_items),
        "completed_review_count": sum(label_counts.values()),
        "unreviewed_count": len(unreviewed),
        "unreviewed_item_ids": unreviewed,
        "label_counts": label_counts,
        "metric_eligible_review_count": eligible,
        "confusion_matrix": confusion,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "accuracy": (tp + tn) / eligible if eligible else None,
        "metric_scope": (
            "Descriptive metrics for reviewed included/excluded candidates only; "
            "duplicate/out_of_scope and uncertain labels are excluded. "
            "Stratified review samples are not automatically population-representative."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path, help="completed reviewer queue JSON")
    parser.add_argument("answer_key", type=Path, help="separately stored answer-key JSON")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--require-complete", action="store_true", help="fail if any queue item is unreviewed")
    args = parser.parse_args(argv)
    try:
        queue = json.loads(args.queue.read_text(encoding="utf-8"))
        answer_key = json.loads(args.answer_key.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read review packet: {exc}", file=sys.stderr)
        return 2
    report = validate_packets(queue, answer_key)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] and (not args.require_complete or report["complete"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
