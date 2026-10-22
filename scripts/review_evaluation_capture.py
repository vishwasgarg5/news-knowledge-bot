#!/usr/bin/env python3
"""Apply an explicit human label to a captured candidate group.

Offline-only: reads and updates one local capture JSON file. It never fetches
articles, infers labels from model decisions, or sends notifications.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LABELS = {"supported", "unsupported", "uncertain"}


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def apply_human_label(
    record: dict[str, Any],
    *,
    story_id: str,
    label: str,
    reviewer: str,
    rationale: str,
    candidate_ids: list[str],
    evidence_urls: list[str],
    reviewed_at: str | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Return a validated updated record; caller decides whether to persist it."""
    if label not in LABELS:
        raise ValueError(f"label must be one of: {', '.join(sorted(LABELS))}")
    if not story_id.strip() or not reviewer.strip() or not rationale.strip():
        raise ValueError("story_id, reviewer, and rationale must be non-empty")
    if not candidate_ids or any(not item.strip() for item in candidate_ids):
        raise ValueError("at least one non-empty candidate_id is required")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate_ids must be unique")
    if label in {"supported", "unsupported"} and not evidence_urls:
        raise ValueError("supported/unsupported labels require at least one independent evidence URL")
    if any(not _valid_http_url(url) for url in evidence_urls):
        raise ValueError("evidence URLs must be absolute http(s) URLs")

    candidates = record.get("candidate_articles")
    if not isinstance(candidates, list):
        raise ValueError("record candidate_articles must be a list")
    known_ids = {row.get("candidate_id") for row in candidates if isinstance(row, dict)}
    missing_ids = sorted(set(candidate_ids) - known_ids)
    if missing_ids:
        raise ValueError(f"candidate_id not found in this capture: {', '.join(missing_ids)}")

    labels = record.get("story_labels")
    if not isinstance(labels, list):
        raise ValueError("record story_labels must be a list")
    existing_index = next(
        (index for index, item in enumerate(labels)
         if isinstance(item, dict) and item.get("story_id") == story_id),
        None,
    )
    if existing_index is not None and not replace_existing:
        raise ValueError(f"story_id {story_id!r} already has a label; use --replace-existing to amend it")

    timestamp = reviewed_at or datetime.now(timezone.utc).isoformat()
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    item = {
        "story_id": story_id.strip(),
        "label": label,
        "review_method": "human",
        "reviewer": reviewer.strip(),
        "reviewed_at": timestamp,
        "rationale": rationale.strip(),
        "candidate_ids": candidate_ids,
        "evidence_urls": list(dict.fromkeys(url.strip() for url in evidence_urls)),
    }
    updated = dict(record)
    updated_labels = list(labels)
    if existing_index is None:
        updated_labels.append(item)
    else:
        updated_labels[existing_index] = item
    updated["story_labels"] = updated_labels
    known_candidate_ids = {
        row.get("candidate_id") for row in candidates
        if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)
    }
    reviewed_candidate_ids = {
        candidate_id for row in updated_labels if isinstance(row, dict)
        for candidate_id in (row.get("candidate_ids") if isinstance(row.get("candidate_ids"), list) else [])
        if isinstance(candidate_id, str)
    }
    labels_valid = all(
        isinstance(row, dict) and row.get("label") in LABELS
        and str(row.get("reviewer", "")).strip()
        and str(row.get("rationale", "")).strip()
        for row in updated_labels
    )
    if not updated_labels:
        updated["labeling_status"] = "pending_review"
    elif labels_valid and known_candidate_ids and known_candidate_ids.issubset(reviewed_candidate_ids):
        updated["labeling_status"] = "reviewed"
    else:
        updated["labeling_status"] = "in_progress"
    return updated


def write_record_atomically(path: Path, record: dict[str, Any]) -> None:
    """Persist JSON atomically, replacing only the selected local record."""
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=".human-review-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True, help="path to one captured run JSON file")
    parser.add_argument("--story-id", required=True, help="stable ID for the story being reviewed")
    parser.add_argument("--label", required=True, choices=sorted(LABELS))
    parser.add_argument("--reviewer", required=True, help="reviewer identifier or initials")
    parser.add_argument("--rationale", required=True, help="brief evidence-based explanation")
    parser.add_argument("--candidate-id", action="append", required=True, dest="candidate_ids",
                        help="candidate ID in this capture; repeat to group multiple reports")
    parser.add_argument("--evidence-url", action="append", default=[], dest="evidence_urls",
                        help="independent source URL; repeat as needed")
    parser.add_argument("--replace-existing", action="store_true", help="explicitly amend an existing story label")
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("capture root must be a JSON object")
        updated = apply_human_label(
            record, story_id=args.story_id, label=args.label, reviewer=args.reviewer,
            rationale=args.rationale, candidate_ids=args.candidate_ids,
            evidence_urls=args.evidence_urls, replace_existing=args.replace_existing,
        )
        write_record_atomically(args.record, updated)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Saved human review for story {args.story_id!r} in {args.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
