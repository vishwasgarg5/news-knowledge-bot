#!/usr/bin/env python3
"""Create a reproducible, stratified human-review queue from captured records.

Offline/read-only: selects candidates for review but never creates labels or
changes production records. Reviewers must independently fill the output queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any


DISPOSITIONS = ("included", "excluded", "duplicate", "out_of_scope")


def select_review_queue(record: dict[str, Any], per_disposition: int = 10, seed: str = "news-eval-v1") -> dict[str, Any]:
    if per_disposition < 1:
        raise ValueError("per_disposition must be at least 1")
    candidates = record.get("candidate_articles", [])
    if not isinstance(candidates, list):
        raise ValueError("candidate_articles must be a list")
    already_reviewed = {
        row.get("candidate_id")
        for row in record.get("candidate_reviews", [])
        if isinstance(row, dict) and row.get("candidate_id")
    }
    queue = []
    strata = {}
    for disposition in DISPOSITIONS:
        eligible = [
            row for row in candidates
            if isinstance(row, dict)
            and row.get("disposition") == disposition
            and row.get("candidate_id")
            and row.get("candidate_id") not in already_reviewed
        ]
        # Stable hash ordering avoids dependence on input order or Python's hash seed.
        eligible.sort(key=lambda row: hashlib.sha256(
            f"{seed}|{record.get('run_id', '')}|{disposition}|{row['candidate_id']}".encode("utf-8")
        ).hexdigest())
        selected = eligible[:per_disposition]
        strata[disposition] = {
            "eligible_unreviewed": len(eligible),
            "selected": len(selected),
            "selection_rate": len(selected) / len(eligible) if eligible else None,
        }
        for row in selected:
            queue.append({
                "candidate_id": row["candidate_id"],
                "disposition": disposition,
                "title": row.get("title", ""),
                "source": row.get("source", ""),
                "url": row.get("url", ""),
                "published_at": row.get("published_at", ""),
                "summary": row.get("summary", ""),
                "relevance_label": "",
                "reviewer_id": "",
                "reviewed_at": "",
                "rationale": "",
            })
    return {
        "queue_schema_version": "1.0",
        "run_id": record.get("run_id", ""),
        "policy_version": record.get("policy_version", ""),
        "sampling_method": "deterministic_stratified_by_disposition",
        "sampling_seed": seed,
        "per_disposition_cap": per_disposition,
        "strata": strata,
        "review_instructions": [
            "Review relevance independently of production verification status.",
            "Use relevant, not_relevant, or uncertain; provide reviewer_id, timezone-aware reviewed_at, and rationale.",
            "Do not infer labels for unreviewed candidates. Preserve the sampling metadata when reporting metrics.",
        ],
        "reviews": queue,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="captured evaluation record JSON")
    parser.add_argument("--per-disposition", type=int, default=10, help="maximum candidates selected from each disposition (default: 10)")
    parser.add_argument("--seed", default="news-eval-v1", help="stable sampling seed")
    parser.add_argument("--output", type=Path, help="output queue path (default: print to stdout)")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("record root must be a JSON object")
        queue = select_review_queue(record, args.per_disposition, args.seed)
        rendered = json.dumps(queue, indent=2, ensure_ascii=False) + "\n"
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
