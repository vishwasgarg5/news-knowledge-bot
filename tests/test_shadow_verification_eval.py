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
    assert result["cases"] == 6
    assert result["baseline_metrics"]["tp"] + result["baseline_metrics"]["fn"] == 3
    assert result["candidate_metrics"]["tp"] + result["candidate_metrics"]["fn"] == 3
    assert "Synthetic fixtures do not estimate real-world precision, recall, or F1." in result["limitations"]
    assert all("candidate_accept" in row for row in result["cases_detail"])


def test_candidate_gate_does_not_accept_single_independent_report_unless_official():
    result = evaluate()
    row = next(x for x in result["cases_detail"] if x["case"] == "only-one-independent-report")
    assert row["independent_sources"] == 1
    assert row["baseline_accept"] is True
    assert row["candidate_accept"] is False
