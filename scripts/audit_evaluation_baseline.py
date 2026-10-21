#!/usr/bin/env python3
"""Audit an adjudicated evaluation report against a versioned quality baseline.

Exit codes: 0 = baseline met, 1 = blocked or below threshold, 2 = input error.
This is an offline audit; it does not run production workflows or fetch data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def audit_baseline(report: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    errors = []
    checks = []
    expected_policy = baseline.get("policy_version")
    if not isinstance(expected_policy, str) or not expected_policy.strip() or expected_policy.startswith("REPLACE_"):
        errors.append("baseline_policy_version_must_be_pinned_to_an_immutable_identifier")

    thresholds = baseline.get("thresholds")
    if not isinstance(thresholds, dict):
        thresholds = {}
        errors.append("baseline_thresholds_must_be_object")

    min_eligible = thresholds.get("minimum_eligible_candidates")
    if not isinstance(min_eligible, int) or isinstance(min_eligible, bool) or min_eligible < 1:
        errors.append("minimum_eligible_candidates_must_be_positive_integer")
        min_eligible = 1
    min_per_disposition = thresholds.get("minimum_eligible_per_disposition")
    if not isinstance(min_per_disposition, int) or isinstance(min_per_disposition, bool) or min_per_disposition < 0:
        errors.append("minimum_eligible_per_disposition_must_be_nonnegative_integer")
        min_per_disposition = 0
    min_coverage = thresholds.get("minimum_review_coverage")
    if not isinstance(min_coverage, (int, float)) or isinstance(min_coverage, bool) or not 0 <= min_coverage <= 1:
        errors.append("minimum_review_coverage_must_be_between_zero_and_one")
        min_coverage = 0.0

    metadata = report.get("sampling_metadata", [])
    if not isinstance(metadata, list):
        metadata = []
    seen_policies = sorted({str(row.get("policy_version", "")).strip() for row in metadata if isinstance(row, dict) and str(row.get("policy_version", "")).strip()})
    missing_policy_queues = [str(row.get("path", "")) for row in metadata if isinstance(row, dict) and not str(row.get("policy_version", "")).strip()]
    policy_matches = bool(expected_policy and not expected_policy.startswith("REPLACE_") and not missing_policy_queues and seen_policies == [expected_policy])
    checks.append({
        "name": "policy_version",
        "passed": policy_matches,
        "expected": expected_policy,
        "observed": seen_policies,
        "queues_missing_policy_version": missing_policy_queues,
        "reason": "All queues must declare the single pinned policy version." if not policy_matches else "Policy version is pinned and consistent.",
    })

    candidates = report.get("candidate_results", [])
    if not isinstance(candidates, list):
        candidates = []
    eligible = [row for row in candidates if isinstance(row, dict) and row.get("eligible_for_precision_recall") is True]
    eligible_count = len(eligible)
    checks.append({
        "name": "minimum_eligible_candidates",
        "passed": eligible_count >= min_eligible,
        "observed": eligible_count,
        "required": min_eligible,
        "reason": "Small eligible samples produce unstable estimates." if eligible_count < min_eligible else "Eligible sample-size threshold met.",
    })

    disposition_counts = {key: 0 for key in ("included", "excluded", "duplicate", "out_of_scope")}
    for row in eligible:
        disposition = row.get("disposition")
        if disposition in disposition_counts:
            disposition_counts[disposition] += 1
    checks.append({
        "name": "minimum_eligible_per_disposition",
        "passed": all(disposition_counts[key] >= min_per_disposition for key in ("included", "excluded")),
        "observed": {"included": disposition_counts["included"], "excluded": disposition_counts["excluded"]},
        "required_per_included_and_excluded": min_per_disposition,
        "reason": "Insufficient eligible cases in included or excluded stratum." if any(disposition_counts[key] < min_per_disposition for key in ("included", "excluded")) else "Included/excluded stratum thresholds met.",
    })

    total = report.get("candidate_count", 0)
    coverage = eligible_count / total if isinstance(total, int) and total > 0 else None
    checks.append({
        "name": "minimum_review_coverage",
        "passed": coverage is not None and coverage >= min_coverage,
        "observed": coverage,
        "required": min_coverage,
        "denominator": total,
        "reason": "Eligible adjudication coverage is below the configured threshold or cannot be calculated." if coverage is None or coverage < min_coverage else "Coverage threshold met.",
    })

    failures = [check["name"] for check in checks if not check["passed"]]
    return {
        "audit_type": "versioned_evaluation_baseline",
        "baseline_version": baseline.get("baseline_version", ""),
        "policy_version": expected_policy,
        "status": "blocked" if errors else ("pass" if not failures else "below_threshold"),
        "passed": not errors and not failures,
        "configuration_errors": errors,
        "checks": checks,
        "failed_checks": failures,
        "warnings": [
            "Passing a threshold does not prove reviewer labels are correct.",
            "Minimum counts and coverage are operational safeguards, not confidence intervals or guarantees of representativeness.",
            "Review queues must accurately record the policy version used for the evaluated run.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON from evaluate_adjudicated_reviews.py")
    parser.add_argument("--baseline", required=True, type=Path, help="versioned baseline JSON")
    parser.add_argument("--output", type=Path, help="output JSON path; defaults to stdout")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(baseline, dict):
            raise ValueError("report and baseline roots must be JSON objects")
        result = audit_baseline(report, baseline)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result["passed"] else 1
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
