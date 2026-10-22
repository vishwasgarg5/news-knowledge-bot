#!/usr/bin/env python3
"""Gate a policy comparison against explicit regression tolerances (offline only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def audit_regression_gate(comparison: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    errors = []
    checks = []
    if comparison.get("comparable") is not True or comparison.get("status") != "comparable":
        errors.append("comparison_must_be_comparable")
    baseline_policy = comparison.get("baseline_policy_version")
    candidate_policy = comparison.get("candidate_policy_version")
    if not isinstance(baseline_policy, str) or not baseline_policy.strip() or baseline_policy.startswith("REPLACE_"):
        errors.append("baseline_policy_version_must_be_pinned")
    if not isinstance(candidate_policy, str) or not candidate_policy.strip() or candidate_policy.startswith("REPLACE_"):
        errors.append("candidate_policy_version_must_be_pinned")
    if baseline_policy == candidate_policy:
        errors.append("policy_versions_must_be_distinct")

    tolerances = config.get("tolerances")
    if not isinstance(tolerances, dict):
        tolerances = {}
        errors.append("tolerances_must_be_object")

    def nonnegative_int(name: str, default: int = 0) -> int:
        value = tolerances.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{name}_must_be_nonnegative_integer")
            return default
        return value

    max_fp_increase = nonnegative_int("maximum_false_positive_increase")
    max_missed_increase = nonnegative_int("maximum_missed_relevant_increase")
    min_precision_delta = tolerances.get("minimum_precision_delta", 0.0)
    if not isinstance(min_precision_delta, (int, float)) or isinstance(min_precision_delta, bool) or not -1 <= min_precision_delta <= 1:
        errors.append("minimum_precision_delta_must_be_between_minus_one_and_one")
        min_precision_delta = 0.0

    deltas = comparison.get("metric_deltas_candidate_minus_baseline")
    if not isinstance(deltas, dict):
        deltas = {}
        errors.append("metric_deltas_missing")
    fp_delta = deltas.get("false_positives")
    missed_delta = deltas.get("missed_relevant_candidates")
    precision_delta = deltas.get("inclusion_precision")

    def numeric(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    checks.append({
        "name": "false_positive_regression",
        "passed": numeric(fp_delta) and fp_delta <= max_fp_increase,
        "observed_increase": fp_delta,
        "maximum_allowed_increase": max_fp_increase,
    })
    checks.append({
        "name": "missed_relevant_regression",
        "passed": numeric(missed_delta) and missed_delta <= max_missed_increase,
        "observed_increase": missed_delta,
        "maximum_allowed_increase": max_missed_increase,
    })
    checks.append({
        "name": "minimum_precision_delta",
        "passed": numeric(precision_delta) and precision_delta >= min_precision_delta,
        "observed_delta": precision_delta,
        "minimum_required_delta": min_precision_delta,
    })

    failures = [item["name"] for item in checks if not item["passed"]]
    return {
        "gate_type": "policy_regression_tolerance",
        "config_version": config.get("config_version", ""),
        "baseline_policy_version": baseline_policy,
        "candidate_policy_version": candidate_policy,
        "status": "blocked" if errors else ("pass" if not failures else "regression_detected"),
        "passed": not errors and not failures,
        "configuration_errors": errors,
        "checks": checks,
        "failed_checks": failures,
        "warnings": [
            "This gate evaluates configured descriptive tolerances, not statistical significance.",
            "A passing gate does not prove real-world quality; use representative, independently adjudicated data.",
            "Do not loosen tolerances solely to make a candidate policy pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path, help="output from compare_policy_evaluations.py")
    parser.add_argument("--config", required=True, type=Path, help="reviewed regression tolerance JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(comparison, dict) or not isinstance(config, dict):
            raise ValueError("input JSON roots must be objects")
        result = audit_regression_gate(comparison, config)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
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
