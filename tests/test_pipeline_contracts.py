from __future__ import annotations

"""Contract tests for the production news pipeline.

These tests intentionally stay deterministic: they validate module boundaries,
quality gates, persistence schema, and workflow wiring without network calls
or an Ollama model.
"""

import ast
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_python_modules_parse():
    for path in (ROOT / "app").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_pipeline_import_contracts():
    from app.ai import rerank_stories, select_stories
    from app.analytics import build_report
    from app.intelligence import enrich_trends, personalize
    from app.learning import apply_learning, evaluate_and_learn
    from app.news import collect
    from app.research import research_stories
    from app.storage import ensure_data, sync_sqlite
    from app.telegram import chunks

    assert all(callable(x) for x in (
        collect, research_stories, rerank_stories, select_stories,
        evaluate_and_learn, apply_learning, enrich_trends, personalize,
        ensure_data, sync_sqlite, build_report, chunks,
    ))


def test_research_quality_contract():
    from app.research import verify_article

    story = {
        "headline": "Reuters: major company launches new factory",
        "summary": "The company launched a new factory in India.",
        "source": "Reuters",
        "url": "https://reuters.com/example",
        "published": "2099-01-01T00:00:00+00:00",
    }
    result = verify_article(story, [], [])
    for key in ("verification", "confidence", "source_count",
                "primary_fresh", "primary_trust", "contradiction_flag",
                "freshness_hours"):
        assert key in result


def test_selection_preserves_research_fields():
    from app.ai import select_stories
    rows = select_stories([{
        "title": "Fresh verified event",
        "summary": "A concrete event happened today with enough detail to research.",
        "source": "Reuters",
        "url": "https://reuters.com/example",
        "published": "2099-01-01T00:00:00+00:00",
        "category": "world",
        "region": "world",
    }], top_n=1)
    assert rows and rows[0]["published"]
    assert rows[0]["summary"]

def test_ranking_rejects_unverified_and_stale():
    from app.ai import rerank_stories

    stories = [
        {"story_id": "u", "headline": "Unverified event", "importance": 99,
         "personalized_score": 99, "region": "world", "source": "Unknown",
         "url": "https://example.com/u"},
        {"story_id": "s", "headline": "Stale event", "importance": 99,
         "personalized_score": 99, "region": "world", "source": "Reuters",
         "url": "https://example.com/s"},
        {"story_id": "v", "headline": "Verified event", "importance": 70,
         "personalized_score": 70, "region": "world", "source": "Reuters",
         "url": "https://example.com/v"},
    ]
    research = {
        "u": {"verification": "unverified", "confidence": 30, "primary_fresh": True},
        "s": {"verification": "multi-source", "confidence": 90,
              "independent_sources": 2, "primary_fresh": False},
        "v": {"verification": "multi-source", "confidence": 90,
              "independent_sources": 2, "primary_fresh": True},
    }
    result = rerank_stories(stories, research)
    ids = {x["story_id"] for x in result}
    assert "u" not in ids
    assert "s" not in ids
    assert "v" in ids


def test_learning_does_not_record_current_run_by_default(tmp_path):
    from app.learning import evaluate_and_learn

    root = tmp_path
    (root / "news_learning.csv").write_text(
        "run_date,event_id,story_id,headline,source,category,initial_score,selected,"
        "seen_again_24h,seen_again_48h,seen_again_7d,missed,false_positive,"
        "learning_value,outcome_score\n",
        encoding="utf-8",
    )
    candidates = [{
        "event_id": "today-event",
        "story_id": "today-story",
        "headline": "Today's event",
        "source": "Reuters",
        "category": "world",
        "importance": 80,
    }]
    result = evaluate_and_learn(root, candidates, "2026-10-07")
    assert result["evaluated"] == 0
    assert "today-event" not in (root / "news_learning.csv").read_text(encoding="utf-8")


def test_storage_and_analytics_contract(tmp_path):
    from app.analytics import build_report
    from app.storage import ensure_data, sync_sqlite

    ensure_data(tmp_path)
    db = sync_sqlite(tmp_path)
    assert db.exists()
    report = build_report(tmp_path)
    assert {"learning_samples", "source_reliability",
            "category_reliability", "outcome_horizon_coverage"} <= report.keys()


def test_telegram_chunks_preserve_content():
    from app.telegram import chunks

    payload = "line\n" * 5000
    parts = chunks(payload, 3800)
    assert parts
    assert "".join(parts).count("line") == payload.count("line")
    assert all(len(x) <= 3800 for x in parts)


def test_workflow_is_schedule_only_and_linked():
    workflow = yaml.safe_load(read(".github/workflows/morning_news.yml"))
    triggers = workflow.get(True) or workflow.get("on") or {}
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "push" not in triggers

    text = read(".github/workflows/morning_news.yml")
    assert "python -m compileall -q app" in text
    assert "python -m app.main" in text
    assert "actions/upload-artifact@v4" in text
    assert "git add data/" in text


def test_main_links_all_pipeline_layers():
    text = read("app/main.py")
    required = (
        "from .news import collect",
        "from .learning import evaluate_and_learn",
        "from .intelligence import enrich_trends",
        "from .research import research_stories",
        "from .ai import",
        "from .storage import",
        "from .analytics import",
        "from .telegram import send_text",
        "candidates=select_stories",
        "research=research_stories",
        "selected=rerank_stories",
        "result=generate_briefing",
        "sync_sqlite(DATA)",
        "report=write_reports(DATA)",
        "send_text(m)",
    )
    assert all(item in text for item in required)


def test_no_debug_or_secret_literals_in_application():
    forbidden = ("print('DEBUG')", 'print("DEBUG")', "TELEGRAM_BOT_TOKEN = '",
                 'TELEGRAM_BOT_TOKEN="', "api_key = '", 'api_key="')
    for path in (ROOT / "app").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden)
