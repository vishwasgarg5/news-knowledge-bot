from scripts.audit_evaluation_baseline import audit_baseline


def report():
    candidates = []
    for index in range(6):
        disposition = "included" if index < 3 else "excluded"
        candidates.append({
            "candidate_id": f"c{index}",
            "disposition": disposition,
            "eligible_for_precision_recall": True,
            "exclusion_reasons": [],
        })
    return {
        "candidate_count": 10,
        "candidate_results": candidates,
        "sampling_metadata": [
            {"path": "queue-a.json", "policy_version": "policy-v7"},
        ],
    }


def baseline(**overrides):
    value = {
        "baseline_version": "1.0",
        "policy_version": "policy-v7",
        "thresholds": {
            "minimum_eligible_candidates": 6,
            "minimum_eligible_per_disposition": 3,
            "minimum_review_coverage": 0.6,
        },
    }
    value.update(overrides)
    return value


def test_passes_when_policy_sample_size_strata_and_coverage_meet_thresholds():
    result = audit_baseline(report(), baseline())

    assert result["passed"] is True
    assert result["status"] == "pass"
    assert all(check["passed"] for check in result["checks"])


def test_blocks_unpinned_policy_version():
    result = audit_baseline(report(), baseline(policy_version="REPLACE_WITH_POLICY"))

    assert result["status"] == "blocked"
    assert "baseline_policy_version_must_be_pinned_to_an_immutable_identifier" in result["configuration_errors"]
    assert result["passed"] is False


def test_flags_policy_mismatch_and_small_or_undercovered_samples():
    value = report()
    value["sampling_metadata"][0]["policy_version"] = "policy-v6"
    value["candidate_results"] = value["candidate_results"][:2]
    result = audit_baseline(value, baseline())

    assert result["passed"] is False
    assert "policy_version" in result["failed_checks"]
    assert "minimum_eligible_candidates" in result["failed_checks"]
    assert "minimum_eligible_per_disposition" in result["failed_checks"]
    assert "minimum_review_coverage" in result["failed_checks"]


def test_missing_policy_version_is_not_assumed_to_match():
    value = report()
    value["sampling_metadata"][0].pop("policy_version")
    result = audit_baseline(value, baseline())

    policy_check = next(check for check in result["checks"] if check["name"] == "policy_version")
    assert policy_check["passed"] is False
    assert policy_check["queues_missing_policy_version"] == ["queue-a.json"]


def test_invalid_thresholds_block_baseline():
    value = baseline()
    value["thresholds"]["minimum_review_coverage"] = 1.5
    result = audit_baseline(report(), value)

    assert result["status"] == "blocked"
    assert "minimum_review_coverage_must_be_between_zero_and_one" in result["configuration_errors"]
