from types import SimpleNamespace

from app.news import Article, _summary_field_provenance, _summary_text, collect, fetch_feed
from scripts.evaluation_capture import build_capture_record
from scripts.audit_capture_quality_trend import _summary_provenance


def test_collect_reports_missing_publisher_summaries_per_feed(monkeypatch):
    articles = [
        Article("Story with summary", "Publisher description", "https://example.com/1", "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-1"),
        Article("Harbour bridge repairs delayed", "", "https://example.com/2", "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-2"),
        Article("Quantum telescope launched", "  ", "https://example.com/3", "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-3"),
        Article("Monsoon crops recover", "", "https://example.com/4", "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-4"),
        Article("Hospital opens wing", "", "https://example.com/5", "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-5"),
    ]
    monkeypatch.setattr("app.news.fetch_feed", lambda *args: (articles, True, ""))
    monkeypatch.setattr("app.news.time.sleep", lambda *_: None)
    collected, stats = collect({"world": ["https://example.com/feed"]})
    source = stats["source_status"][0]
    assert len(collected) == 5
    assert source["count"] == 5
    assert source["summary_missing_count"] == 4
    assert [row["title"] for row in source["missing_summary_examples"]] == [
        "Harbour bridge repairs delayed", "Quantum telescope launched", "Monsoon crops recover"
    ]
    assert source["summary_field_state_counts"] == {}
    assert source["missing_summary_examples"][0]["summary_provenance_status"] == "unavailable"


def test_collect_reports_parser_provenance_for_missing_summaries(monkeypatch):
    articles = [
        Article(
            "Blank publisher summary",
            "",
            "https://example.com/blank",
            "Example Feed",
            "world",
            "2026-10-23T00:00:00+00:00",
            "id-blank",
            summary_selected_field=None,
            summary_field_diagnostics={
                "summary": "blank",
                "description": "missing_key",
            },
        ),
        Article(
            "Publisher summary present",
            "Publisher text",
            "https://example.com/present",
            "Example Feed",
            "world",
            "2026-10-23T00:00:00+00:00",
            "id-present",
            summary_selected_field="summary",
            summary_field_diagnostics={
                "summary": "present",
                "description": "missing_key",
            },
        ),
    ]
    monkeypatch.setattr("app.news.fetch_feed", lambda *args: (articles, True, ""))
    monkeypatch.setattr("app.news.time.sleep", lambda *_: None)

    _, stats = collect({"world": ["https://example.com/feed"]})

    source = stats["source_status"][0]
    assert source["summary_missing_count"] == 1
    assert source["summary_field_state_counts"] == {
        "summary": {"present": 0, "blank": 1, "missing_key": 0, "other": 0},
        "description": {"present": 0, "blank": 0, "missing_key": 1, "other": 0},
    }
    example = source["missing_summary_examples"][0]
    assert example["summary_selected_field"] is None
    assert example["summary_field_diagnostics"] == {
        "summary": "blank",
        "description": "missing_key",
    }
    assert example["summary_provenance_status"] == "captured"


def test_fetch_feed_logs_bounded_field_diagnostics_for_blank_summaries(monkeypatch, capsys):
    class Response:
        content = b"offline fixture"
        status_code = 200
        headers = {"Content-Type": "application/rss+xml"}
        def raise_for_status(self): return None
    entries = [{"title": f"Blank summary story {i}", "link": f"https://example.com/{i}",
                "author": "Reporter", "summary": "", "summary_detail": {"type": "text", "value": ""}}
               for i in range(4)]
    parsed = SimpleNamespace(entries=entries, feed={"title": "Synthetic Publisher Feed"}, bozo=False, bozo_exception=None)
    monkeypatch.setattr("app.news.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.news.feedparser.parse", lambda _content: parsed)
    articles, ok, warning = fetch_feed("https://example.com/feed", "world", limit=10)
    output = capsys.readouterr().out
    assert ok and warning == "" and len(articles) == 4
    assert output.count("[SUMMARY FIELD GAP]") == 3
    assert "publisher_summary_fields_present=none" in output
    assert "publisher_summary_field_shapes=['summary=string(len=0)', 'summary_detail=mapping(value:len=0)']" in output
    assert articles[0].summary_selected_field is None
    assert articles[0].summary_field_diagnostics["summary"] == "blank"
    assert articles[0].summary_field_diagnostics["summary_detail"] == "blank"
    assert articles[0].summary_field_diagnostics["description"] == "missing_key"


def test_summary_extractor_uses_publisher_detail_and_content_fallbacks():
    assert _summary_text({"summary": "", "description": "", "summary_detail": {"value": "<p>Publisher &amp; verified context.</p>"}}) == "Publisher & verified context."
    assert _summary_text({"summary": "", "description": "", "content": [{"value": "<p>Actual article excerpt</p>"}]}) == "Actual article excerpt"


def test_summary_extractor_does_not_substitute_unrelated_entry_metadata():
    assert _summary_text({"title": "Story headline", "author": "Reporter", "tags": [{"term": "business"}], "summary": "   ", "description": ""}) == ""


