#!/usr/bin/env python3
"""Build an auditable GO/NO-GO release decision from offline evaluation gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _named_checks(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = audit.get("checks", [])
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("name")): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }


def build_release_decision(
    comparison: dict[str, Any],
    baseline_audit: dict[str, Any],
    candidate_audit: dict[str, Any],
    regression_gate: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            blockers.append({"check": name, "reason": detail})

    add_check(
        "policy_comparison",
        comparison.get("comparable") is True and comparison.get("status") == "comparable",
        "Policy comparison must be marked comparable; inspect its errors and checks.",
    )
    add_check(
        "baseline_quality_gate",
        baseline_audit.get("passed") is True and baseline_audit.get("status") == "pass",
        "Baseline policy quality audit must pass all checks.",
    )
    add_check(
        "candidate_quality_gate",
        candidate_audit.get("passed") is True and candidate_audit.get("status") == "pass",
        "Candidate policy quality audit must pass all checks.",
    )
    add_check(
        "regression_tolerance_gate",
        regression_gate.get("passed") is True and regression_gate.get("status") == "pass",
        "Candidate policy must pass the configured regression tolerances.",
    )

    baseline_policy = baseline_audit.get("policy_version")
    candidate_policy = candidate_audit.get("policy_version")
    add_check(
        "policy_identity_consistency",
        isinstance(baseline_policy, str) and bool(baseline_policy.strip())
        and isinstance(candidate_policy, str) and bool(candidate_policy.strip())
        and baseline_policy != candidate_policy
        and comparison.get("baseline_policy_version") == baseline_policy
        and comparison.get("candidate_policy_version") == candidate_policy
        and regression_gate.get("baseline_policy_version") == baseline_policy
        and regression_gate.get("candidate_policy_version") == candidate_policy,
        "All artifacts must agree on two distinct, pinned policy versions.",
    )

    base_checks = _named_checks(baseline_audit)
    candidate_checks = _named_checks(candidate_audit)
    for name, audit_checks in (
        ("baseline_evidence_coverage", base_checks),
        ("candidate_evidence_coverage", candidate_checks),
    ):
        coverage = audit_checks.get("minimum_review_coverage")
        add_check(
            name,
            isinstance(coverage, dict) and coverage.get("passed") is True
            and isinstance(coverage.get("observed"), (int, float))
            and not isinstance(coverage.get("observed"), bool),
            "A calculable review-coverage check must pass its configured threshold.",
        )

    # Preserve upstream failure details as an audit trail, even though each is
    # summarized above, so the release report explains precisely what was blocked.
    upstream = {
        "comparison": {
            "errors": comparison.get("errors", []),
            "failed_checks": [c.get("name") for c in comparison.get("checks", [])
                              if isinstance(c, dict) and c.get("passed") is not True],
        },
        "baseline_audit": {
            "configuration_errors": baseline_audit.get("configuration_errors", []),
            "failed_checks": baseline_audit.get("failed_checks", []),
        },
        "candidate_audit": {
            "configuration_errors": candidate_audit.get("configuration_errors", []),
            "failed_checks": candidate_audit.get("failed_checks", []),
        },
        "regression_gate": {
            "configuration_errors": regression_gate.get("configuration_errors", []),
            "failed_checks": regression_gate.get("failed_checks", []),
        },
    }
    return {
        "decision_type": "offline_policy_release_decision",
        "decision_schema_version": "1.0",
        "decision": "GO" if not blockers else "NO-GO",
        "passed": not blockers,
        "baseline_policy_version": baseline_policy,
        "candidate_policy_version": candidate_policy,
        "checks": checks,
        "blockers": blockers,
        "upstream_failure_details": upstream,
        "evidence_coverage": {
            "baseline": {
                "observed": base_checks.get("minimum_review_coverage", {}).get("observed"),
                "required": base_checks.get("minimum_review_coverage", {}).get("required"),
                "denominator": base_checks.get("minimum_review_coverage", {}).get("denominator"),
            },
            "candidate": {
                "observed": candidate_checks.get("minimum_review_coverage", {}).get("observed"),
                "required": candidate_checks.get("minimum_review_coverage", {}).get("required"),
                "denominator": candidate_checks.get("minimum_review_coverage", {}).get("denominator"),
            },
        },
        "warnings": [
            "GO is an offline evaluation decision only; it does not deploy or activate a policy.",
            "Configured thresholds are descriptive safeguards, not confidence intervals or proof of causality.",
            "A passing decision depends on the quality and representativeness of independent adjudications.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    parser.add_argument("--baseline-audit", required=True, type=Path)
    parser.add_argument("--candidate-audit", required=True, type=Path)
    parser.add_argument("--regression-gate", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        values = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (args.comparison, args.baseline_audit, args.candidate_audit, args.regression_gate)
        ]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError("all input JSON roots must be objects")
        result = build_release_decision(*values)
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
