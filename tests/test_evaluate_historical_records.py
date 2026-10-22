from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_historical_records import evaluate_paths, evaluate_record


def record_with_reviews(labels_and_dispositions):
    candidates = []
    reviews = []
    for index, (disposition, label) in enumerate(labels_and_dispositions):
        candidate_id = f"candidate-{index}"
        candidates.append({
            "candidate_id": candidate_id,
            "title": f"Candidate {index}",
            "source": "Publisher",
            "url": f"https://example.com/{index}",
            "published_at": "2026-10-22T08:00:00+00:00",
            "summary": "A candidate summary.",
            "disposition": disposition,
        })
        reviews.append({
            "candidate_id": candidate_id,
            "relevance_label": label,
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-10-22T09:00:00+00:00",
            "rationale": "Independently checked against source material.",
        })
    return {
        "schema_version": "1.0",
        "run_id": "test-run",
        "run_timestamp": "2026-10-22T08:00:00+00:00",
        "policy_version": "test-policy",
        "candidate_articles": candidates,
        "candidate_reviews": reviews,
        "story_labels": [],
        "evaluation_sampling": {
            "sampling_method": "deterministic_stratified_by_disposition",
            "sampling_seed": "test-seed",
        },
    }


def test_report_computes_confusion_matrix_and_explicit_false_positive_negative_counts():
    record = record_with_reviews([
        ("included", "relevant"),
        ("included", "not_relevant"),
        ("excluded", "relevant"),
        ("excluded", "not_relevant"),
        ("duplicate", "relevant"),
        ("included", "uncertain"),
    ])

    result = evaluate_record(record)

    assert result["schema_valid"] is True
    assert result["confusion_matrix"] == {
        "true_positives": 1, "false_positives": 1,
        "true_negatives": 1, "false_negatives": 1,
    }
    assert result["false_positives"] == 1
    assert result["missed_relevant_candidates"] == 1
    assert result["metric_eligible_reviews"] == 4
    assert result["accuracy"] == 0.5
    assert result["inclusion_precision"] == 0.5
    assert result["inclusion_recall"] == 0.5
    assert result["specificity"] == 0.5
    assert result["balanced_accuracy"] == 0.5
    assert result["f1"] == 0.5
    assert result["candidate_relevance_labels"]["uncertain"] == 1


def test_aggregate_gate_blocks_small_samples_and_keeps_sampling_metadata(tmp_path):
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record_with_reviews([
        ("included", "relevant"),
        ("included", "not_relevant"),
        ("excluded", "relevant"),
    ])), encoding="utf-8")

    report = evaluate_paths([path], min_reviewed_candidates=5, min_per_class=2)

    assert report["evaluation_gate"]["status"] == "BLOCKED_INSUFFICIENT_SAMPLE"
    assert set(report["evaluation_gate"]["reasons"]) == {
        "insufficient_metric_eligible_reviews",
        "insufficient_relevant_class_support",
        "insufficient_not_relevant_class_support",
    }
    assert report["class_support"] == {"relevant": 2, "not_relevant": 1}
    assert report["evaluation_sampling"]["per_record"][0]["sampling"]["sampling_seed"] == "test-seed"
    assert report["confusion_matrix"]["false_positives"] == 1


def test_aggregate_gate_only_reports_thresholds_met_when_both_classes_have_support(tmp_path):
    path = tmp_path / "record.json"
    rows = ([("included", "relevant")] * 10
            + [("included", "not_relevant")] * 2
            + [("excluded", "relevant")] * 2
            + [("excluded", "not_relevant")] * 10)
    path.write_text(json.dumps(record_with_reviews(rows)), encoding="utf-8")

    report = evaluate_paths([path], min_reviewed_candidates=20, min_per_class=10)

    assert report["evaluation_gate"]["status"] == "SAMPLE_THRESHOLDS_MET"
    assert report["metric_eligible_reviews"] == 24
    assert report["class_support"] == {"relevant": 12, "not_relevant": 12}
    assert report["evaluation_gate"]["reasons"] == []
    assert report["limitations"][2] == "Story claim-support labels are distinct from candidate relevance labels."


@pytest.mark.parametrize("minimum,per_class", [(0, 1), (1, 0)])
def test_invalid_sample_thresholds_are_rejected(minimum, per_class):
    with pytest.raises(ValueError, match="at least 1"):
        evaluate_paths([], min_reviewed_candidates=minimum, min_per_class=per_class)