def test_summary_provenance_matches_actual_extractor_precedence():
    entry = {
        "summary": "Normalized publisher summary",
        "media_description": "Different extension text",
        "content": [{"value": "Longer article body"}],
    }
    selected, diagnostics = _summary_field_provenance(entry)
    assert _summary_text(entry) == "Normalized publisher summary"
    assert selected == "summary"
    assert diagnostics["summary"] == "present"
    assert diagnostics["media_description"] == "present"
    assert diagnostics["content"] == "present"


def test_feedparser_xml_namespace_summary_is_extracted_offline():
    import feedparser
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Synthetic RSS</title>
    <item><title>Namespace summary example</title><link>https://example.com/namespace-summary</link>
    <media:description><![CDATA[Publisher-provided media summary.]]></media:description></item></channel></rss>"""
    parsed = feedparser.parse(xml)
    assert len(parsed.entries) == 1
    assert _summary_text(parsed.entries[0]) == "Publisher-provided media summary."


def test_fetch_feed_extracts_namespaced_rss_summary_end_to_end_offline(monkeypatch, capsys):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>Synthetic Publisher Feed</title>
    <item><title>End-to-end namespace summary</title><link>https://example.com/end-to-end-summary</link>
    <media:description><![CDATA[Publisher-provided media summary for offline integration test.]]></media:description></item></channel></rss>"""
    class Response:
        content = xml
        status_code = 200
        headers = {"Content-Type": "application/rss+xml"}
        def raise_for_status(self): return None
    monkeypatch.setattr("app.news.requests.get", lambda *args, **kwargs: Response())
    articles, ok, warning = fetch_feed("https://example.com/feed", "world", limit=10)
    assert ok and warning == "" and len(articles) == 1
    assert articles[0].source == "Synthetic Publisher Feed"
    assert articles[0].summary == "Publisher-provided media summary for offline integration test."
    # feedparser normalizes media:description into its standard summary key.
    assert articles[0].summary_selected_field == "summary"
    assert articles[0].summary_field_diagnostics["summary"] == "present"
    assert articles[0].summary_field_diagnostics["media_description"] == "missing_key"
    assert "[SUMMARY FIELD GAP]" not in capsys.readouterr().out


def test_feedparser_content_encoded_summary_is_extracted_offline():
    import feedparser
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Synthetic Content Feed</title>
    <item><title>Encoded content summary example</title><link>https://example.com/content-encoded-summary</link>
    <description></description><content:encoded><![CDATA[<p>Publisher excerpt from content:encoded.</p>]]></content:encoded></item></channel></rss>"""
    parsed = feedparser.parse(xml)
    assert len(parsed.entries) == 1
    assert _summary_text(parsed.entries[0]) == "Publisher excerpt from content:encoded."


def test_atom_xml_fixture_extracts_publisher_summary_without_fabricating_missing_text():
    from pathlib import Path
    import feedparser

    fixture_path = Path(__file__).parent / "fixtures" / "rss" / "atom_summary.xml"
    parsed = feedparser.parse(fixture_path.read_bytes())
    assert len(parsed.entries) == 2

    summary_entry, missing_entry = parsed.entries
    assert _summary_text(summary_entry) == "Publisher-provided Atom summary with & encoded text."
    selected, diagnostics = _summary_field_provenance(summary_entry)
    assert selected == "summary"
    assert diagnostics["summary"] == "present"

    assert _summary_text(missing_entry) == ""
    selected, diagnostics = _summary_field_provenance(missing_entry)
    assert selected is None
    assert diagnostics["summary"] == "missing_key"


def test_parser_article_provenance_survives_production_capture_boundary():
    # app.main passes Article.__dict__ into write_capture_record; exercise that
    # exact boundary offline so parser diagnostics cannot silently disappear.
    article = Article(
        title="Publisher entry without a summary",
        summary="",
        url="https://example.com/no-summary",
        source="Example Feed",
        category="world",
        published="2026-10-24T00:00:00+00:00",
        article_id="offline-no-summary",
        summary_selected_field=None,
        summary_field_diagnostics={
            "summary": "blank",
            "description": "missing_key",
            "summary_detail": "blank",
            "content": "missing_key",
        },
    )

    record = build_capture_record(
        articles=[article.__dict__],
        included_urls=set(),
        run_id="offline-provenance-boundary",
        run_timestamp="2026-10-24T00:00:00+00:00",
        policy_version="test",
    )

    candidate = record["candidate_articles"][0]
    assert candidate["summary"] == ""
    assert candidate["summary_selected_field"] is None
    assert candidate["summary_field_diagnostics"] == {
        "summary": "blank",
        "description": "missing_key",
        "summary_detail": "blank",
        "content": "missing_key",
    }



def test_legacy_capture_without_parser_diagnostics_is_explicitly_unknown():
    provenance = _summary_provenance({"summary": ""})

    assert provenance["summary_selected_field"] is None
    assert provenance["summary_field_diagnostics"] == {}
    assert provenance["summary_provenance_status"] == "unavailable_legacy_capture"


def test_capture_with_parser_diagnostics_is_marked_as_captured():
    provenance = _summary_provenance({
        "summary": "",
        "summary_selected_field": None,
        "summary_field_diagnostics": {
            "summary": "blank",
            "description": "missing_key",
        },
    })

    assert provenance["summary_provenance_status"] == "captured"
