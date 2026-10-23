from scripts.evaluate_adjudicated_reviews import evaluate_adjudicated_reviews


def review(cid, disposition="included", **overrides):
    row = {
        "candidate_id": cid,
        "disposition": disposition,
        "source": "Publisher",
        "url": f"https://example.com/{cid}",
        "published_at": "2026-10-21T09:00:00+05:30",
        "summary": "Evidence summary",
    }
    row.update(overrides)
    return row


def adjudication(cid, label):
    return {
        "candidate_id": cid,
        "final_label": label,
        "adjudicator_id": "adjudicator-1",
        "adjudicated_at": "2026-10-21T12:00:00+05:30",
        "rationale": "Reviewed the evidence and scope.",
    }


def test_metrics_use_only_explicit_adjudications_and_compute_precision_recall():
    queue = ("reviews.json", {"sampling_seed": "seed-1", "reviews": [
        review("tp", "included"), review("fp", "included"),
        review("fn", "excluded"), review("tn", "excluded"),
    ]})
    labels = {"adjudications": [
        adjudication("tp", "relevant"), adjudication("fp", "not_relevant"),
        adjudication("fn", "relevant"), adjudication("tn", "not_relevant"),
    ]}

    report = evaluate_adjudicated_reviews([queue], labels)

    assert report["metric_eligible_candidates"] == 4
    assert report["metrics"]["true_positives"] == 1
    assert report["metrics"]["false_positives"] == 1
    assert report["metrics"]["missed_relevant_candidates"] == 1
    assert report["metrics"]["inclusion_precision"] == 0.5
    assert report["metrics"]["inclusion_recall"] == 0.5
    assert report["sampling_metadata"][0]["sampling_seed"] == "seed-1"


def test_unadjudicated_uncertain_and_evidence_incomplete_cases_are_excluded_with_reasons():
    queue = ("reviews.json", {"reviews": [
        review("pending"),
        review("uncertain"),
        review("gap", url=""),
    ]})
    labels = {"adjudications": [
        adjudication("uncertain", "uncertain"),
        adjudication("gap", "relevant"),
    ]}

    report = evaluate_adjudicated_reviews([queue], labels)
    rows = {row["candidate_id"]: row for row in report["candidate_results"]}

    assert report["metric_eligible_candidates"] == 0
    assert "no_valid_adjudication" in rows["pending"]["exclusion_reasons"]
    assert "adjudicated_uncertain" in rows["uncertain"]["exclusion_reasons"]
    assert any(reason.startswith("missing_evidence:url") for reason in rows["gap"]["exclusion_reasons"])
    assert report["metrics"]["inclusion_precision"] is None


def test_duplicate_and_out_of_scope_candidates_do_not_enter_precision_recall():
    queue = ("reviews.json", {"reviews": [
        review("dup", "duplicate"), review("oos", "out_of_scope"),
    ]})
    labels = {"adjudications": [adjudication("dup", "relevant"), adjudication("oos", "relevant")]}

    report = evaluate_adjudicated_reviews([queue], labels)

    assert report["metric_eligible_candidates"] == 0
    assert all(not row["eligible_for_precision_recall"] for row in report["candidate_results"])
    assert report["exclusion_reason_counts"]["disposition_outside_precision_recall_scope"] == 2


def test_invalid_and_duplicate_adjudications_are_not_silently_accepted():
    queue = ("reviews.json", {"reviews": [review("c1")]})
    labels = {"adjudications": [
        adjudication("c1", "relevant"),
        adjudication("c1", "not_relevant"),
    ]}
    report = evaluate_adjudicated_reviews([queue], labels)

    assert report["valid_adjudications_for_known_candidates"] == 1
    assert report["invalid_adjudications"][0]["reasons"] == ["duplicate_adjudication"]


def test_conflicting_candidate_evidence_or_disposition_is_excluded_from_metrics():
    first = review("c1", "included", url="https://example.com/one")
    second = review("c1", "excluded", url="https://example.com/two")
    queue_a = ("reviewer-a.json", {"reviews": [first]})
    queue_b = ("reviewer-b.json", {"reviews": [second]})

    report = evaluate_adjudicated_reviews(
        [queue_a, queue_b], {"adjudications": [adjudication("c1", "relevant")]}
    )

    assert report["metric_eligible_candidates"] == 0
    assert report["conflicting_candidate_record_count"] == 1
    conflict = report["conflicting_candidate_records"][0]
    assert conflict["candidate_id"] == "c1"
    assert set(conflict["fields"]) == {"url", "disposition"}
    row = report["candidate_results"][0]
    assert "conflicting_candidate_records" in row["exclusion_reasons"]
    assert not row["eligible_for_precision_recall"]


