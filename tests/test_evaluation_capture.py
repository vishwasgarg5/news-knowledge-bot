import json

from scripts.evaluation_capture import build_capture_record


def test_capture_preserves_included_and_excluded_candidates_without_labels():
    record = build_capture_record(
        articles=[
            {"title": "Included story", "source": "A", "url": "https://a.example/1",
             "published": "2026-10-21T10:00:00+05:30", "summary": "First"},
            {"headline": "Excluded story", "source": "B", "url": "https://b.example/2",
             "published_at": "2026-10-21T10:05:00+05:30", "description": "Second"},
        ],
        included_urls={"https://a.example/1"},
        run_id="run-1",
        run_timestamp="2026-10-21T10:10:00+05:30",
        policy_version="policy-v1",
    )

    assert record["schema_version"] == "1.0"
    assert record["policy_version"] == "policy-v1"
    assert [x["disposition"] for x in record["candidate_articles"]] == ["included", "excluded"]
    assert record["candidate_articles"][1]["title"] == "Excluded story"
    assert record["story_labels"] == []
    assert record["labeling_status"] == "pending_review"


def test_capture_ids_are_stable_and_duplicate_urls_are_deduplicated():
    articles = [
        {"title": "A", "source": "Publisher", "url": "https://a.example/story"},
        {"title": "A revised title", "source": "Publisher", "url": "https://a.example/story"},
    ]
    first = build_capture_record(articles, set(), "r", "2026-10-21T10:00:00+05:30", "p")
    second = build_capture_record(articles[:1], set(), "r", "2026-10-21T10:00:00+05:30", "p")

    assert len(first["candidate_articles"]) == 1
    assert first["candidate_articles"][0]["candidate_id"] == second["candidate_articles"][0]["candidate_id"]


def test_capture_does_not_infer_labels_from_production_verification():
    record = build_capture_record(
        articles=[{"title": "A", "url": "https://a.example", "verification": {"verified": True}}],
        included_urls={"https://a.example"},
        run_id="r",
        run_timestamp="2026-10-21T10:00:00+05:30",
        policy_version="p",
    )

    assert record["story_labels"] == []
    assert "verification" not in record["candidate_articles"][0]


def test_capture_record_can_be_serialized_as_json():
    record = build_capture_record(
        [{"title": "A", "url": "https://a.example"}],
        {"https://a.example"},
        "r",
        "2026-10-21T10:00:00+05:30",
        "p",
    )

    assert json.loads(json.dumps(record))["run_id"] == "r"
