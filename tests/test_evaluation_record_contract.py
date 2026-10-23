from copy import deepcopy

from scripts.validate_evaluation_record import validate_record


def valid_record():
    return {
        "schema_version": "1.0",
        "run_id": "news-run-2026-10-21T04:07:00+05:30",
        "run_timestamp": "2026-10-21T04:07:00+05:30",
        "policy_version": "verification-policy-v1",
        "candidate_articles": [
            {
                "candidate_id": "article-001",
                "title": "Example event update",
                "source": "Example News",
                "url": "https://example.com/story",
                "published_at": "2026-10-21T03:45:00+05:30",
                "summary": "An independently reviewable example summary.",
                "disposition": "included",
            },
            {
                "candidate_id": "article-002",
                "title": "Another report of the event",
                "source": "Example Wire",
                "url": "https://example.org/report",
                "published_at": "2026-10-21T03:50:00+05:30",
                "summary": "A second candidate retained for audit, even if excluded.",
                "disposition": "excluded",
            },
        ],
        "story_labels": [
            {
                "story_id": "event-001",
                "label": "supported",
                "reviewer_id": "reviewer-alias-01",
                "reviewed_at": "2026-10-21T05:00:00+05:30",
                "rationale": "Primary source confirms the core event claim.",
                "evidence_urls": ["https://example.com/official-notice"],
            }
        ],
    }


def test_accepts_complete_versioned_record_with_included_and_excluded_candidates():
    assert validate_record(valid_record()) == []


def test_requires_original_candidate_pool_and_independent_labels():
    record = valid_record()
    record.pop("candidate_articles")
    record.pop("story_labels")

    errors = validate_record(record)

    assert "candidate_articles_must_be_nonempty_list" in errors
    assert "story_labels_must_be_nonempty_list" in errors


def test_production_verification_decision_is_not_a_truth_label():
    record = valid_record()
    record.pop("story_labels")
    record["verification"] = {"verified": True, "decision": "official-source"}

    errors = validate_record(record)

    assert "story_labels_must_be_nonempty_list" in errors


def test_rejects_duplicate_candidate_ids_and_invalid_dispositions():
    record = valid_record()
    record["candidate_articles"][1]["candidate_id"] = "article-001"
    record["candidate_articles"][1]["disposition"] = "probably-irrelevant"

    errors = validate_record(record)

    assert "candidate_articles[1]_candidate_id_duplicate" in errors
    assert "candidate_articles[1]_disposition_invalid" in errors


def test_requires_timezone_aware_timestamps_and_supported_label_values():
    record = valid_record()
    record["run_timestamp"] = "2026-10-21T04:07:00"
    record["story_labels"][0]["label"] = "verified-by-production"

    errors = validate_record(record)

    assert "run_timestamp_must_be_timezone_aware_iso8601" in errors
    assert "story_labels[0]_label_invalid" in errors


def test_uncertain_label_requires_rationale():
    record = valid_record()
    record["story_labels"][0]["label"] = "uncertain"
    record["story_labels"][0]["rationale"] = "  "

    assert "story_labels[0]_rationale_required" in validate_record(record)


def test_documented_template_is_schema_valid():
    import json
    from pathlib import Path

    template_path = Path(__file__).resolve().parents[1] / "docs" / "historical-evaluation-record-template.json"
    record = json.loads(template_path.read_text(encoding="utf-8"))
    assert validate_record(record) == []



def test_definitive_story_label_requires_supporting_http_evidence():
    record = valid_record()
    record["story_labels"][0].pop("evidence_urls")

    errors = validate_record(record)

    assert "story_labels[0]_definitive_label_requires_evidence_urls" in errors


def test_definitive_story_label_rejects_invalid_evidence_urls():
    record = valid_record()
    record["story_labels"][0]["evidence_urls"] = ["not-a-url", "ftp://example.com/source"]

    errors = validate_record(record)

    assert "story_labels[0]_definitive_label_requires_valid_evidence_url" in errors


def test_definitive_story_label_accepts_any_valid_http_evidence_url():
    record = valid_record()
    record["story_labels"][0]["evidence_urls"] = [
        "not-a-url",
        "https://independent-source.example/story",
    ]

    assert validate_record(record) == []
