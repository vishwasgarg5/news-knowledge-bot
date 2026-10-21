import json

from scripts.evaluate_historical_records import evaluate_record, evaluate_paths
from scripts.validate_evaluation_record import validate_record


def record_with_reviews():
    return {
        "schema_version": "1.0",
        "run_id": "offline-eval-001",
        "run_timestamp": "2026-10-21T10:00:00+05:30",
        "policy_version": "policy-v1",
        "candidate_articles": [
            {"candidate_id": "c1", "title": "Relevant included", "source": "A", "url": "https://a.example/1",
             "published_at": "2026-10-21T09:00:00+05:30", "summary": "Summary", "disposition": "included"},
            {"candidate_id": "c2", "title": "Irrelevant included", "source": "B", "url": "https://b.example/2",
             "published_at": "2026-10-21T09:01:00+05:30", "summary": "Summary", "disposition": "included"},
            {"candidate_id": "c3", "title": "Relevant excluded", "source": "C", "url": "https://c.example/3",
             "published_at": "2026-10-21T09:02:00+05:30", "summary": "Summary", "disposition": "excluded"},
            {"candidate_id": "c4", "title": "Uncertain excluded", "source": "D", "url": "https://d.example/4",
             "published_at": "2026-10-21T09:03:00+05:30", "summary": "Summary", "disposition": "excluded"},
        ],
        "story_labels": [],
        "candidate_reviews": [
            {"candidate_id": "c1", "relevance_label": "relevant", "reviewer_id": "reviewer-1",
             "reviewed_at": "2026-10-21T11:00:00+05:30", "rationale": "Matches evaluation scope."},
            {"candidate_id": "c2", "relevance_label": "not_relevant", "reviewer_id": "reviewer-1",
             "reviewed_at": "2026-10-21T11:01:00+05:30", "rationale": "Outside the defined scope."},
            {"candidate_id": "c3", "relevance_label": "relevant", "reviewer_id": "reviewer-2",
             "reviewed_at": "2026-10-21T11:02:00+05:30", "rationale": "Important event was omitted."},
            {"candidate_id": "c4", "relevance_label": "uncertain", "reviewer_id": "reviewer-2",
             "reviewed_at": "2026-10-21T11:03:00+05:30", "rationale": "Insufficient context."},
        ],
    }


def test_candidate_reviews_validate_and_unknown_candidate_is_rejected():
    record = record_with_reviews()
    assert validate_record(record) == []
    record["candidate_reviews"][0]["candidate_id"] = "missing"
    assert "candidate_reviews[0]_candidate_id_unknown" in validate_record(record)


def test_metrics_count_false_positive_and_missed_relevant_without_using_uncertain():
    result = evaluate_record(record_with_reviews())

    assert result["schema_valid"] is True
    assert result["false_positives"] == 1
    assert result["missed_relevant_candidates"] == 1
    assert result["true_positives"] == 1
    assert result["inclusion_precision"] == 0.5
    assert result["inclusion_recall"] == 0.5
    assert result["candidate_relevance_labels"]["uncertain"] == 1


def test_story_support_labels_are_not_substituted_for_candidate_relevance():
    record = record_with_reviews()
    record["candidate_reviews"] = []
    record["story_labels"] = [
        {"story_id": "c2", "label": "supported", "reviewer_id": "reviewer-1",
         "reviewed_at": "2026-10-21T11:00:00+05:30", "rationale": "Claim confirmed."}
    ]

    result = evaluate_record(record)

    assert result["story_claim_labels"] == 1
    assert result["candidate_reviews"] == 0
    assert result["false_positives"] == 0
    assert result["inclusion_precision"] is None
    assert result["inclusion_recall"] is None


def test_directory_evaluation_reports_invalid_records(tmp_path):
    (tmp_path / "valid.json").write_text(json.dumps(record_with_reviews()), encoding="utf-8")
    (tmp_path / "invalid.json").write_text('{"schema_version": "bad"}', encoding="utf-8")

    result = evaluate_paths(sorted(tmp_path.glob("*.json")))

    assert result["records_seen"] == 2
    assert result["schema_valid_records"] == 1
    assert result["invalid_records"] == 1
