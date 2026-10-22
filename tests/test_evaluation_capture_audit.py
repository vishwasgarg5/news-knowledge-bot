import json

from scripts.audit_evaluation_captures import audit_directory, audit_record


def test_pending_capture_is_reported_without_inventing_labels():
    record = {
        "run_id": "run-1",
        "run_timestamp": "2026-10-21T10:00:00+05:30",
        "policy_version": "policy-v1",
        "labeling_status": "pending_review",
        "candidate_articles": [
            {"candidate_id": "c1", "title": "Included", "source": "A",
             "url": "https://a.example", "published_at": "2026-10-21T09:00:00+05:30",
             "summary": "Summary", "disposition": "included"},
            {"candidate_id": "c2", "title": "Excluded", "source": "B",
             "url": "https://b.example", "published_at": "2026-10-21T09:05:00+05:30",
             "summary": "Summary", "disposition": "excluded"},
        ],
        "story_labels": [],
    }

    result = audit_record(record, "run.json")

    assert result["status"] == "pending_review"
    assert result["candidate_count"] == 2
    assert result["included_count"] == 1
    assert result["excluded_or_other_count"] == 1
    assert result["label_count"] == 0
    assert result["errors"] == []


def test_audit_directory_reads_captures_and_reports_review_counts(tmp_path):
    pending = {
        "run_id": "run-2",
        "run_timestamp": "2026-10-21T10:00:00+05:30",
        "policy_version": "policy-v1",
        "labeling_status": "pending_review",
        "candidate_articles": [{"candidate_id": "c1", "title": "A", "source": "S",
                                "url": "https://a.example", "published_at": "2026-10-21T09:00:00+05:30",
                                "summary": "Summary", "disposition": "included"}],
        "story_labels": [],
    }
    (tmp_path / "run.json").write_text(json.dumps(pending), encoding="utf-8")

    report = audit_directory(tmp_path)

    assert report["record_count"] == 1
    assert report["pending_review_count"] == 1
    assert report["reviewed_record_count"] == 0
    assert report["records"][0]["run_id"] == "run-2"


def test_audit_flags_incomplete_candidate_metadata():
    result = audit_record({
        "run_id": "run-3",
        "policy_version": "policy-v1",
        "candidate_articles": [{"candidate_id": "c1", "title": "Missing source details"}],
        "story_labels": [],
    })

    assert result["incomplete_candidate_count"] == 1
    assert "candidate_metadata_incomplete" in result["errors"]



def test_audit_reports_field_level_gaps_without_fabricating_values():
    result = audit_record({
        "run_id": "run-4",
        "policy_version": "policy-v1",
        "labeling_status": "pending_review",
        "candidate_articles": [
            {"candidate_id": "c1", "title": "Headline", "source": "Publisher",
             "url": "https://a.example", "published_at": "2026-10-21T09:00:00+05:30",
             "summary": "", "disposition": "included"},
            {"candidate_id": "c2", "title": "Second headline", "source": "Publisher",
             "url": "https://b.example", "published_at": "2026-10-21T09:05:00+05:30",
             "disposition": "mystery"},
        ],
        "story_labels": [],
    })

    assert result["status"] == "pending_review"
    assert result["missing_field_counts"]["summary"] == 2
    assert result["incomplete_candidate_count"] == 2
    assert result["invalid_disposition_count"] == 1
    assert "candidate_metadata_incomplete" in result["errors"]
    assert "candidate_disposition_invalid" in result["errors"]
    assert "summary" in result["incomplete_candidates"][0]["missing"]


def test_directory_aggregates_missing_fields_and_needs_attention(tmp_path):
    reviewed = {
        "run_id": "run-5",
        "policy_version": "policy-v1",
        "candidate_articles": [{
            "candidate_id": "c1", "title": "Headline", "source": "Publisher",
            "url": "https://a.example", "published_at": "2026-10-21T09:00:00+05:30",
            "summary": "", "disposition": "included",
        }],
        "story_labels": [{"story_id": "s1", "label": "supported"}],
    }
    (tmp_path / "reviewed.json").write_text(json.dumps(reviewed), encoding="utf-8")

    report = audit_directory(tmp_path)

    assert report["needs_attention_count"] == 1
    assert report["records"][0]["status"] == "needs_attention"
    assert report["missing_field_counts"]["summary"] == 1
