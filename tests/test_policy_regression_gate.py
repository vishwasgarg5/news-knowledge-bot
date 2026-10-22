from scripts.audit_policy_regression_gate import audit_regression_gate


def comparison(*, comparable=True, fp=0, missed=0, precision=0.0, base="policy-v1", candidate="policy-v2"):
    return {
        "status": "comparable" if comparable else "blocked",
        "comparable": comparable,
        "baseline_policy_version": base,
        "candidate_policy_version": candidate,
        "metric_deltas_candidate_minus_baseline": {
            "false_positives": fp,
            "missed_relevant_candidates": missed,
            "inclusion_precision": precision,
        },
    }


def config(**overrides):
    values = {
        "config_version": "test-1",
        "tolerances": {
            "maximum_false_positive_increase": 0,
            "maximum_missed_relevant_increase": 0,
            "minimum_precision_delta": 0.0,
        },
    }
    values["tolerances"].update(overrides)
    return values


def test_passes_when_all_regression_tolerances_are_met():
    result = audit_regression_gate(comparison(fp=-1, missed=0, precision=0.05), config())
    assert result["passed"] is True
    assert result["status"] == "pass"


def test_blocks_false_positive_missed_relevant_and_precision_regressions():
    result = audit_regression_gate(comparison(fp=1, missed=1, precision=-0.1), config())
    assert result["passed"] is False
    assert result["status"] == "regression_detected"
    assert set(result["failed_checks"]) == {
        "false_positive_regression", "missed_relevant_regression", "minimum_precision_delta"
    }


def test_blocks_noncomparable_reports_missing_metrics_and_unpinned_versions():
    result = audit_regression_gate(comparison(comparable=False), config())
    assert "comparison_must_be_comparable" in result["configuration_errors"]

    result = audit_regression_gate(comparison(fp=None), config())
    assert "false_positive_regression" in result["failed_checks"]

    result = audit_regression_gate(comparison(base="policy-v1", candidate="policy-v1"), config())
    assert "policy_versions_must_be_distinct" in result["configuration_errors"]


def test_rejects_invalid_tolerance_configuration():
    result = audit_regression_gate(comparison(), config(maximum_false_positive_increase=-1))
    assert result["passed"] is False
    assert "maximum_false_positive_increase_must_be_nonnegative_integer" in result["configuration_errors"]
