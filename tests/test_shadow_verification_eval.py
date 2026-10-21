from __future__ import annotations

from scripts.shadow_verification_eval import evaluate, _metrics


def test_metrics_calculate_confusion_matrix_and_f1():
    result = _metrics([True, True, False, False], [True, False, True, False])
    assert result == {
        "tp": 1, "fp": 1, "tn": 1, "fn": 1,
        "precision": 0.5, "recall": 0.5, "f1": 0.5,
    }


def test_shadow_evaluation_is_deterministic_in_shape_and_discloses_limits():
    result = evaluate()
    assert result["evaluation_type"] == "synthetic_fixture_shadow_only"
    assert result["cases"] == 12
    assert result["baseline_metrics"]["tp"] + result["baseline_metrics"]["fn"] == 7
    assert result["candidate_metrics"]["tp"] + result["candidate_metrics"]["fn"] == 7
    assert "Synthetic fixtures do not estimate real-world precision, recall, or F1." in result["limitations"]
    assert all("candidate_accept" in row for row in result["cases_detail"])
    assert all("baseline_error" in row and "candidate_error" in row for row in result["cases_detail"])
    assert all("baseline_correct" in row and "candidate_correct" in row for row in result["cases_detail"])
    assert result["error_cases"]["baseline"] == [
        row for row in result["cases_detail"] if row["baseline_error"]
    ]
    assert result["error_cases"]["candidate"] == [
        row for row in result["cases_detail"] if row["candidate_error"]
    ]
    assert result["comparison_summary"]["decisions_changed"] == len(result["decision_changes"])
    assert result["comparison_summary"]["baseline_errors"] == (
        result["baseline_metrics"]["fp"] + result["baseline_metrics"]["fn"]
    )
    assert result["comparison_summary"]["candidate_errors"] == (
        result["candidate_metrics"]["fp"] + result["candidate_metrics"]["fn"]
    )


def test_shadow_report_classifies_false_positives_and_false_negatives():
    result = evaluate()
    rows = result["cases_detail"]
    for row in rows:
        if row["baseline_accept"] and not row["label"]:
            assert row["baseline_error"] == "false_positive"
        elif row["label"] and not row["baseline_accept"]:
            assert row["baseline_error"] == "false_negative"
        else:
            assert row["baseline_error"] is None
        if row["candidate_accept"] and not row["label"]:
            assert row["candidate_error"] == "false_positive"
        elif row["label"] and not row["candidate_accept"]:
            assert row["candidate_error"] == "false_negative"
        else:
            assert row["candidate_error"] is None

    changed = {row["case"] for row in rows if row["decision_changed"]}
    reported = {row["case"] for row in result["decision_changes"]}
    assert reported == changed


def test_candidate_gate_preserves_clean_single_report_path_and_rejects_copy_noise():
    result = evaluate()
    rows = {row["case"]: row for row in result["cases_detail"]}

    # A fresh, non-contradicted single independent report should not be rejected
    # merely because a second publisher is absent.
    for case_id in (
        "only-one-independent-report",
        "one-independent-report-plus-unrelated-article",
        "same-publisher-aliases-plus-unrelated-article",
    ):
        row = rows[case_id]
        assert row["independent_sources"] == 1
        assert row["baseline_accept"] is True
        assert row["candidate_accept"] is True

    syndicated = rows["two-syndicated-copies-of-one-report"]
    assert syndicated["independent_sources"] == 1
    assert syndicated["duplicate_reporting_copies_excluded"] >= 1
    assert syndicated["candidate_accept"] is False

    contradiction = rows["conflicting-reporting-flags-contradiction"]
    assert contradiction["contradiction"] is True
    assert contradiction["candidate_accept"] is False

    derivative = rows["derivative-primary-roundup"]
    assert derivative["primary_derivative"] is True
    assert derivative["candidate_accept"] is False


def test_recall_fixtures_distinguish_unrelated_noise_from_same_publisher_aliases():
    result = evaluate()
    rows = {row["case"]: row for row in result["cases_detail"]}

    single_report = rows["one-independent-report-plus-unrelated-article"]
    assert single_report["label"] is True
    assert single_report["independent_sources"] == 1
    assert single_report["baseline_accept"] is True
    assert single_report["candidate_accept"] is True
    assert single_report["candidate_error"] is None

    aliases = rows["same-publisher-aliases-plus-unrelated-article"]
    assert aliases["label"] is True
    assert aliases["independent_sources"] == 1
    assert aliases["baseline_accept"] is True
    assert aliases["candidate_accept"] is True
    assert aliases["candidate_error"] is None


def test_alias_conflict_and_derivative_fixtures_expose_expected_signals():
    result = evaluate()
    rows = {row["case"]: row for row in result["cases_detail"]}
    assert rows["publisher-aliases-same-identity"]["independent_sources"] == 1
    assert rows["conflicting-reporting-flags-contradiction"]["contradiction"] is True
    assert rows["derivative-primary-roundup"]["primary_derivative"] is True


def test_distinct_summaries_are_not_collapsed_only_for_shared_headline():
    result = evaluate()
    row = next(x for x in result["cases_detail"] if x["case"] == "same-headline-distinct-independent-reporting")
    assert row["independent_sources"] == 2
    assert row["baseline_accept"] is True
