from scripts.build_policy_release_decision import build_release_decision


def audit(policy, passed=True, coverage_passed=True, observed=0.8, required=0.5):
    return {
        "passed": passed,
        "status": "pass" if passed else "below_threshold",
        "policy_version": policy,
        "configuration_errors": [] if passed else ["sample_error"],
        "failed_checks": [] if passed else ["minimum_eligible_candidates"],
        "checks": [{
            "name": "minimum_review_coverage",
            "passed": coverage_passed,
            "observed": observed,
            "required": required,
            "denominator": 100,
        }],
    }


def comparison(base="policy-v1", candidate="policy-v2", comparable=True):
    return {
        "status": "comparable" if comparable else "blocked",
        "comparable": comparable,
        "baseline_policy_version": base,
        "candidate_policy_version": candidate,
        "errors": [] if comparable else ["reports_do_not_describe_the_same_comparable_adjudicated_set"],
        "checks": [{"name": "same_candidate_set", "passed": comparable}],
    }


def regression(base="policy-v1", candidate="policy-v2", passed=True):
    return {
        "status": "pass" if passed else "regression_detected",
        "passed": passed,
        "baseline_policy_version": base,
        "candidate_policy_version": candidate,
        "configuration_errors": [] if passed else [],
        "failed_checks": [] if passed else ["false_positive_regression"],
    }


def test_returns_go_only_when_all_gates_and_coverage_pass():
    result = build_release_decision(
        comparison(), audit("policy-v1"), audit("policy-v2"), regression()
    )
    assert result["decision"] == "GO"
    assert result["passed"] is True
    assert result["blockers"] == []
    assert result["evidence_coverage"]["candidate"]["observed"] == 0.8


def test_no_go_lists_failed_quality_coverage_and_regression_reasons():
    result = build_release_decision(
        comparison(),
        audit("policy-v1"),
        audit("policy-v2", passed=False, coverage_passed=False, observed=0.1),
        regression(passed=False),
    )
    assert result["decision"] == "NO-GO"
    names = {item["check"] for item in result["blockers"]}
    assert "candidate_quality_gate" in names
    assert "candidate_evidence_coverage" in names
    assert "regression_tolerance_gate" in names
    assert result["upstream_failure_details"]["candidate_audit"]["failed_checks"] == ["minimum_eligible_candidates"]


def test_no_go_when_comparison_is_blocked_or_policy_ids_disagree():
    result = build_release_decision(
        comparison(comparable=False), audit("policy-v1"), audit("policy-v2"), regression()
    )
    assert result["decision"] == "NO-GO"
    assert "policy_comparison" in {item["check"] for item in result["blockers"]}

    mismatched_gate = regression(base="wrong-baseline")
    result = build_release_decision(
        comparison(), audit("policy-v1"), audit("policy-v2"), mismatched_gate
    )
    assert result["decision"] == "NO-GO"
    assert "policy_identity_consistency" in {item["check"] for item in result["blockers"]}


def test_missing_coverage_check_fails_closed():
    base = audit("policy-v1")
    base["checks"] = []
    result = build_release_decision(comparison(), base, audit("policy-v2"), regression())
    assert result["decision"] == "NO-GO"
    assert "baseline_evidence_coverage" in {item["check"] for item in result["blockers"]}
