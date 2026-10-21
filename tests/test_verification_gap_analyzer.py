from __future__ import annotations

from scripts.analyze_verification_gaps import analyze_snapshot, render_markdown


def article(
    title,
    source="Reuters",
    published="2026-10-20T12:00:00+00:00",
    summary="Officials confirmed the development and said more details would be released soon.",
):
    return {
        "title": title,
        "source": source,
        "published": published,
        "summary": summary,
        "url": "https://www.reuters.com/world/example-story",
    }


def test_analyzer_flags_missing_corroboration_and_stale_primary():
    snapshot = {
        "date": "2026-10-21",
        "intelligence_v5": {"stories": [{
            "headline": "Central bank raises interest rate after inflation accelerates",
            "source": "Example News",
            "published": "2026-10-17T00:00:00+00:00",
            "verification": {
                "evidence": [],
                "independent_sources": 0,
                "verification": "single-source",
                "verification_reason": "no independent current corroboration",
                "primary_fresh": False,
                "freshness_hours": 100,
            },
        }]},
    }
    result = analyze_snapshot("fixture", "test-sha", snapshot)
    row = result["stories"][0]
    assert "no_saved_corroborating_evidence" in row["diagnostics"]
    assert "no_independent_sources" in row["diagnostics"]
    assert "primary_article_stale_by_recorded_metadata" in row["diagnostics"]
    assert result["independent_source_distribution"]["zero_independent_sources"] == 1


def test_analyzer_flags_roundup_duplicate_and_weak_headline_match():
    title = "City approves new bridge after severe flood damage across northern region"
    snapshot = {
        "date": "2026-10-21",
        "intelligence_v5": {"stories": [{
            "headline": "City approves new bridge after flood damage",
            "source": "Example News",
            "published": "2026-10-21T00:00:00+00:00",
            "verification": {
                "evidence": [
                    article(title, "Example Digest"),
                    article(title, "Example Digest"),
                    article("Unrelated technology company reports quarterly revenue", "Other Source"),
                ],
                "independent_sources": 1,
                "verification": "multi-report",
                "primary_fresh": True,
                "freshness_hours": 1,
            },
        }]},
    }
    result = analyze_snapshot("fixture", "test-sha", snapshot)
    row = result["stories"][0]
    assert "only_one_independent_source" in row["diagnostics"]
    assert "derivative_or_roundup_evidence" in row["diagnostics"]
    assert "near_identical_copy_in_saved_evidence" in row["diagnostics"]
    assert "saved_evidence_weak_headline_match" in row["diagnostics"]


def test_analyzer_flags_definitely_stale_saved_evidence_conservatively():
    snapshot = {
        "date": "2026-10-21",
        "intelligence_v5": {"stories": [{
            "headline": "City approves new bridge after flood damage",
            "source": "Example News",
            "published": "2026-10-21T00:00:00+00:00",
            "verification": {
                "evidence": [article(
                    "City approves new bridge after severe flood damage across northern region",
                    "Reuters",
                    "2026-10-16T00:00:00+00:00",
                )],
                "independent_sources": 1,
                "verification": "multi-report",
                "primary_fresh": True,
                "freshness_hours": 1,
            },
        }]},
    }
    result = analyze_snapshot("fixture", "test-sha", snapshot)
    assert "evidence_definitely_older_than_72h" in result["stories"][0]["diagnostics"]


def test_markdown_report_includes_counts_and_limitations():
    result = analyze_snapshot("fixture", "abc123", {
        "date": "2026-10-21",
        "intelligence_v5": {"stories": [{
            "headline": "Headline",
            "verification": {"evidence": [], "independent_sources": 0},
        }]},
    })
    report = render_markdown([result])
    assert "Zero independent sources" in report
    assert "not a new verification score" in report
    assert "No network calls" in report
