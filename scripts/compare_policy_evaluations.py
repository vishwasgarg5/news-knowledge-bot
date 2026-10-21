#!/usr/bin/env python3
"""Compare two policy evaluation reports on the same independently labelled set.

This offline comparison blocks if candidate IDs or adjudicated labels differ,
if evidence/adjudication quality differs, or if either policy fails its own
baseline audit. It describes observed changes; it does not infer causality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


NON_COMPARABLE_REASONS = (
    "no_valid_adjudication",
    "adjudicated_uncertain",
    "invalid_disposition",
)


def _index_candidates(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("candidate_results", [])
    if not isinstance(rows, list):
        return {}
    return {
        str(row["candidate_id"]): row
        for row in rows
        if isinstance(row, dict) and str(row.get("candidate_id", "")).strip()
    }


def compare_policy_reports(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    baseline_gate: dict[str, Any],
    candidate_gate: dict[str, Any],
) -> dict[str, Any]:
    errors = []
    checks = []
    if baseline_gate.get("passed") is not True:
        errors.append("baseline_policy_failed_its_quality_gate")
    if candidate_gate.get("passed") is not True:
        errors.append("candidate_policy_failed_its_quality_gate")

    base = _index_candidates(baseline_report)
    cand = _index_candidates(candidate_report)
    same_ids = set(base) == set(cand) and bool(base)
    checks.append({
        "name": "same_candidate_set",
        "passed": same_ids,
        "baseline_candidate_count": len(base),
        "candidate_candidate_count": len(cand),
        "baseline_only_ids": sorted(set(base) - set(cand)),
        "candidate_only_ids": sorted(set(cand) - set(base)),
    })
    same_labels = same_ids and all(base[cid].get("adjudicated_label") == cand[cid].get("adjudicated_label") for cid in base)
    checks.append({"name": "same_adjudicated_labels", "passed": same_labels})
    same_evidence = same_ids and all(
        base[cid].get("evidence_fingerprint")
        and base[cid].get("evidence_fingerprint") == cand[cid].get("evidence_fingerprint")
        for cid in base
    )
    checks.append({"name": "same_evidence_snapshot", "passed": same_evidence})

    quality_issues = []
    for policy_name, rows in (("baseline", base), ("candidate", cand)):
        for cid, row in rows.items():
            reasons = row.get("exclusion_reasons", [])
            if not isinstance(reasons, list):
                reasons = ["malformed_exclusion_reasons"]
            forbidden = [
                reason for reason in reasons
                if any(str(reason).startswith(prefix) for prefix in NON_COMPARABLE_REASONS)
                or str(reason).startswith("missing_evidence:")
            ]
            if forbidden:
                quality_issues.append({"policy": policy_name, "candidate_id": cid, "reasons": forbidden})
    checks.append({
        "name": "same_set_has_valid_adjudication_and_complete_evidence",
        "passed": not quality_issues,
        "issues": quality_issues,
        "reason": "Comparison requires valid, non-uncertain adjudications and complete evidence for every candidate.",
    })

    base_meta = baseline_report.get("sampling_metadata", [])
    cand_meta = candidate_report.get("sampling_metadata", [])
    base_methods = sorted({(str(x.get("sampling_method", "")), str(x.get("sampling_seed", ""))) for x in base_meta if isinstance(x, dict)})
    cand_methods = sorted({(str(x.get("sampling_method", "")), str(x.get("sampling_seed", ""))) for x in cand_meta if isinstance(x, dict)})
    same_sampling = bool(base_methods) and base_methods == cand_methods
    checks.append({
        "name": "same_sampling_design",
        "passed": same_sampling,
        "baseline_sampling": [{"method": method, "seed": seed} for method, seed in base_methods],
        "candidate_sampling": [{"method": method, "seed": seed} for method, seed in cand_methods],
    })

    if not same_ids or not same_labels or not same_evidence or quality_issues:
        errors.append("reports_do_not_describe_the_same_comparable_adjudicated_set")
    if not same_sampling:
        errors.append("sampling_method_or_seed_mismatch")

    def metric_summary(report: dict[str, Any]) -> dict[str, Any]:
        metrics = report.get("metrics", {})
        return {
            "candidate_count": report.get("candidate_count"),
            "metric_eligible_candidates": report.get("metric_eligible_candidates"),
            "true_positives": metrics.get("true_positives"),
            "false_positives": metrics.get("false_positives"),
            "missed_relevant_candidates": metrics.get("missed_relevant_candidates"),
            "inclusion_precision": metrics.get("inclusion_precision"),
            "inclusion_recall": metrics.get("inclusion_recall"),
            "precision_denominator": metrics.get("precision_denominator"),
            "recall_denominator": metrics.get("recall_denominator"),
        }

    def per_disposition(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
        result = {key: {"eligible": 0, "adjudicated_relevant": 0, "adjudicated_not_relevant": 0}
                  for key in ("included", "excluded", "duplicate", "out_of_scope", "other")}
        for row in rows.values():
            disposition = row.get("disposition")
            key = disposition if disposition in result else "other"
            label = row.get("adjudicated_label")
            if row.get("eligible_for_precision_recall") is True:
                result[key]["eligible"] += 1
            if label == "relevant":
                result[key]["adjudicated_relevant"] += 1
            elif label == "not_relevant":
                result[key]["adjudicated_not_relevant"] += 1
        return result

    base_metrics = metric_summary(baseline_report)
    cand_metrics = metric_summary(candidate_report)
    deltas = {}
    for key in ("true_positives", "false_positives", "missed_relevant_candidates", "inclusion_precision", "inclusion_recall"):
        left, right = base_metrics.get(key), cand_metrics.get(key)
        deltas[key] = right - left if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool) else None

    passed = not errors and all(check["passed"] for check in checks)
    return {
        "comparison_type": "same_set_policy_comparison",
        "status": "comparable" if passed else "blocked",
        "comparable": passed,
        "errors": errors,
        "checks": checks,
        "baseline_policy_version": baseline_gate.get("policy_version", baseline_report.get("sampling_metadata", [{}])[0].get("policy_version") if baseline_report.get("sampling_metadata") else None),
        "candidate_policy_version": candidate_gate.get("policy_version", candidate_report.get("sampling_metadata", [{}])[0].get("policy_version") if candidate_report.get("sampling_metadata") else None),
        "baseline_metrics": base_metrics,
        "candidate_metrics": cand_metrics,
        "metric_deltas_candidate_minus_baseline": deltas,
        "baseline_by_disposition": per_disposition(base),
        "candidate_by_disposition": per_disposition(cand),
        "warnings": [
            "A comparable result is an observed difference on this reviewed set, not proof that the policy caused the difference.",
            "Both policy-specific baseline audits must pass; threshold checks do not establish statistical significance.",
            "The same sampling method and seed are necessary but do not alone prove a representative sample.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_report", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("--baseline-gate", required=True, type=Path, help="baseline policy audit JSON")
    parser.add_argument("--candidate-gate", required=True, type=Path, help="candidate policy audit JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        values = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (args.baseline_report, args.candidate_report, args.baseline_gate, args.candidate_gate)
        ]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError("all input JSON roots must be objects")
        result = compare_policy_reports(*values)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result["comparable"] else 1
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
