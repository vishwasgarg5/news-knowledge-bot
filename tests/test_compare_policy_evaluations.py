from scripts.compare_policy_evaluations import compare_policy_reports


def candidate(cid, disposition, label, fingerprint=None):
    return {
        "candidate_id": cid,
        "evidence_fingerprint": fingerprint or f"sha-{cid}",
        "disposition": disposition,
        "adjudicated_label": label,
        "eligible_for_precision_recall": disposition in {"included", "excluded"} and label != "uncertain",
        "exclusion_reasons": [],
    }


def report(policy, candidates, precision, recall):
    tp = 2 if policy == "v2" else 1
    fp = 1 if policy == "v2" else 2
    fn = 1
    return {
        "candidate_count": len(candidates),
        "metric_eligible_candidates": sum(x["eligible_for_precision_recall"] for x in candidates),
        "candidate_results": candidates,
        "metrics": {
            "true_positives": tp,
            "false_positives": fp,
            "missed_relevant_candidates": fn,
            "inclusion_precision": precision,
            "inclusion_recall": recall,
            "precision_denominator": tp + fp,
            "recall_denominator": tp + fn,
        },
        "sampling_metadata": [{"policy_version": policy, "sampling_method": "stratified", "sampling_seed": "seed-42"}],
    }


def gate(policy, passed=True):
    return {"passed": passed, "policy_version": policy}


def test_compares_policy_versions_on_same_adjudicated_evidence_set():
    base_rows = [
        candidate("a", "included", "relevant"),
        candidate("b", "included", "not_relevant"),
        candidate("c", "excluded", "relevant"),
    ]
    next_rows = [
        candidate("a", "included", "relevant"),
        candidate("b", "excluded", "not_relevant"),
        candidate("c", "included", "relevant"),
    ]

    result = compare_policy_reports(
        report("v1", base_rows, 1 / 3, 1 / 2),
        report("v2", next_rows, 2 / 3, 2 / 3),
        gate("v1"), gate("v2"),
    )

    assert result["comparable"] is True
    assert result["metric_deltas_candidate_minus_baseline"]["inclusion_precision"] == 1 / 3
    assert result["baseline_by_disposition"]["included"]["eligible"] == 2
    assert result["candidate_by_disposition"]["included"]["eligible"] == 2


def test_blocks_different_candidate_sets_or_adjudicated_labels():
    base_rows = [candidate("a", "included", "relevant"), candidate("b", "excluded", "not_relevant")]
    different_ids = [candidate("a", "included", "relevant"), candidate("c", "excluded", "not_relevant")]
    result = compare_policy_reports(
        report("v1", base_rows, 1.0, 1.0),
        report("v2", different_ids, 1.0, 1.0), gate("v1"), gate("v2"),
    )
    assert result["comparable"] is False
    assert "same_candidate_set" in [c["name"] for c in result["checks"] if not c["passed"]]

    changed_labels = [candidate("a", "included", "not_relevant"), candidate("b", "excluded", "not_relevant")]
    result = compare_policy_reports(
        report("v1", base_rows, 1.0, 1.0),
        report("v2", changed_labels, 1.0, 1.0), gate("v1"), gate("v2"),
    )
    assert result["comparable"] is False
    assert "reports_do_not_describe_the_same_comparable_adjudicated_set" in result["errors"]


def test_blocks_different_evidence_sampling_design_or_failed_policy_gate():
    base_rows = [candidate("a", "included", "relevant"), candidate("b", "excluded", "not_relevant")]
    changed_evidence = [candidate("a", "included", "relevant", "different"), candidate("b", "excluded", "not_relevant")]
    result = compare_policy_reports(
        report("v1", base_rows, 1.0, 1.0),
        report("v2", changed_evidence, 1.0, 1.0), gate("v1"), gate("v2"),
    )
    assert result["comparable"] is False
    assert "same_evidence_snapshot" in [c["name"] for c in result["checks"] if not c["passed"]]

    changed_seed_report = report("v2", base_rows, 1.0, 1.0)
    changed_seed_report["sampling_metadata"][0]["sampling_seed"] = "different-seed"
    result = compare_policy_reports(report("v1", base_rows, 1.0, 1.0), changed_seed_report, gate("v1"), gate("v2"))
    assert "sampling_method_or_seed_mismatch" in result["errors"]

    result = compare_policy_reports(report("v1", base_rows, 1.0, 1.0), report("v2", base_rows, 1.0, 1.0), gate("v1", False), gate("v2"))
    assert "baseline_policy_failed_its_quality_gate" in result["errors"]
