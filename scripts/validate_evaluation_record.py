#!/usr/bin/env python3
"""Validate a versioned, independently labelled historical-evaluation record.

The validator is offline and read-only. It does not run the news pipeline or
infer labels from the production verification decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
LABELS = {"supported", "not_supported", "uncertain"}
CANDIDATE_REQUIRED = ("candidate_id", "title", "source", "url", "published_at", "summary", "disposition")
LABEL_REQUIRED = ("story_id", "label", "reviewer_id", "reviewed_at", "rationale")
CANDIDATE_REVIEW_REQUIRED = ("candidate_id", "relevance_label", "reviewer_id", "reviewed_at", "rationale")
RELEVANCE_LABELS = {"relevant", "not_relevant", "uncertain"}
DISPOSITIONS = {"included", "excluded", "duplicate", "out_of_scope"}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_http_url(value: Any) -> bool:
    if not _nonempty(value):
        return False
    from urllib.parse import urlparse
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_timestamp(value: Any) -> bool:
    if not _nonempty(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_record(record: Any) -> list[str]:
    """Return deterministic validation errors; an empty list means schema-valid."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record_root_must_be_object"]

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version_must_equal_1.0")
    for field in ("run_id", "policy_version"):
        if not _nonempty(record.get(field)):
            errors.append(f"{field}_required")
    if not _valid_timestamp(record.get("run_timestamp")):
        errors.append("run_timestamp_must_be_timezone_aware_iso8601")

    candidates = record.get("candidate_articles")
    if not isinstance(candidates, list) or not candidates:
        errors.append("candidate_articles_must_be_nonempty_list")
        candidates = []
    seen_candidates: set[str] = set()
    for index, candidate in enumerate(candidates):
        prefix = f"candidate_articles[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{prefix}_must_be_object")
            continue
        for field in CANDIDATE_REQUIRED:
            if not _nonempty(candidate.get(field)):
                errors.append(f"{prefix}_{field}_required")
        candidate_id = candidate.get("candidate_id")
        if _nonempty(candidate_id):
            if candidate_id in seen_candidates:
                errors.append(f"{prefix}_candidate_id_duplicate")
            seen_candidates.add(candidate_id)
        if candidate.get("disposition") not in DISPOSITIONS:
            errors.append(f"{prefix}_disposition_invalid")
        if not _valid_timestamp(candidate.get("published_at")):
            errors.append(f"{prefix}_published_at_must_be_timezone_aware_iso8601")

    labels = record.get("story_labels")
    # Candidate-relevance evaluation is valid independently of claim-truth
    # review. Require story_labels when no candidate reviews are supplied, but
    # never substitute one label type for the other.
    has_candidate_reviews = isinstance(record.get("candidate_reviews"), list) and bool(record.get("candidate_reviews"))
    if not isinstance(labels, list) or (not labels and not has_candidate_reviews):
        errors.append("story_labels_must_be_nonempty_list")
        labels = []
    elif not isinstance(labels, list):
        labels = []
    seen_stories: set[str] = set()
    for index, label in enumerate(labels):
        prefix = f"story_labels[{index}]"
        if not isinstance(label, dict):
            errors.append(f"{prefix}_must_be_object")
            continue
        for field in LABEL_REQUIRED:
            if not _nonempty(label.get(field)):
                errors.append(f"{prefix}_{field}_required")
        story_id = label.get("story_id")
        if _nonempty(story_id):
            if story_id in seen_stories:
                errors.append(f"{prefix}_story_id_duplicate")
            seen_stories.add(story_id)
        if label.get("label") not in LABELS:
            errors.append(f"{prefix}_label_invalid")
        if not _valid_timestamp(label.get("reviewed_at")):
            errors.append(f"{prefix}_reviewed_at_must_be_timezone_aware_iso8601")
        if label.get("label") == "uncertain" and not _nonempty(label.get("rationale")):
            errors.append(f"{prefix}_uncertain_label_requires_rationale")
        if label.get("label") in {"supported", "not_supported"}:
            evidence_urls = label.get("evidence_urls")
            if not isinstance(evidence_urls, list) or not evidence_urls:
                errors.append(f"{prefix}_definitive_label_requires_evidence_urls")
            elif not any(_valid_http_url(url) for url in evidence_urls):
                errors.append(f"{prefix}_definitive_label_requires_valid_evidence_url")

    candidate_reviews = record.get("candidate_reviews", [])
    if not isinstance(candidate_reviews, list):
        errors.append("candidate_reviews_must_be_list")
        candidate_reviews = []
    seen_review_ids: set[str] = set()
    known_candidate_ids = seen_candidates
    for index, review in enumerate(candidate_reviews):
        prefix = f"candidate_reviews[{index}]"
        if not isinstance(review, dict):
            errors.append(f"{prefix}_must_be_object")
            continue
        for field in CANDIDATE_REVIEW_REQUIRED:
            if not _nonempty(review.get(field)):
                errors.append(f"{prefix}_{field}_required")
        candidate_id = review.get("candidate_id")
        if _nonempty(candidate_id):
            if candidate_id in seen_review_ids:
                errors.append(f"{prefix}_candidate_id_duplicate")
            seen_review_ids.add(candidate_id)
            if candidate_id not in known_candidate_ids:
                errors.append(f"{prefix}_candidate_id_unknown")
        if review.get("relevance_label") not in RELEVANCE_LABELS:
            errors.append(f"{prefix}_relevance_label_invalid")
        if not _valid_timestamp(review.get("reviewed_at")):
            errors.append(f"{prefix}_reviewed_at_must_be_timezone_aware_iso8601")
        if review.get("relevance_label") == "uncertain" and not _nonempty(review.get("rationale")):
            errors.append(f"{prefix}_uncertain_label_requires_rationale")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="path to a JSON evaluation record")
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid evaluation record: {exc}", file=sys.stderr)
        return 2
    errors = validate_record(record)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1
    print(json.dumps({"valid": True, "schema_version": SCHEMA_VERSION}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
