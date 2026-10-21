#!/usr/bin/env python3
"""Audit whether saved news snapshots can support a labelled historical evaluation.

This is an offline schema/readiness audit. It never fetches news, runs the
production pipeline, changes production decisions, or sends notifications.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = "data/operational_snapshot.json"
LABEL_FIELDS = ("ground_truth_label", "human_label", "verified_outcome")
POOL_FIELDS = ("candidate_articles", "article_pool", "raw_articles")


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def audit_snapshot(snapshot: dict[str, Any], revision: str = "working-tree") -> dict[str, Any]:
    """Report persisted evidence coverage without inferring truth labels."""
    intelligence = snapshot.get("intelligence_v5")
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    stories = intelligence.get("stories")
    stories = stories if isinstance(stories, list) else []

    explicit_pool = any(_present(snapshot.get(key)) for key in POOL_FIELDS)
    explicit_pool = explicit_pool or any(_present(intelligence.get(key)) for key in POOL_FIELDS)

    total_evidence_rows = 0
    stories_with_evidence = 0
    labelled_stories = 0
    stories_with_identity = 0
    evidence_field_counts = {key: 0 for key in ("title", "source", "url", "published", "summary")}
    story_field_counts = {key: 0 for key in ("story_id", "headline", "verification.evidence")}
    for story in stories:
        if not isinstance(story, dict):
            continue
        if _present(story.get("story_id")):
            story_field_counts["story_id"] += 1
        if _present(story.get("headline")):
            story_field_counts["headline"] += 1
        if _present(story.get("story_id")) or _present(story.get("headline")):
            stories_with_identity += 1
        verification = story.get("verification")
        verification = verification if isinstance(verification, dict) else {}
        evidence = verification.get("evidence")
        if isinstance(evidence, list):
            story_field_counts["verification.evidence"] += 1
            total_evidence_rows += len(evidence)
            if evidence:
                stories_with_evidence += 1
            for article in evidence:
                if not isinstance(article, dict):
                    continue
                for key in evidence_field_counts:
                    if _present(article.get(key)) or (key == "title" and _present(article.get("headline"))):
                        evidence_field_counts[key] += 1
        if any(_present(story.get(key)) for key in LABEL_FIELDS):
            labelled_stories += 1

    story_count = sum(isinstance(story, dict) for story in stories)
    has_story_records = story_count > 0
    has_saved_evidence = has_story_records and total_evidence_rows > 0
    has_labels = labelled_stories > 0
    replayable = has_story_records and explicit_pool and has_labels
    blockers = []
    if not has_story_records:
        blockers.append("no_intelligence_v5_story_records")
    if not explicit_pool:
        blockers.append("original_candidate_article_pool_not_persisted")
    if not has_labels:
        blockers.append("human_or_verified_story_labels_not_persisted")
    warnings = []
    if has_story_records and not has_saved_evidence:
        warnings.append("saved_verification_evidence_rows_not_persisted")

    return {
        "audit_type": "historical_evaluation_readiness",
        "revision": revision,
        "snapshot_date": str(snapshot.get("date") or ""),
        "story_records": story_count,
        "stories_with_identity": stories_with_identity,
        "saved_evidence_rows": total_evidence_rows,
        "stories_with_saved_evidence": stories_with_evidence,
        "stories_with_evidence_field": story_field_counts["verification.evidence"],
        "explicit_candidate_pool_available": explicit_pool,
        "labelled_stories": labelled_stories,
        "saved_evidence_replay_possible": has_saved_evidence,
        "labelled_historical_evaluation_ready": replayable,
        "blockers": blockers,
        "warnings": warnings,
        "story_field_coverage": story_field_counts,
        "evidence_field_row_coverage": evidence_field_counts,
        "required_for_trustworthy_evaluation": [
            "the original candidate article pool for each run, including excluded candidates",
            "stable story identity and headline",
            "source/publisher, URL, publication timestamp, title and summary for each candidate",
            "a human-reviewed or otherwise independently verified story-level truth label",
            "the snapshot/run timestamp and the policy version being evaluated",
        ],
        "limitations": [
            "Saved evidence replay is not a substitute for the original candidate pool.",
            "Missing labels are not inferred from verification decisions or publisher reputation.",
            "Field presence does not establish field correctness or factual truth.",
            "This audit is read-only and does not change production verification, ranking, or delivery.",
        ],
    }


def read_snapshot_from_git(revision: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{revision}:{SNAPSHOT_PATH}"],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"{revision}: snapshot root must be a JSON object")
    return value


def _parse_revision(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    label, revision = value.split("=", 1)
    if not label.strip() or not revision.strip():
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    return label.strip(), revision.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="JSON snapshot path (defaults to data/operational_snapshot.json)")
    parser.add_argument("--revision", action="append", type=_parse_revision, metavar="DATE=GIT_SHA",
                        help="historical Git snapshot to audit; may be repeated")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        if args.revision:
            results = [audit_snapshot(read_snapshot_from_git(sha), sha) for _, sha in args.revision]
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                print("\n".join(
                    f"{row['snapshot_date'] or row['revision']}: {row['story_records']} stories; "
                    f"saved-evidence replay={'yes' if row['saved_evidence_replay_possible'] else 'no'}; "
                    f"labelled evaluation={'ready' if row['labelled_historical_evaluation_ready'] else 'blocked'} "
                    f"({', '.join(row['blockers']) or 'no blockers'})"
                    for row in results
                ))
            return 0
        path = args.snapshot or (ROOT / SNAPSHOT_PATH)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot root must be a JSON object")
        result = audit_snapshot(snapshot, str(path))
    except (OSError, json.JSONDecodeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else (
        f"{result['snapshot_date'] or result['revision']}: {result['story_records']} stories, "
        f"{result['saved_evidence_rows']} saved evidence rows; "
        f"labelled historical evaluation "
        f"{'READY' if result['labelled_historical_evaluation_ready'] else 'BLOCKED'}; "
        f"blockers: {', '.join(result['blockers']) or 'none'}"
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
