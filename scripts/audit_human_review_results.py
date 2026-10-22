#!/usr/bin/env python3
"""Audit completed review queues for disagreement, uncertainty, and evidence gaps.

Offline/read-only. Accept one or more completed queue JSON files; multiple reviewers'
copies can be passed together to compare labels for the same candidate.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

DISPOSITIONS = ("included", "excluded", "duplicate", "out_of_scope")
EVIDENCE_FIELDS = ("source", "url", "published_at", "summary")
LABELS = {"relevant", "not_relevant", "uncertain"}


def audit_review_queues(
    queues: list[tuple[str, dict[str, Any]]],
    min_reviews_per_disposition: int = 3,
) -> dict[str, Any]:
    if min_reviews_per_disposition < 1:
        raise ValueError("min_reviews_per_disposition must be at least 1")
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    strata: dict[str, dict[str, Any]] = {
        disposition: {"review_count": 0, "candidate_ids": set(), "missing_evidence": 0}
        for disposition in DISPOSITIONS
    }
    missing_fields = []
    malformed_entries = 0
    sampling = []

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
            malformed_entries += 1
            continue
        for index, review in enumerate(reviews):
            if not isinstance(review, dict):
                malformed_entries += 1
                continue
            candidate_id = str(review.get("candidate_id", "")).strip()
            disposition = review.get("disposition")
            if not candidate_id:
                malformed_entries += 1
                continue
            row = dict(review)
            row["_queue_path"] = path
            by_candidate[candidate_id].append(row)
            if disposition in strata:
                bucket = strata[disposition]
                bucket["review_count"] += 1
                bucket["candidate_ids"].add(candidate_id)
                absent = [field for field in EVIDENCE_FIELDS if not str(review.get(field, "") or "").strip()]
                if absent:
                    bucket["missing_evidence"] += 1
                    missing_fields.append({
                        "candidate_id": candidate_id,
                        "queue": path,
                        "missing_fields": absent,
                    })
            else:
                missing_fields.append({
                    "candidate_id": candidate_id,
                    "queue": path,
                    "missing_fields": ["valid_disposition"],
                })

    duplicate_reviewer_entries = []
    for candidate_id, reviews in sorted(by_candidate.items()):
        by_reviewer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in reviews:
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
                        if str(row.get("relevance_label", "")).strip() in LABELS
                    }),
                    "queues": sorted({row["_queue_path"] for row in reviewer_rows}),
                })

    disagreements = []
    uncertain = []
    incomplete_reviews = []
    candidate_summaries = []
    for candidate_id, reviews in sorted(by_candidate.items()):
        labels = sorted({
            str(row.get("relevance_label", "")).strip()
            for row in reviews
            if str(row.get("relevance_label", "")).strip() in LABELS
        })
        valid_labels = [
            str(row.get("relevance_label", "")).strip()
            for row in reviews
            if str(row.get("relevance_label", "")).strip() in LABELS
        ]
        if len(labels) > 1:
            disagreements.append({
                "candidate_id": candidate_id,
                "labels": labels,
                "review_count": len(valid_labels),
                "reviewers": sorted({str(row.get("reviewer_id", "")).strip() or "(missing)" for row in reviews}),
                "queues": sorted({row["_queue_path"] for row in reviews}),
            })
        if "uncertain" in valid_labels:
            uncertain.append({
                "candidate_id": candidate_id,
                "reviewers": sorted({str(row.get("reviewer_id", "")).strip() or "(missing)" for row in reviews}),
                "review_count": len(valid_labels),
            })
        for row in reviews:
            missing = []
            if str(row.get("relevance_label", "")).strip() not in LABELS:
                missing.append("relevance_label")
            if not str(row.get("reviewer_id", "") or "").strip():
                missing.append("reviewer_id")
            if not str(row.get("reviewed_at", "") or "").strip():
                missing.append("reviewed_at")
            if not str(row.get("rationale", "") or "").strip():
                missing.append("rationale")
            if missing:
                incomplete_reviews.append({
                    "candidate_id": candidate_id,
                    "queue": row["_queue_path"],
                    "missing_fields": missing,
                })
        candidate_summaries.append({
            "candidate_id": candidate_id,
            "review_count": len(valid_labels),
            "labels": labels,
            "status": (
                "disagreement" if len(labels) > 1 else
                "uncertain" if "uncertain" in labels else
                "reviewed" if labels else "pending"
            ),
        })

    disposition_report = {}
    for disposition, bucket in strata.items():
        count = len(bucket["candidate_ids"])
        disposition_report[disposition] = {
            "review_entries": bucket["review_count"],
            "unique_candidates_reviewed": count,
            "candidates_missing_evidence": bucket["missing_evidence"],
            "under_reviewed": count < min_reviews_per_disposition,
            "minimum_unique_candidates": min_reviews_per_disposition,
        }

    return {
        "audit_type": "human_review_quality_audit",
        "queue_files_seen": len(queues),
        "unique_candidates_seen": len(by_candidate),
        "malformed_entries": malformed_entries,
        "disagreements": disagreements,
        "disagreement_count": len(disagreements),
        "duplicate_reviewer_entries": duplicate_reviewer_entries,
        "duplicate_reviewer_entry_count": len(duplicate_reviewer_entries),
        "uncertain_candidates": uncertain,
        "uncertain_candidate_count": len(uncertain),
        "incomplete_reviews": incomplete_reviews,
        "incomplete_review_count": len(incomplete_reviews),
        "missing_candidate_evidence": missing_fields,
        "missing_candidate_evidence_count": len(missing_fields),
        "disposition_coverage": disposition_report,
        "candidate_summaries": candidate_summaries,
        "sampling_metadata": sampling,
        "limitations": [
            "A disagreement means reviewers supplied different valid labels; it is not automatically an adjudicated error.",
            "Repeated candidate IDs are compared across all supplied queue files; do not pass duplicate copies from the same reviewer as independent opinions.",
            "Under-review thresholds are operational flags, not a statistical guarantee of representativeness.",
            "Evidence-field presence does not establish source credibility or factual correctness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queues", nargs="+", type=Path, help="one or more completed review queue JSON files")
    parser.add_argument("--min-reviews-per-disposition", type=int, default=3,
                        help="flag strata with fewer unique reviewed candidates (default: 3)")
    parser.add_argument("--output", type=Path, help="write JSON report to this path; defaults to stdout")
    args = parser.parse_args()
    try:
        queues = []
        for path in args.queues:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{path}: queue root must be an object")
            queues.append((str(path), data))
        report = audit_review_queues(queues, args.min_reviews_per_disposition)
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
