#!/usr/bin/env python3
"""Append-only, offline history and trend report for policy evaluation artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_history_entry(
    comparison: dict[str, Any],
    baseline_audit: dict[str, Any],
    candidate_audit: dict[str, Any],
    regression_gate: dict[str, Any],
    release_decision: dict[str, Any],
    artifact_hashes: dict[str, str],
    recorded_at: str | None = None,
) -> dict[str, Any]:
    deltas = comparison.get("metric_deltas_candidate_minus_baseline", {})
    base_metrics = comparison.get("baseline_metrics", {})
    cand_metrics = comparison.get("candidate_metrics", {})
    base_coverage = baseline_audit.get("checks", [])
    cand_coverage = candidate_audit.get("checks", [])

    def observed_coverage(checks: Any) -> Any:
        if not isinstance(checks, list):
            return None
        for check in checks:
            if isinstance(check, dict) and check.get("name") == "minimum_review_coverage":
                return check.get("observed")
        return None

    artifact_identity = {
        "baseline_policy_version": baseline_audit.get("policy_version"),
        "candidate_policy_version": candidate_audit.get("policy_version"),
        "artifact_sha256": artifact_hashes,
    }
    run_id = hashlib.sha256(
        json.dumps(artifact_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    entry = {
        "history_schema_version": "1.0",
        "run_id": run_id,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "baseline_policy_version": baseline_audit.get("policy_version"),
        "candidate_policy_version": candidate_audit.get("policy_version"),
        "comparison_status": comparison.get("status"),
        "baseline_metrics": base_metrics,
        "candidate_metrics": cand_metrics,
        "metric_deltas_candidate_minus_baseline": deltas,
        "baseline_review_coverage": observed_coverage(base_coverage),
        "candidate_review_coverage": observed_coverage(cand_coverage),
        "baseline_gate_status": baseline_audit.get("status"),
        "candidate_gate_status": candidate_audit.get("status"),
        "regression_gate_status": regression_gate.get("status"),
        "release_decision": release_decision.get("decision"),
        "release_blockers": release_decision.get("blockers", []),
        "artifact_sha256": artifact_hashes,
        "interpretation": {
            "is_descriptive_only": True,
            "note": "Observed results on the reviewed set; not proof of causality or statistical significance.",
        },
    }
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    entry["entry_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return entry


def append_history(history_path: Path, entry: dict[str, Any]) -> bool:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if history_path.exists():
        raw = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("history_schema_version") != "1.0" or not isinstance(raw.get("entries"), list):
            raise ValueError("existing history has an unsupported or invalid schema")
        existing = raw["entries"]
        if not all(isinstance(row, dict) and row.get("entry_sha256") for row in existing):
            raise ValueError("existing history contains an invalid entry")
        if any(row.get("run_id") == entry["run_id"] for row in existing):
            return False
    existing.append(entry)
    document = {
        "history_schema_version": "1.0",
        "append_only_by_default": True,
        "entries": existing,
    }
    history_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def build_trends(history: dict[str, Any]) -> dict[str, Any]:
    entries = history.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("history entries must be a list")
    trends = []
    previous: dict[str, Any] | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        trends.append({
            "recorded_at": entry.get("recorded_at"),
            "baseline_policy_version": entry.get("baseline_policy_version"),
            "candidate_policy_version": entry.get("candidate_policy_version"),
            "inclusion_precision": entry.get("candidate_metrics", {}).get("inclusion_precision"),
            "inclusion_recall": entry.get("candidate_metrics", {}).get("inclusion_recall"),
            "false_positives": entry.get("candidate_metrics", {}).get("false_positives"),
            "missed_relevant_candidates": entry.get("candidate_metrics", {}).get("missed_relevant_candidates"),
            "review_coverage": entry.get("candidate_review_coverage"),
            "release_decision": entry.get("release_decision"),
            "entry_sha256": entry.get("entry_sha256"),
        })
        previous = entry
    return {
        "trend_schema_version": "1.0",
        "entry_count": len(trends),
        "trends": trends,
        "latest": trends[-1] if trends else None,
        "warnings": [
            "Rows may represent different policy pairs, samples, or adjudication cohorts; do not infer a time trend unless cohorts are comparable.",
            "History hashes detect accidental changes but do not provide cryptographic signing or prevent a privileged user from rewriting the file.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="append a release/evaluation run to history")
    record.add_argument("--comparison", required=True, type=Path)
    record.add_argument("--baseline-audit", required=True, type=Path)
    record.add_argument("--candidate-audit", required=True, type=Path)
    record.add_argument("--regression-gate", required=True, type=Path)
    record.add_argument("--release-decision", required=True, type=Path)
    record.add_argument("--history", required=True, type=Path)
    record.add_argument("--recorded-at", help="optional timezone-aware ISO-8601 timestamp")
    trend = sub.add_parser("trends", help="write a trend report from an existing history")
    trend.add_argument("--history", required=True, type=Path)
    trend.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "record":
            paths = {
                "comparison": args.comparison,
                "baseline_audit": args.baseline_audit,
                "candidate_audit": args.candidate_audit,
                "regression_gate": args.regression_gate,
                "release_decision": args.release_decision,
            }
            if args.recorded_at:
                parsed = datetime.fromisoformat(args.recorded_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("--recorded-at must include a timezone")
            values = {key: _load(path) for key, path in paths.items()}
            entry = build_history_entry(
                values["comparison"], values["baseline_audit"], values["candidate_audit"],
                values["regression_gate"], values["release_decision"],
                {key: _digest(path) for key, path in paths.items()}, args.recorded_at,
            )
            inserted = append_history(args.history, entry)
            print(json.dumps({"inserted": inserted, "entry_sha256": entry["entry_sha256"], "history": str(args.history)}, indent=2))
            return 0
        history = _load(args.history)
        trends = build_trends(history)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(trends, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"entry_count": trends["entry_count"], "output": str(args.output)}, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
