#!/usr/bin/env python3
"""Offline trend report for evaluation capture metadata completeness."""
from __future__ import annotations
import argparse, json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "historical_evaluation_records"
FIELDS = ("title", "source", "url", "published_at", "summary")

def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())

def _record_quality(record: Any, path: Path) -> dict[str, Any]:
    timestamp = path.stem
    if isinstance(record, dict):
        raw_ts = record.get("run_timestamp")
        if isinstance(raw_ts, str) and raw_ts.strip():
            try: timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).isoformat()
            except ValueError: pass
    if not isinstance(record, dict):
        return {"path": str(path), "run_id": "", "timestamp": timestamp, "candidate_count": 0,
                "field_coverage": {f: 0.0 for f in FIELDS}, "missing_counts": {f: 0 for f in FIELDS}, "invalid_record": True}
    raw = record.get("candidate_articles")
    candidates = raw if isinstance(raw, list) else []
    rows = [row for row in candidates if isinstance(row, dict)]
    missing = {f: sum(not _nonempty(row.get(f)) for row in rows) for f in FIELDS}
    n = len(rows)
    # Category-level summary coverage makes future capture regressions diagnosable
    # without inferring missing article text or making network requests.
    category_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        category = str(row.get("category") or "").strip() or "unknown"
        category_groups.setdefault(category, []).append(row)
    summary_coverage_by_category = {
        category: {
            "candidate_count": len(group),
            "summary_present_count": sum(_nonempty(row.get("summary")) for row in group),
            "summary_missing_count": sum(not _nonempty(row.get("summary")) for row in group),
            "summary_coverage": round(sum(_nonempty(row.get("summary")) for row in group) / len(group), 4),
        }
        for category, group in sorted(category_groups.items())
    }
    return {"path": str(path), "run_id": str(record.get("run_id") or ""), "timestamp": timestamp,
            "candidate_count": n, "field_coverage": {f: round((n-missing[f])/n, 4) if n else 0.0 for f in FIELDS},
            "missing_counts": missing, "summary_coverage_by_category": summary_coverage_by_category,
            "invalid_record": not isinstance(raw, list) or len(rows) != len(candidates)}

def build_trend(records: list[tuple[Path, Any]]) -> dict[str, Any]:
    rows = sorted((_record_quality(record, path) for path, record in records), key=lambda row: (row["timestamp"], row["path"]))
    total = sum(row["candidate_count"] for row in rows)
    missing = {f: sum(row["missing_counts"][f] for row in rows) for f in FIELDS}
    coverage = {f: round((total-missing[f])/total, 4) if total else 0.0 for f in FIELDS}
    comparison, regressions = None, []
    if len(rows) >= 2:
        prev, latest = rows[-2], rows[-1]
        for f in FIELDS:
            before, after = prev["field_coverage"][f], latest["field_coverage"][f]
            if latest["candidate_count"] and after < before:
                regressions.append({"field": f, "previous_coverage": before, "latest_coverage": after, "delta": round(after-before, 4)})
        previous_categories = prev.get("summary_coverage_by_category", {})
        latest_categories = latest.get("summary_coverage_by_category", {})
        category_summary_coverage_delta = {}
        for category in sorted(set(previous_categories) | set(latest_categories)):
            before = previous_categories.get(category, {})
            after = latest_categories.get(category, {})
            before_coverage = before.get("summary_coverage")
            after_coverage = after.get("summary_coverage")
            category_summary_coverage_delta[category] = {
                "previous_candidate_count": before.get("candidate_count", 0),
                "latest_candidate_count": after.get("candidate_count", 0),
                "previous_summary_coverage": before_coverage,
                "latest_summary_coverage": after_coverage,
                "coverage_delta": round(after_coverage-before_coverage, 4)
                    if before_coverage is not None and after_coverage is not None else None,
            }
        comparison = {"previous_run_id": prev["run_id"], "latest_run_id": latest["run_id"],
                      "previous_timestamp": prev["timestamp"], "latest_timestamp": latest["timestamp"],
                      "coverage_delta": {f: round(latest["field_coverage"][f]-prev["field_coverage"][f], 4) for f in FIELDS},
                      "summary_coverage_by_category_delta": category_summary_coverage_delta,
                      "regressions": regressions}
    return {"audit_type": "evaluation_capture_quality_trend", "record_count": len(rows), "candidate_count": total,
            "overall_field_coverage": coverage, "missing_field_counts": missing, "latest_run": rows[-1] if rows else None,
            "previous_run_comparison": comparison,
            "quality_gate": {"status": "BLOCKED" if regressions else ("INSUFFICIENT_HISTORY" if len(rows)<2 else "PASS"),
                "regression_count": len(regressions),
                "limitations": ["Compares only the two newest capture records; not a population-level accuracy estimate.",
                                "Missing metadata is never synthesized; field presence does not prove correctness.",
                                "A run with zero candidate objects cannot establish metadata quality."]},
            "records": rows}

def audit_directory(directory: Path) -> dict[str, Any]:
    records = []
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        try: records.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError): records.append((path, None))
    return build_trend(records)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)
    report = audit_directory(args.directory)
    if args.json: print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Capture records: {report['record_count']}; candidates: {report['candidate_count']}; quality gate: {report['quality_gate']['status']}")
        print("Field coverage: " + ", ".join(f"{k}={v:.1%}" for k,v in report["overall_field_coverage"].items()))
        for item in (report["previous_run_comparison"] or {}).get("regressions", []):
            print(f"REGRESSION {item['field']}: {item['previous_coverage']:.1%} -> {item['latest_coverage']:.1%}")
    if args.fail_on_regression and report["quality_gate"]["status"] == "BLOCKED": return 1
    return 2 if any(row["invalid_record"] for row in report["records"]) else 0
if __name__ == "__main__": raise SystemExit(main())
