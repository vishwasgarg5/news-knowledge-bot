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
    assert result["cases"] == 10
    assert result["baseline_metrics"]["tp"] + result["baseline_metrics"]["fn"] == 5
    assert result["candidate_metrics"]["tp"] + result["candidate_metrics"]["fn"] == 5
    assert "Synthetic fixtures do not estimate real-world precision, recall, or F1." in result["limitations"]
    assert all("candidate_accept" in row for row in result["cases_detail"])


def test_candidate_gate_does_not_accept_single_independent_report_unless_official():
    result = evaluate()
    row = next(x for x in result["cases_detail"] if x["case"] == "only-one-independent-report")
    assert row["independent_sources"] == 1
    assert row["baseline_accept"] is True
    assert row["candidate_accept"] is False


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
