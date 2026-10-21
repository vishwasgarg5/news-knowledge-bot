from __future__ import annotations

from scripts.replay_syndication_audit import analyze_snapshot, render_markdown


def article(title: str, summary: str) -> dict[str, str]:
    return {"title": title, "summary": summary, "source": "Example", "url": "https://example.test/story"}


def test_replay_excludes_near_identical_copy_but_keeps_distinct_reporting():
    shared = "Government announces major transport infrastructure investment across northern districts"
    story = {
        "headline": "Transport investment announced",
        "verification": {
            "evidence": [
                article(
                    "Government announces major transport infrastructure investment across northern districts",
                    shared + " Officials said the project will improve regional access and reduce travel times for residents.",
                ),
                article(
                    "Government announces major transport infrastructure investment across northern districts",
                    shared + " Officials said the project will improve regional access and reduce travel times for residents.",
                ),
                article(
                    "Local residents question the transport project's timetable",
                    "Community groups asked officials to publish the construction timetable and explain how delays will be handled.",
                ),
            ]
        },
    }
    result = analyze_snapshot("fixture", "test-sha", {
        "date": "fixture",
        "intelligence_v5": {"stories": [story]},
    })
    assert result["stories"] == 1
    assert result["saved_evidence_rows"] == 3
    assert result["likely_copies_excluded"] == 1
    assert result["retained_rows_estimate"] == 2
    assert result["affected_stories"][0]["rows_retained"] == 2


def test_replay_handles_empty_and_missing_evidence():
    result = analyze_snapshot("empty", "test-sha", {
        "intelligence_v5": {"stories": [
            {"headline": "No evidence", "verification": {"evidence": []}},
            {"headline": "Missing evidence"},
        ]}
    })
    assert result["stories"] == 2
    assert result["saved_evidence_rows"] == 0
    assert result["likely_copies_excluded"] == 0
    assert result["affected_stories"] == []


def test_markdown_report_discloses_scope_and_limitations():
    result = analyze_snapshot("fixture", "abc123", {
        "date": "2026-10-21",
        "intelligence_v5": {"stories": [
            {"headline": "Headline | with pipe", "verification": {"evidence": []}}
        ]},
    })
    report = render_markdown([result])
    assert "Retained rows (estimate)" in report
    assert "not recorded historical runtime metrics" in report
    assert "does not access the network" in report
