#!/usr/bin/env python3
"""Diagnose verification gaps in saved news snapshots without network access.

The analyzer reads a local JSON snapshot or a snapshot stored in a local Git
object. It does not collect news, run the production pipeline, mutate data, or
send notifications. Diagnostics are heuristics for investigation, not truth
labels or a replacement verification score.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = "data/operational_snapshot.json"
MIN_INDEPENDENT_SOURCES = 2
MAX_EVIDENCE_AGE_HOURS = 72


def read_snapshot_from_git(revision: str) -> dict[str, Any]:
    """Read a snapshot from an already available local Git object."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{SNAPSHOT_PATH}"],
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


def _snapshot_day(value: Any) -> date | None:
    raw = str(value or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_published(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _headline_match(headline: str, article: dict[str, Any]) -> tuple[bool, float]:
    """Reuse the production event-match rules without searching for articles."""
    from app.research import (
        _event_similarity,
        _relaxed_event_match,
        _strong_event_match,
    )

    title = str(article.get("title", "") or article.get("headline", "") or "")
    score = _event_similarity(headline, title)
    accepted = score >= 0.55 or _strong_event_match(headline, "", article) or _relaxed_event_match(headline, "", article)
    return accepted, round(score, 3)


def analyze_snapshot(label: str, revision: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify saved evidence gaps using persisted fields and production helpers."""
    from app.research import _is_derivative_report, _same_reporting_copy, _source_key

    intelligence = snapshot.get("intelligence_v5") or {}
    stories = intelligence.get("stories", [])
    if not isinstance(stories, list):
        raise ValueError(f"{label}: intelligence_v5.stories must be a list")

    snapshot_date = _snapshot_day(snapshot.get("date"))
    rows: list[dict[str, Any]] = []
    diagnostic_counts: dict[str, int] = {}
    for index, story in enumerate(stories):
        if not isinstance(story, dict):
            continue
        headline = str(story.get("headline", "") or "(untitled)")
        verification = story.get("verification") or {}
        if not isinstance(verification, dict):
            verification = {}
        evidence = verification.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []

        try:
            independent_sources = max(0, int(verification.get("independent_sources", 0) or 0))
        except (TypeError, ValueError):
            independent_sources = 0
        official = bool(verification.get("official_source"))
        diagnostics: list[str] = []
        details: dict[str, Any] = {}

        if not evidence:
            diagnostics.append("no_saved_corroborating_evidence")
        if not official and independent_sources < MIN_INDEPENDENT_SOURCES:
            diagnostics.append(
                "no_independent_sources" if independent_sources == 0 else "only_one_independent_source"
            )

        freshness_hours = verification.get("freshness_hours")
        try:
            primary_age = float(freshness_hours) if freshness_hours is not None else None
        except (TypeError, ValueError):
            primary_age = None
        primary_fresh = verification.get("primary_fresh")
        if primary_fresh is False or (primary_age is not None and primary_age > MAX_EVIDENCE_AGE_HOURS):
            diagnostics.append("primary_article_stale_by_recorded_metadata")
        elif primary_fresh is None and primary_age is None:
            diagnostics.append("primary_freshness_unknown")
        if not str(story.get("published", "") or "").strip():
            diagnostics.append("primary_publication_time_missing")
        if verification.get("primary_derivative") is True:
            diagnostics.append("primary_source_marked_derivative")
        if verification.get("contradiction_flag") is True:
            diagnostics.append("contradiction_flagged")

        publisher_keys: list[str] = []
        derivative_count = 0
        weak_matches: list[dict[str, Any]] = []
        missing_evidence_dates = 0
        definitely_stale_evidence = 0
        duplicate_copy_pairs = 0
        retained_for_copy_check: list[dict[str, Any]] = []

        for article in evidence:
            if not isinstance(article, dict):
                continue
            source_key = _source_key(article.get("source", ""), article.get("url", ""))
            if source_key:
                publisher_keys.append(source_key)
            if _is_derivative_report(article):
                derivative_count += 1
            if any(_same_reporting_copy(article, prior) for prior in retained_for_copy_check):
                duplicate_copy_pairs += 1
            else:
                retained_for_copy_check.append(article)

            published = _parse_published(article.get("published"))
            if published is None:
                missing_evidence_dates += 1
            elif snapshot_date is not None:
                # Use the start of the snapshot day as a conservative reference:
                # an item already >72h old at that point is definitely over 72h
                # old at any time later that day. This avoids inventing a run time.
                as_of_start = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
                if as_of_start - published > timedelta(hours=MAX_EVIDENCE_AGE_HOURS):
                    definitely_stale_evidence += 1

            matched, score = _headline_match(headline, article)
            if not matched:
                weak_matches.append({
                    "source": str(article.get("source", "") or "(unknown source)"),
                    "title": str(article.get("title", "") or article.get("headline", "") or "(untitled)"),
                    "event_similarity": score,
                })

        duplicate_publishers = sorted({
            key for key in publisher_keys if publisher_keys.count(key) > 1
        })
        if duplicate_publishers:
            diagnostics.append("duplicate_publisher_identity_in_saved_evidence")
        if duplicate_copy_pairs:
            diagnostics.append("near_identical_copy_in_saved_evidence")
        if derivative_count:
            diagnostics.append("derivative_or_roundup_evidence")
        if weak_matches:
            diagnostics.append("saved_evidence_weak_headline_match")
        if missing_evidence_dates:
            diagnostics.append("evidence_publication_time_missing")
        if definitely_stale_evidence:
            diagnostics.append("evidence_definitely_older_than_72h")

        details.update({
            "saved_evidence_rows": len([x for x in evidence if isinstance(x, dict)]),
            "recorded_independent_sources": independent_sources,
            "unique_saved_publishers": len(set(publisher_keys)),
            "duplicate_publisher_keys": duplicate_publishers,
            "derivative_evidence_rows": derivative_count,
            "near_identical_copy_rows": duplicate_copy_pairs,
            "weak_headline_matches": weak_matches,
            "evidence_dates_missing": missing_evidence_dates,
            "evidence_definitely_stale_rows": definitely_stale_evidence,
            "primary_freshness_hours_recorded": primary_age,
        })
        row = {
            "index": index,
            "headline": headline,
            "primary_source": str(story.get("source", "") or "(unknown source)"),
            "verification_tier": str(verification.get("verification", "") or "unknown"),
            "verification_reason": str(verification.get("verification_reason", "") or ""),
            "diagnostics": diagnostics,
            "details": details,
        }
        rows.append(row)
        for diagnostic in diagnostics:
            diagnostic_counts[diagnostic] = diagnostic_counts.get(diagnostic, 0) + 1

    independent_distribution = {
        "zero_independent_sources": sum(1 for row in rows if row["details"]["recorded_independent_sources"] == 0),
        "one_independent_source": sum(1 for row in rows if row["details"]["recorded_independent_sources"] == 1),
        "two_or_more_independent_sources": sum(1 for row in rows if row["details"]["recorded_independent_sources"] >= 2),
    }
    return {
        "snapshot_date": str(snapshot.get("date") or label),
        "revision": revision,
        "stories_analyzed": len(rows),
        "independent_source_distribution": independent_distribution,
        "diagnostic_story_counts": dict(sorted(diagnostic_counts.items())),
        "stories": rows,
        "scope_note": (
            "Offline diagnostics over saved snapshot fields and saved evidence only. "
            "A missing evidence row does not prove no corroboration existed in the original candidate pool. "
            "Heuristic flags require review and are not accuracy labels."
        ),
    }


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Offline verification-gap analysis",
        "",
        "Generated from saved operational snapshots using the current production publisher and event-match helpers.",
        "",
        "| Snapshot | Revision | Stories analyzed | Zero independent sources | One independent source | Two or more |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for result in results:
        dist = result["independent_source_distribution"]
        lines.append(
            f"| {result['snapshot_date']} | `{result['revision']}` | {result['stories_analyzed']} | "
            f"{dist['zero_independent_sources']} | {dist['one_independent_source']} | "
            f"{dist['two_or_more_independent_sources']} |"
        )
        if result["diagnostic_story_counts"]:
            lines.extend(["", f"## Diagnostic counts — {result['snapshot_date']}", "",
                          "| Diagnostic | Stories flagged |", "|---|---:|"])
            for name, count in result["diagnostic_story_counts"].items():
                lines.append(f"| `{name}` | {count} |")
        lines.extend(["", f"## Story-level findings — {result['snapshot_date']}", "",
                      "| Headline | Tier | Independent sources | Saved evidence | Findings |",
                      "|---|---|---:|---:|---|"])
        for row in result["stories"]:
            headline = row["headline"].replace("|", "\\|")
            findings = ", ".join(row["diagnostics"]) or "no gap flagged by these heuristics"
            lines.append(
                f"| {headline} | {row['verification_tier']} | "
                f"{row['details']['recorded_independent_sources']} | "
                f"{row['details']['saved_evidence_rows']} | {findings} |"
            )
    lines.extend([
        "",
        "## Interpretation and limitations",
        "",
        "- This report is an offline diagnostic, not a new verification score or a claim about factual accuracy.",
        "- Saved evidence is incomplete by design; no saved corroboration does not prove no candidate existed.",
        "- Evidence age is flagged only when it is already over 72 hours at the start of the snapshot date, avoiding assumptions about the exact run time.",
        "- Publisher aliases, roundup detection, and headline matching reuse current production helpers; flags can still be false positives or false negatives.",
        "- No network calls, production execution, snapshot mutation, or Telegram delivery occur.",
        "",
    ])
    return "\n".join(lines)


def _parse_revision(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    label, revision = value.split("=", 1)
    if not label.strip() or not revision.strip():
        raise argparse.ArgumentTypeError("revision must be DATE=GIT_SHA")
    return label.strip(), revision.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision",
        action="append",
        type=_parse_revision,
        metavar="DATE=GIT_SHA",
        help="local Git snapshot revision; repeat to analyze multiple snapshots (default: HEAD)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown report (default)")
    args = parser.parse_args(argv)

    revisions = args.revision or [("HEAD", "HEAD")]
    results: list[dict[str, Any]] = []
    try:
        for label, revision in revisions:
            results.append(analyze_snapshot(label, revision, read_snapshot_from_git(revision)))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
