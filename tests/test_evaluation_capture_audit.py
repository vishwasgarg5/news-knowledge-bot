import json

from scripts.audit_evaluation_captures import audit_directory, audit_record
from scripts.audit_capture_quality_trend import build_trend


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



def test_capture_quality_trend_reports_coverage_and_detects_regression():
    from pathlib import Path

    complete = {
        "run_id": "older",
        "run_timestamp": "2026-10-20T08:00:00Z",
        "candidate_articles": [{
            "title": "Title", "source": "Source", "url": "https://example.com/a",
            "published_at": "2026-10-20T07:00:00Z", "summary": "Real available summary",
        }],
    }
    incomplete = {
        "run_id": "newer",
        "run_timestamp": "2026-10-21T08:00:00Z",
        "candidate_articles": [{
            "title": "Title", "source": "Source", "url": "https://example.com/b",
            "published_at": "2026-10-21T07:00:00Z", "summary": "",
        }],
    }

    report = build_trend([(Path("older.json"), complete), (Path("newer.json"), incomplete)])

    assert report["record_count"] == 2
    assert report["candidate_count"] == 2
    assert report["overall_field_coverage"]["summary"] == 0.5
    assert report["missing_field_counts"]["summary"] == 1
    assert report["quality_gate"]["status"] == "BLOCKED"
    assert report["latest_run"]["summary_coverage_by_category"]["unknown"] == {
        "candidate_count": 1, "summary_present_count": 0,
        "summary_missing_count": 1, "summary_coverage": 0.0,
    }
    assert report["previous_run_comparison"]["regressions"] == [{
        "field": "summary", "previous_coverage": 1.0, "latest_coverage": 0.0, "delta": -1.0,
    }]
    assert report["previous_run_comparison"]["summary_coverage_by_category_delta"]["unknown"] == {
        "previous_candidate_count": 1, "latest_candidate_count": 1,
        "previous_summary_coverage": 1.0, "latest_summary_coverage": 0.0,
        "coverage_delta": -1.0,
    }
    assert report["latest_run"]["summary_coverage_by_source"]["Source"]["summary_missing_count"] == 0
    assert report["previous_run_comparison"]["summary_coverage_by_source_delta"]["Source"] == {
        "previous_candidate_count": 1, "latest_candidate_count": 0,
        "previous_summary_coverage": 1.0, "latest_summary_coverage": None,
        "coverage_delta": None,
    }


def test_capture_quality_trend_requires_history_and_does_not_invent_fields():
    from pathlib import Path

    report = build_trend([(Path("one.json"), {
        "run_id": "one", "run_timestamp": "2026-10-22T08:00:00Z",
        "candidate_articles": [{"title": "Known", "summary": ""}],
    })])

    assert report["quality_gate"]["status"] == "INSUFFICIENT_HISTORY"
    assert report["overall_field_coverage"]["title"] == 1.0
    assert report["overall_field_coverage"]["summary"] == 0.0
    assert report["missing_field_counts"]["summary"] == 1
    assert report["previous_run_comparison"] is None



def test_audit_keeps_partial_reviews_in_progress_and_rejects_incomplete_labels():
    partial = {
        "run_id": "run-partial", "policy_version": "policy-v1", "labeling_status": "in_progress",
        "candidate_articles": [
            {"candidate_id": "c1", "title": "A", "source": "S", "url": "https://a.example",
             "published_at": "2026-10-22T08:00:00Z", "summary": "Summary", "disposition": "included"},
            {"candidate_id": "c2", "title": "B", "source": "S", "url": "https://b.example",
             "published_at": "2026-10-22T08:00:00Z", "summary": "Summary", "disposition": "excluded"},
        ],
        "story_labels": [{
            "story_id": "story-1", "label": "supported", "reviewer": "r1",
            "reviewed_at": "2026-10-22T09:00:00Z", "rationale": "Confirmed independently.",
            "candidate_ids": ["c1"], "evidence_urls": ["https://official.example/a"],
        }],
    }
    result = audit_record(partial, "partial.json")
    assert result["status"] == "in_progress"
    assert result["invalid_label_count"] == 0

    partial["story_labels"][0]["evidence_urls"] = []
    invalid = audit_record(partial, "partial.json")
    assert invalid["invalid_label_count"] == 1
    assert "human_label_incomplete_or_invalid" in invalid["errors"]
