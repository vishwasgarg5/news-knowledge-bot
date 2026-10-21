#!/usr/bin/env python3
"""Audit captured evaluation records and list which runs need human review.

Offline/read-only. Does not label stories, fetch sources, or run production code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "historical_evaluation_records"
REQUIRED_CANDIDATE_FIELDS = ("title", "source", "url", "published_at", "summary")


def audit_record(record: Any, path: str = "") -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"path": path, "status": "invalid", "errors": ["record_root_must_be_object"]}
    candidates = record.get("candidate_articles")
    if not isinstance(candidates, list):
        candidates = []
    included = sum(isinstance(row, dict) and row.get("disposition") == "included" for row in candidates)
    excluded = sum(isinstance(row, dict) and row.get("disposition") != "included" for row in candidates)
    incomplete = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            incomplete.append({"index": index, "missing": ["candidate_object"]})
            continue
        missing = [field for field in REQUIRED_CANDIDATE_FIELDS
                   if not isinstance(candidate.get(field), str) or not candidate[field].strip()]
        if missing:
            incomplete.append({"index": index, "candidate_id": candidate.get("candidate_id", ""), "missing": missing})
    labels = record.get("story_labels")
    labels = labels if isinstance(labels, list) else []
    state = str(record.get("labeling_status", "") or "")
    if state != "pending_review" and labels:
        status = "reviewed_labels_present"
    elif state == "pending_review" or not labels:
        status = "pending_review"
    else:
        status = "needs_attention"
    errors = []
    if not str(record.get("run_id", "")).strip():
        errors.append("run_id_missing")
    if not str(record.get("policy_version", "")).strip():
        errors.append("policy_version_missing")
    if not candidates:
        errors.append("candidate_pool_empty")
    if incomplete:
        errors.append("candidate_metadata_incomplete")
    return {
        "path": path,
        "run_id": record.get("run_id", ""),
        "run_timestamp": record.get("run_timestamp", ""),
        "policy_version": record.get("policy_version", ""),
        "status": status,
        "candidate_count": len(candidates),
        "included_count": included,
        "excluded_or_other_count": excluded,
        "label_count": len(labels),
        "incomplete_candidate_count": len(incomplete),
        "incomplete_candidates": incomplete,
        "errors": errors,
    }


def audit_directory(directory: Path) -> dict[str, Any]:
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    records = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(audit_record(record, str(path)))
        except (OSError, json.JSONDecodeError) as exc:
            records.append({"path": str(path), "status": "invalid", "errors": [f"read_or_json_error:{exc}"]})
    return {
        "audit_type": "evaluation_capture_review_queue",
        "directory": str(directory),
        "record_count": len(records),
        "pending_review_count": sum(row.get("status") == "pending_review" for row in records),
        "reviewed_record_count": sum(row.get("status") == "reviewed_labels_present" for row in records),
        "invalid_record_count": sum(row.get("status") == "invalid" for row in records),
        "records_with_issues": sum(bool(row.get("errors")) for row in records),
        "records": records,
        "limitations": [
            "This report checks capture completeness only; it does not establish factual truth.",
            "Production verification decisions are never treated as independent labels.",
            "A pending record must be reviewed independently before accuracy metrics are computed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR, help="directory containing captured JSON records")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    report = audit_directory(args.directory)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Captured records: {report['record_count']}; pending review: {report['pending_review_count']}; "
              f"reviewed: {report['reviewed_record_count']}; records with review issues: {report['records_with_issues']}; "
              f"unreadable/invalid: {report['invalid_record_count']}")
        for row in report["records"]:
            print(f"- {row.get('run_id') or row['path']}: {row['status']}; "
                  f"candidates={row.get('candidate_count', 0)}; labels={row.get('label_count', 0)}")
    return 1 if report["invalid_record_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
