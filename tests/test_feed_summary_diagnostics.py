from app.news import Article, collect


def test_collect_reports_missing_publisher_summaries_per_feed(monkeypatch):
    articles = [
        Article("Story with summary", "Publisher description", "https://example.com/1",
                "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-1"),
        Article("Story without summary A", "", "https://example.com/2",
                "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-2"),
        Article("Story without summary B", "  ", "https://example.com/3",
                "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-3"),
        Article("Story without summary C", "", "https://example.com/4",
                "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-4"),
        Article("Story without summary D", "", "https://example.com/5",
                "Example Feed", "world", "2026-10-23T00:00:00+00:00", "id-5"),
    ]
    monkeypatch.setattr("app.news.fetch_feed", lambda *args: (articles, True, ""))
    monkeypatch.setattr("app.news.time.sleep", lambda *_: None)

    collected, stats = collect({"world": ["https://example.com/feed"]})
    source = stats["source_status"][0]

    assert len(collected) == 5
    assert source["count"] == 5
    assert source["summary_missing_count"] == 4
    assert len(source["missing_summary_examples"]) == 3
    assert [row["title"] for row in source["missing_summary_examples"]] == [
        "Story without summary A",
        "Story without summary B",
        "Story without summary C",
    ]
    assert all(row["url"].startswith("https://example.com/") for row in source["missing_summary_examples"])
