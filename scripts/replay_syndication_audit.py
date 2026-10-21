#!/usr/bin/env python3
"""Replay near-identical reporting-copy exclusions against saved Git snapshots.

This is an offline audit utility. It reads only local Git objects and never
fetches news, changes production data, or sends notifications.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVISIONS = (
    ("2026-10-19", "14f385a048bbb6a2f28a32a528c1dbd36881dbb5"),
    ("2026-10-20", "57e7c97c17fe39baf829ef4f5d9be521bfaed2d0"),
    ("2026-10-21", "8626e62e354567f7dbaf02afb74791bdbb10074f"),
)


def read_snapshot_from_git(revision: str) -> dict[str, Any]:
    """Read a historical snapshot from an already available local Git object."""
    result = subprocess.run(
        ["git", "show", f"{revision}:data/operational_snapshot.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"{revision}: snapshot root must be a JSON object")
    return value


def analyze_snapshot(label: str, revision: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Apply the production copy detector in stored evidence order."""
    # Import lazily so parsing/help and tests of input handling do not initialize
    # unrelated pipeline components.
    from app.research import _same_reporting_copy

    stories = snapshot.get("intelligence_v5", {}).get("stories", [])
    if not isinstance(stories, list):
        raise ValueError(f"{label}: intelligence_v5.stories must be a list")

    evidence_rows = 0
    excluded = 0
    affected: list[dict[str, Any]] = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        verification = story.get("verification") or {}
        evidence = verification.get("evidence", []) if isinstance(verification, dict) else []
        if not isinstance(evidence, list):
            continue
        evidence_rows += len(evidence)
        retained: list[dict[str, Any]] = []
        story_excluded = 0
        for article in evidence:
            if not isinstance(article, dict):
                continue
            if any(_same_reporting_copy(article, previous) for previous in retained):
                story_excluded += 1
                continue
            retained.append(article)
        excluded += story_excluded
        if story_excluded:
            affected.append({
                "headline": str(story.get("headline", "") or "(untitled)"),
                "evidence_rows": len(evidence),
                "likely_copies_excluded": story_excluded,
                "rows_retained": len(retained),
            })

    return {
        "snapshot_date": str(snapshot.get("date") or label),
        "revision": revision,
        "stories": len(stories),
        "saved_evidence_rows": evidence_rows,
        "likely_copies_excluded": excluded,
        "retained_rows_estimate": evidence_rows - excluded,
        "affected_stories": affected,
        "scope_note": (
            "Retrospective estimate over saved evidence only; it cannot identify "
            "copies that were never stored in this snapshot."
        ),
    }


def _parse_revision(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    label, revision = value.split("=", 1)
    if not label.strip() or not revision.strip():
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    return label.strip(), revision.strip()


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Historical syndication replay",
        "",
        "Generated from locally available Git snapshots using the current "
        "`app.research._same_reporting_copy` detector.",
        "",
        "| Snapshot date | Revision | Stories | Saved evidence rows | Likely copies excluded | Retained rows (estimate) | Affected stories |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            "| {snapshot_date} | `{revision}` | {stories} | {saved_evidence_rows} | "
            "{likely_copies_excluded} | {retained_rows_estimate} | {affected} |".format(
                **result, affected=len(result["affected_stories"])
            )
        )
    for result in results:
        if not result["affected_stories"]:
            continue
        lines.extend(["", f"## {result['snapshot_date']} — affected stories", ""])
        lines.extend([
            "| Headline | Evidence rows | Likely copies excluded | Retained rows |",
            "|---|---:|---:|---:|",
        ])
        for story in result["affected_stories"]:
            headline = story["headline"].replace("|", "\\|")
            lines.append(
                f"| {headline} | {story['evidence_rows']} | "
                f"{story['likely_copies_excluded']} | {story['rows_retained']} |"
            )
    lines.extend([
        "",
        "## Limitations",
        "",
        "- These are retrospective estimates, not recorded historical runtime metrics.",
        "- Only evidence rows present in each snapshot are examined; excluded or undiscovered candidates are unavailable.",
        "- Similarity flags indicate likely near-identical copy, not proven publisher syndication.",
        "- This command reads local Git objects only. It does not access the network, run the news pipeline, modify snapshots, or send Telegram messages.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision",
        action="append",
        type=_parse_revision,
        metavar="DATE=GIT_SHA",
        help="local Git revision to replay; may be repeated (defaults to the three audited snapshots)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    revisions = args.revision or list(DEFAULT_REVISIONS)
    results = []
    try:
        for label, revision in revisions:
            results.append(analyze_snapshot(label, revision, read_snapshot_from_git(revision)))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
