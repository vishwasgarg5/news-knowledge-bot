#!/usr/bin/env python3
"""Build a deterministic, blinded offline candidate-review packet.

The reviewer queue omits pipeline dispositions. A separate answer key retains
those dispositions for a later, independent comparison. No labels are generated.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

DISPOSITIONS = ("included", "excluded", "duplicate", "out_of_scope")
EVIDENCE_FIELDS = ("title", "source", "url", "published_at", "summary")
BLANK_REVIEW = {
    "relevance_label": "",
    "reviewer_id": "",
    "reviewed_at": "",
    "rationale": "",
    "evidence_urls": [],
}


def load_records(path: Path) -> list[tuple[str, dict[str, Any]]]:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not paths:
        raise ValueError(f"no JSON records found at {path}")
    records = []
    for record_path in paths:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {record_path}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{record_path}: record root must be an object")
        candidates = record.get("candidate_articles")
        if not isinstance(candidates, list):
            raise ValueError(f"{record_path}: candidate_articles must be a list")
        records.append((str(record_path), record))
    return records


def build_packet(
    records: list[tuple[str, dict[str, Any]]],
    *,
    sample_per_disposition: int = 25,
    seed: str = "20261022",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return blinded review queue and separate disposition answer key."""
    if not records:
        raise ValueError("no JSON records supplied")
    if sample_per_disposition < 1:
        raise ValueError("sample_per_disposition must be at least 1")
    groups: dict[str, list[dict[str, Any]]] = {value: [] for value in DISPOSITIONS}
    seen_item_ids: set[str] = set()
    for record_path, record in records:
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(f"{record_path}: run_id must be a non-empty string")
        candidates = record["candidate_articles"]
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise ValueError(f"{record_path}: candidate_articles[{index}] must be an object")
            candidate_id = candidate.get("candidate_id")
            disposition = candidate.get("disposition")
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise ValueError(f"{record_path}: candidate_articles[{index}] has no candidate_id")
            if disposition not in groups:
                raise ValueError(f"{record_path}: candidate_articles[{index}] has invalid disposition")
            item_id = f"{run_id}::{candidate_id}"
            if item_id in seen_item_ids:
                raise ValueError(f"duplicate review item id: {item_id}")
            seen_item_ids.add(item_id)
            groups[disposition].append({
                "item_id": item_id,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "record_path": record_path,
                "policy_version": record.get("policy_version", ""),
                "candidate": candidate,
                "disposition": disposition,
            })

    rng = random.Random(str(seed))
    queue_items = []
    key_items = []
    selected_counts = {}
    available_counts = {}
    for disposition in DISPOSITIONS:
        group = sorted(groups[disposition], key=lambda row: row["item_id"])
        available_counts[disposition] = len(group)
        selected = rng.sample(group, min(sample_per_disposition, len(group)))
        selected.sort(key=lambda row: row["item_id"])
        selected_counts[disposition] = len(selected)
        for row in selected:
            candidate = row["candidate"]
            queue_item = {
                "item_id": row["item_id"],
                "run_id": row["run_id"],
                "candidate_id": row["candidate_id"],
                **{
                    field: candidate.get(field, "") if isinstance(candidate.get(field, ""), str) else ""
                    for field in EVIDENCE_FIELDS
                },
                "review": dict(BLANK_REVIEW),
            }
            queue_items.append(queue_item)
            key_items.append({
                "item_id": row["item_id"],
                "run_id": row["run_id"],
                "candidate_id": row["candidate_id"],
                "pipeline_disposition": row["disposition"],
                "source_record": row["record_path"],
                "policy_version": row["policy_version"],
            })

    queue_items.sort(key=lambda row: row["item_id"])
    key_items.sort(key=lambda row: row["item_id"])
    queue = {
        "packet_type": "blinded_candidate_relevance_review",
        "packet_version": "1.0",
        "sampling": {
            "method": "deterministic_stratified_random_sample_by_pipeline_disposition",
            "seed": str(seed),
            "maximum_per_disposition": sample_per_disposition,
            "available_by_disposition": available_counts,
            "selected_by_disposition": selected_counts,
        },
        "instructions": (
            "Review relevance from the candidate evidence and your stated review criteria. "
            "Do not infer a label from the candidate ID. Use relevant, not_relevant, or uncertain; "
            "record reviewer_id, timezone-aware reviewed_at, rationale, and evidence_urls. "
            "The pipeline disposition is intentionally omitted."
        ),
        "items": queue_items,
        "limitations": [
            "Blinding reduces one source of reviewer bias but does not ensure a representative sample.",
            "The packet does not fetch, verify, enrich, or label candidate evidence.",
            "Blank or missing evidence fields remain blank; they are not synthesized.",
            "The separate answer key must be stored away from reviewers until labels are submitted.",
        ],
    }
    answer_key = {
        "packet_type": "candidate_review_answer_key",
        "packet_version": "1.0",
        "seed": str(seed),
        "items": key_items,
        "warning": "Keep this file separate from the reviewer queue until independent labels are finalized.",
    }
    return queue, answer_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="record JSON file or directory of record JSON files")
    parser.add_argument("--queue-output", type=Path, required=True, help="path for blinded review queue JSON")
    parser.add_argument("--key-output", type=Path, required=True, help="path for separate answer-key JSON")
    parser.add_argument("--sample-per-disposition", type=int, default=25)
    parser.add_argument("--seed", default="20261022", help="deterministic sampling seed")
    args = parser.parse_args(argv)
    if args.queue_output.resolve() == args.key_output.resolve():
        parser.error("--queue-output and --key-output must be different paths")
    try:
        records = load_records(args.input)
        queue, answer_key = build_packet(
            records, sample_per_disposition=args.sample_per_disposition, seed=args.seed
        )
        args.queue_output.parent.mkdir(parents=True, exist_ok=True)
        args.key_output.parent.mkdir(parents=True, exist_ok=True)
        args.queue_output.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        args.key_output.write_text(json.dumps(answer_key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"Cannot build review packet: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "review_packet_created",
        "queue_output": str(args.queue_output),
        "answer_key_output": str(args.key_output),
        "selected_count": len(queue["items"]),
        "selected_by_disposition": queue["sampling"]["selected_by_disposition"],
        "seed": str(args.seed),
        "labels_created": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
