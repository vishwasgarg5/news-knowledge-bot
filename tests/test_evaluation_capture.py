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


def test_write_capture_record_persists_json(tmp_path):
    from scripts.evaluation_capture import write_capture_record

    path = write_capture_record(
        [{"title": "Captured story", "source": "Publisher", "url": "https://example.com/a"}],
        {"https://example.com/a"},
        tmp_path,
        "2026-10-21T10:00:00+05:30",
        "scheduled",
        "policy-v1",
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["candidate_articles"][0]["disposition"] == "included"
    assert saved["story_labels"] == []



def test_capture_uses_fallback_fields_and_cleans_available_summary_content():
    record = build_capture_record(
        articles=[{
            "headline": "Feed headline",
            "publisher": {"title": "Publisher Name"},
            "link": "https://example.com/story",
            "publication_date": "2026-10-22T08:00:00Z",
            "summary": "",
            "description": "<p>Useful &amp; available <b>context</b>.</p>",
        }],
        included_urls={"https://example.com/story"},
        run_id="fallback-fields",
        run_timestamp="2026-10-22T09:00:00+00:00",
        policy_version="p",
    )

    candidate = record["candidate_articles"][0]
    assert candidate["title"] == "Feed headline"
    assert candidate["category"] == ""
    assert candidate["source"] == "Publisher Name"
    assert candidate["url"] == "https://example.com/story"
    assert candidate["published_at"] == "2026-10-22T08:00:00Z"
    assert candidate["summary"] == "Useful & available context."
    assert candidate["disposition"] == "included"


def test_capture_handles_missing_or_malformed_metadata_without_inventing_values():
    record = build_capture_record(
        articles=[
            {"title": "No source metadata", "source": {}, "url": "https://example.com/missing"},
            {"headline": "Malformed source", "source": ["unexpected", "shape"],
             "link": "https://example.com/malformed", "published": "not-a-date",
             "content": [{"value": "<p>Actual snippet</p>"}]},
            None,
        ],
        included_urls=set(),
        run_id="metadata-gaps",
        run_timestamp="2026-10-22T09:00:00+00:00",
        policy_version="p",
    )

    candidates = record["candidate_articles"]
    assert len(candidates) == 2
    assert candidates[0]["source"] == ""
    assert candidates[0]["published_at"] == ""
    assert candidates[0]["summary"] == ""
    assert candidates[1]["source"] == "unexpected shape"
    assert candidates[1]["published_at"] == "not-a-date"
    assert candidates[1]["summary"] == "Actual snippet"
    assert all(candidate["disposition"] == "excluded" for candidate in candidates)
