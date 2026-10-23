#!/usr/bin/env python3
"""Offline trend report for evaluation capture metadata completeness."""
from __future__ import annotations
import argparse, json
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "historical_evaluation_records"
FIELDS = ("title", "source", "url", "published_at", "summary")

def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())

def _url_domain(value: Any) -> str:
    """Return a normalized hostname for offline grouping; never fetch the URL."""
    if not _nonempty(value):
        return "unknown"
    try:
        hostname = urlsplit(value.strip()).hostname
    except ValueError:
        return "unknown"
    if not hostname:
        return "unknown"
    hostname = hostname.lower().rstrip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname

def _record_quality(record: Any, path: Path) -> dict[str, Any]:
    timestamp = path.stem
    if isinstance(record, dict):
        raw_ts = record.get("run_timestamp")
        if isinstance(raw_ts, str) and raw_ts.strip():
            try: timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).isoformat()
            except ValueError: pass
    if isinstance(record, dict) and record.get("__audit_parse_error__") is True:
        return {"path": str(path), "run_id": "", "timestamp": timestamp, "candidate_count": 0,
                "field_coverage": {f: 0.0 for f in FIELDS}, "missing_counts": {f: 0 for f in FIELDS},
                "invalid_record": True, "record_error": "json_parse_error"}
    if not isinstance(record, dict):
        return {"path": str(path), "run_id": "", "timestamp": timestamp, "candidate_count": 0,
                "field_coverage": {f: 0.0 for f in FIELDS}, "missing_counts": {f: 0 for f in FIELDS},
                "invalid_record": True, "record_error": "record_not_object"}
    raw = record.get("candidate_articles")
    candidates = raw if isinstance(raw, list) else []
    rows = [row for row in candidates if isinstance(row, dict)]
    missing = {f: sum(not _nonempty(row.get(f)) for row in rows) for f in FIELDS}
    summary_value_diagnostics = {
        "missing_key_count": sum("summary" not in row for row in rows),
        "blank_string_count": sum(isinstance(row.get("summary"), str) and not row.get("summary", "").strip() for row in rows),
        "non_string_count": sum("summary" in row and not isinstance(row.get("summary"), str) for row in rows),
    }
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
    # Categories are absent in some legacy captures, so source-level grouping
    # provides a second diagnostic dimension that remains useful for those runs.
    source_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source = str(row.get("source") or "").strip() or "unknown"
        source_groups.setdefault(source, []).append(row)
    summary_coverage_by_source = {
        source: {
            "candidate_count": len(group),
            "summary_present_count": sum(_nonempty(row.get("summary")) for row in group),
            "summary_missing_count": sum(not _nonempty(row.get("summary")) for row in group),
            "summary_coverage": round(sum(_nonempty(row.get("summary")) for row in group) / len(group), 4),
            # Keep a small, offline-only sample of missing-summary candidates so
            # a blocked quality gate points to concrete records for investigation.
            "missing_summary_examples": [
                {
                    "candidate_id": row.get("candidate_id", ""),
                    "title": str(row.get("title") or ""),
                    "url": str(row.get("url") or ""),
                    "summary_state": (
                        "missing_key" if "summary" not in row else
                        "blank_string" if isinstance(row.get("summary"), str) and not row.get("summary", "").strip() else
                        "non_string" if not isinstance(row.get("summary"), str) else
                        "present"
                    ),
                }
                for row in group if not _nonempty(row.get("summary"))
            ][:5],
        }
        for source, group in sorted(source_groups.items())
    }
    domain_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        domain = _url_domain(row.get("url"))
        domain_groups.setdefault(domain, []).append(row)
    summary_coverage_by_domain = {
        domain: {
            "candidate_count": len(group),
            "summary_present_count": sum(_nonempty(row.get("summary")) for row in group),
            "summary_missing_count": sum(not _nonempty(row.get("summary")) for row in group),
            "summary_coverage": round(sum(_nonempty(row.get("summary")) for row in group) / len(group), 4),
            "missing_summary_examples": [
                {
                    "candidate_id": row.get("candidate_id", ""),
                    "title": str(row.get("title") or ""),
                    "source": str(row.get("source") or ""),
                    "url": str(row.get("url") or ""),
                    "summary_state": (
                        "missing_key" if "summary" not in row else
                        "blank_string" if isinstance(row.get("summary"), str) and not row.get("summary", "").strip() else
                        "non_string" if not isinstance(row.get("summary"), str) else
                        "present"
                    ),
                }
                for row in group if not _nonempty(row.get("summary"))
            ][:5],
        }
        for domain, group in sorted(domain_groups.items())
    }
    return {"path": str(path), "run_id": str(record.get("run_id") or ""), "timestamp": timestamp,
            "candidate_count": n, "field_coverage": {f: round((n-missing[f])/n, 4) if n else 0.0 for f in FIELDS},
            "missing_counts": missing, "summary_value_diagnostics": summary_value_diagnostics,
            "summary_coverage_by_category": summary_coverage_by_category,
            "summary_coverage_by_source": summary_coverage_by_source,
            "summary_coverage_by_domain": summary_coverage_by_domain,
            "invalid_record": not isinstance(raw, list) or len(rows) != len(candidates),
            "record_error": (
                "candidate_articles_not_list" if not isinstance(raw, list) else
                "candidate_articles_contains_non_object" if len(rows) != len(candidates) else None
            )}

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
        def _group_coverage_delta(group_key: str) -> dict[str, Any]:
            previous_groups = prev.get(group_key, {})
            latest_groups = latest.get(group_key, {})
            result = {}
            for group_name in sorted(set(previous_groups) | set(latest_groups)):
                before = previous_groups.get(group_name, {})
                after = latest_groups.get(group_name, {})
                before_coverage = before.get("summary_coverage")
                after_coverage = after.get("summary_coverage")
                result[group_name] = {
                    "previous_candidate_count": before.get("candidate_count", 0),
                    "latest_candidate_count": after.get("candidate_count", 0),
                    "previous_summary_coverage": before_coverage,
                    "latest_summary_coverage": after_coverage,
                    "coverage_delta": round(after_coverage-before_coverage, 4)
                        if before_coverage is not None and after_coverage is not None else None,
                }
            return result
        comparison = {"previous_run_id": prev["run_id"], "latest_run_id": latest["run_id"],
                      "previous_timestamp": prev["timestamp"], "latest_timestamp": latest["timestamp"],
                      "coverage_delta": {f: round(latest["field_coverage"][f]-prev["field_coverage"][f], 4) for f in FIELDS},
                      "summary_coverage_by_category_delta": _group_coverage_delta("summary_coverage_by_category"),
                      "summary_coverage_by_source_delta": _group_coverage_delta("summary_coverage_by_source"),
                      "summary_coverage_by_domain_delta": _group_coverage_delta("summary_coverage_by_domain"),
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
        try:
            records.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            # Preserve the distinction between malformed JSON and valid JSON null.
            records.append((path, {"__audit_parse_error__": True}))
        except OSError:
            records.append((path, None))
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
        latest = report["latest_run"] or {}
        domains = latest.get("summary_coverage_by_domain", {})
        affected = sorted(
            ((domain, details) for domain, details in domains.items()
             if details.get("summary_missing_count", 0)),
            key=lambda item: (-item[1].get("summary_missing_count", 0), item[0]),
        )
        for domain, details in affected[:5]:
            print(
                f"SUMMARY GAPS {domain}: {details['summary_missing_count']}/"
                f"{details['candidate_count']} missing "
                f"({details['summary_coverage']:.1%} coverage)"
            )
            for example in details.get("missing_summary_examples", [])[:3]:
                title = example.get("title") or "(untitled)"
                url = example.get("url") or "(no URL)"
                print(f"  - [{example['summary_state']}] {title} — {url}")
    if args.fail_on_regression and report["quality_gate"]["status"] == "BLOCKED": return 1
    return 2 if any(row["invalid_record"] for row in report["records"]) else 0
if __name__ == "__main__": raise SystemExit(main())