def test_sampling_diagnostics_report_selection_rate_without_applying_weights():
    queue = ("sampled.json", {
        "run_id": "run-1",
        "sampling_method": "deterministic_stratified_by_disposition",
        "sampling_seed": "fixed-seed",
        "strata": {
            "included": {"eligible_unreviewed": 100, "selected": 10, "selection_rate": 0.1},
            "excluded": {"eligible_unreviewed": 20, "selected": 20, "selection_rate": 1.0},
        },
        "reviews": [review("c1", "included")],
    })
    report = evaluate_adjudicated_reviews(
        [queue], {"adjudications": [adjudication("c1", "relevant")]}
    )

    rows = {row["disposition"]: row for row in report["sampling_diagnostics"]}
    assert rows["included"]["inverse_selection_weight_diagnostic"] == 10.0
    assert rows["excluded"]["inverse_selection_weight_diagnostic"] == 1.0
    assert rows["included"]["eligible_unreviewed"] == 100
    assert rows["included"]["selected"] == 10
    assert rows["included"]["weighting_applied_to_metrics"] is False
    assert report["metrics"]["inclusion_precision"] == 1.0


def test_sampling_diagnostics_flag_inconsistent_rates_and_withhold_weights():
    queue = ("bad-sampling.json", {
        "strata": {
            "included": {"eligible_unreviewed": 10, "selected": 5, "selection_rate": 0.9},
            "excluded": {"eligible_unreviewed": 0, "selected": 0, "selection_rate": 0.0},
            "duplicate": {"eligible_unreviewed": 2, "selected": 3, "selection_rate": 1.5},
        },
        "reviews": [review("c1", "included"), review("c2", "excluded")],
    })
    report = evaluate_adjudicated_reviews([queue], {"adjudications": []})
    rows = {row["disposition"]: row for row in report["sampling_diagnostics"]}

    assert rows["included"]["metadata_valid"] is False
    assert rows["included"]["inverse_selection_weight_diagnostic"] is None
    assert rows["excluded"]["metadata_valid"] is False
    assert rows["duplicate"]["selection_counts_valid"] is False
    assert rows["duplicate"]["inverse_selection_weight_diagnostic"] is None


def test_sample_coverage_is_explicitly_limited_to_supplied_queues():
    queue = ("reviews.json", {"reviews": [review("a", "included"), review("b", "excluded"), review("c", "duplicate")]})
    report = evaluate_adjudicated_reviews([queue], {"adjudications": [
        adjudication("a", "relevant"), adjudication("b", "not_relevant"),
        adjudication("c", "relevant"),
    ]})

    coverage = report["sample_coverage"]
    assert coverage["unique_candidates_in_supplied_queues"] == 3
    assert coverage["metric_eligible_candidates"] == 2
    assert coverage["not_metric_eligible_candidates"] == 1
    assert coverage["metric_eligibility_rate_within_supplied_candidates"] == 2 / 3
    assert coverage["disposition_counts"] == {"duplicate": 1, "excluded": 1, "included": 1, "out_of_scope": 0}
    assert "not full-population coverage" in coverage["interpretation"]


def test_same_candidate_from_different_runs_or_policies_is_excluded():
    queue_a = ("run-a.json", {
        "run_id": "run-a", "policy_version": "policy-v1",
        "reviews": [review("reused-id", "included")],
    })
    queue_b = ("run-b.json", {
        "run_id": "run-b", "policy_version": "policy-v2",
        "reviews": [review("reused-id", "included")],
    })

    report = evaluate_adjudicated_reviews(
        [queue_a, queue_b], {"adjudications": [adjudication("reused-id", "relevant")]}
    )

    assert report["metric_eligible_candidates"] == 0
    assert report["conflicting_candidate_record_count"] == 1
    assert set(report["conflicting_candidate_records"][0]["fields"]) == {"run_id", "policy_version"}
    assert "conflicting_candidate_records" in report["candidate_results"][0]["exclusion_reasons"]

def test_same_candidate_with_missing_provenance_is_not_merged_with_known_provenance():
    queue_a = ("run-unknown.json", {
        "reviews": [review("reused-id", "included")],
    })
    queue_b = ("run-known.json", {
        "run_id": "run-known", "policy_version": "policy-v1",
        "reviews": [review("reused-id", "included")],
    })

    report = evaluate_adjudicated_reviews(
        [queue_a, queue_b], {"adjudications": [adjudication("reused-id", "relevant")]}
    )

    assert report["metric_eligible_candidates"] == 0
    assert report["conflicting_candidate_record_count"] == 1
    assert set(report["conflicting_candidate_records"][0]["fields"]) == {"run_id", "policy_version"}
    assert "conflicting_candidate_records" in report["candidate_results"][0]["exclusion_reasons"]

