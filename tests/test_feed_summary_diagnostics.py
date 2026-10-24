from types import SimpleNamespace

from app.news import Article, _summary_text, collect, fetch_feed


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
