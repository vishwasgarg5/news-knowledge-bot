from scripts.summarize_paired_policy_evaluation import summarize_paired_evaluation


def report(policy, dispositions):
    rows = []
    for i, (label, disposition) in enumerate(dispositions):
        rows.append({
            "candidate_id": f"c{i}",
            "adjudicated_label": label,
            "disposition": disposition,
            "evidence_fingerprint": f"evidence-{i}",
            "exclusion_reasons": [],
            "eligible_for_precision_recall": True,
        })
    return {
        "candidate_count": len(rows),
        "metric_eligible_candidates": len(rows),
        "candidate_results": rows,
        "sampling_metadata": [{"sampling_method": "stratified", "sampling_seed": "seed-1",
                               "policy_version": policy}],
        "metrics": {},
    }


def gate(policy):
    return {"policy_version": policy, "passed": True, "status": "pass"}


def test_paired_summary_is_reproducible_and_labels_uncertainty():
    baseline = report("v1", [
        ("relevant", "included"), ("not_relevant", "included"),
        ("relevant", "excluded"), ("not_relevant", "excluded"),
        ("relevant", "included"), ("not_relevant", "excluded"),
    ])
    candidate = report("v2", [
        ("relevant", "included"), ("not_relevant", "excluded"),
        ("relevant", "included"), ("not_relevant", "excluded"),
        ("relevant", "included"), ("not_relevant", "excluded"),
    ])
    first = summarize_paired_evaluation(baseline, candidate, gate("v1"), gate("v2"),
                                        bootstrap_samples=500, seed=42)
    second = summarize_paired_evaluation(baseline, candidate, gate("v1"), gate("v2"),
                                         bootstrap_samples=500, seed=42)
    assert first == second
    assert first["status"] == "complete"
    assert first["cohort"]["eligible_paired_candidates"] == 6
    assert first["paired_bootstrap"]["intervals"]["inclusion_precision"]["confidence_level"] == 0.95
    assert first["improvement_claim"] in {"supported_on_this_cohort_only", "not_supported"}


def test_summary_blocks_when_candidate_cohorts_differ():
    baseline = report("v1", [("relevant", "included"), ("not_relevant", "excluded")])
    candidate = report("v2", [("relevant", "included")])
    result = summarize_paired_evaluation(baseline, candidate, gate("v1"), gate("v2"),
                                         bootstrap_samples=200)
    assert result["status"] == "blocked"
    assert result["comparable"] is False
    assert result["improvement_claim"] == "not_supported"


def test_summary_blocks_when_policy_quality_gate_fails():
    baseline = report("v1", [("relevant", "included"), ("not_relevant", "excluded")])
    candidate = report("v2", [("relevant", "included"), ("not_relevant", "excluded")])
    result = summarize_paired_evaluation(baseline, candidate, gate("v1"),
                                         {"policy_version": "v2", "passed": False},
                                         bootstrap_samples=200)
    assert result["status"] == "blocked"
    assert "candidate_policy_failed_its_quality_gate" in result["comparison_errors"]


def test_summary_rejects_too_few_bootstrap_samples():
    baseline = report("v1", [("relevant", "included"), ("not_relevant", "excluded")])
    candidate = report("v2", [("relevant", "included"), ("not_relevant", "excluded")])
    try:
        summarize_paired_evaluation(baseline, candidate, gate("v1"), gate("v2"),
                                    bootstrap_samples=20)
    except ValueError as exc:
        assert "at least 100" in str(exc)
    else:
        raise AssertionError("small bootstrap count must be rejected")
