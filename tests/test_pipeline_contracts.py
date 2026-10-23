from __future__ import annotations

"""Contract tests for the production news pipeline.

These tests intentionally stay deterministic: they validate module boundaries,
quality gates, persistence schema, and workflow wiring without network calls
or an Ollama model.
"""

import ast
from datetime import datetime, timezone
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



def test_category_research_is_bounded_and_only_targets_known_gaps():
    from app.research import _CATEGORY_QUERY_MAP

    assert set(_CATEGORY_QUERY_MAP) == {"economy", "defence"}
    assert len(_CATEGORY_QUERY_MAP["economy"]) >= 2
    assert len(_CATEGORY_QUERY_MAP["defence"]) >= 2


def test_category_research_uses_fresh_results_and_deduplicates(monkeypatch):
    from datetime import datetime, timezone
    from email.utils import format_datetime
    from types import SimpleNamespace
    import app.research as research

    now = datetime.now(timezone.utc)
    fresh = {
        "title": "RBI signals policy review as inflation eases - Example News",
        "link": "https://example.com/economy-story",
        "published": format_datetime(now),
        "published_parsed": now.utctimetuple(),
        "summary": "<p>Reserve Bank of India discusses inflation and policy.</p>",
        "source": {"title": "Example News"},
    }
    monkeypatch.setattr(research.requests, "get", lambda *a, **k: SimpleNamespace(
        content=b"feed", raise_for_status=lambda: None
    ))
    monkeypatch.setattr(research.feedparser, "parse", lambda _: SimpleNamespace(entries=[fresh]))
    articles, metrics = research.discover_category_articles(
        ["economy", "unknown"], max_queries=1, existing_articles=[]
    )
    assert metrics["queries"] == 1
    assert metrics["failed_queries"] == 0
    assert articles and articles[0]["category"] == "economy"
    assert articles[0]["region"] == "india"
    articles2, _ = research.discover_category_articles(
        ["economy"], max_queries=1,
        existing_articles=[{"url": "https://example.com/economy-story"}],
    )
    assert articles2 == []

def test_category_second_pass_targets_underfilled_categories():
    from app.main import _underfilled_research_categories

    initial = ["economy", "defence"]
    candidates = [
        {"category": "economy"},
        {"category": "economy"},
        {"category": "defence"},
        {"category": "business"},
    ]
    assert _underfilled_research_categories(initial, candidates, min_candidates=2) == ["defence"]
    assert _underfilled_research_categories(initial, [], min_candidates=2) == initial
    assert _underfilled_research_categories(initial, candidates, min_candidates=1) == []


def test_research_target_priority_favors_evidence_gaps():
    from app.main import _research_target_priority

    assert _research_target_priority({}, {
        "verification": "multi-source", "independent_sources": 2
    }) == 4
    assert _research_target_priority({}, {
        "verification": "official-source", "independent_sources": 0
    }) == 3
    assert _research_target_priority({}, {
        "verification": "multi-report", "independent_sources": 1
    }) == 2
    assert _research_target_priority({}, {
        "verification": "single-source", "independent_sources": 0
    }) == 1
    assert _research_target_priority({}, {
        "verification": "multi-source", "independent_sources": 2,
        "contradiction_flag": True
    }) == 0


def test_related_discovery_filters_stale_results_and_reports_supply_metrics(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    from types import SimpleNamespace
    import app.research as research

    now = datetime.now(timezone.utc)
    fresh = {
        "title": "Company launches new factory - Reuters",
        "link": "https://reuters.com/fresh-factory",
        "published": format_datetime(now),
        "published_parsed": now.utctimetuple(),
        "summary": "A fresh factory announcement.",
        "source": {"title": "Reuters"},
    }
    old_date = now - timedelta(days=5)
    stale = {
        "title": "Company launches old factory - BBC",
        "link": "https://bbc.com/old-factory",
        "published": format_datetime(old_date),
        "published_parsed": old_date.utctimetuple(),
        "summary": "An old factory announcement.",
        "source": {"title": "BBC"},
    }
    monkeypatch.setattr(research.requests, "get", lambda *a, **k: SimpleNamespace(
        content=b"feed", raise_for_status=lambda: None
    ))
    monkeypatch.setattr(research.feedparser, "parse", lambda _: SimpleNamespace(entries=[fresh, stale]))
    articles, metrics = research.discover_related_articles(
        [{"headline": "Company launches factory", "importance": 90, "region": "world"}],
        existing_articles=[], max_queries=1,
    )
    assert [article["url"] for article in articles] == ["https://reuters.com/fresh-factory"]
    assert metrics["articles_found"] == 1
    assert metrics["stale_skipped"] == 1
    assert metrics["unique_publishers"] == 1
    assert metrics["missing_timestamp"] == 0


def test_discovery_match_metrics_counts_unique_matched_urls():
    from app.main import _discovery_match_metrics

    discovered = [
        {"url": "https://reuters.com/story-a"},
        {"url": "https://bbc.com/story-b"},
        {"url": "https://bbc.com/story-b"},
    ]
    research = {
        "story-1": {"evidence": [{"url": "https://reuters.com/story-a"}]},
        "story-2": {"evidence": [
            {"url": "https://bbc.com/story-b"},
            {"url": "https://unrelated.com/story-c"},
        ]},
    }
    assert _discovery_match_metrics(discovered, research) == {
        "articles_found": 2, "matched_articles": 2, "match_rate": 1.0
    }
    assert _discovery_match_metrics([], research) == {
        "articles_found": 0, "matched_articles": 0, "match_rate": 0.0
    }


def test_research_target_selection_respects_budget_and_region_caps():
    from app.main import _select_research_targets

    candidates = [
        {"story_id": "strong", "headline": "Corroborated event", "importance": 99, "region": "world"},
        {"story_id": "weak", "headline": "Uncorroborated event", "importance": 70, "region": "world"},
        {"story_id": "india-weak", "headline": "Unverified India event", "importance": 71, "region": "india"},
    ]
    evidence = {
        "strong": {"verification": "multi-source", "independent_sources": 2},
        "weak": {"verification": "single-source", "independent_sources": 0},
        "india-weak": {"verification": "unverified", "independent_sources": 0},
    }
    empty, empty_regions, empty_priorities = _select_research_targets(
        candidates, evidence, query_limit=0, per_region_limit=1
    )
    assert empty == []
    assert empty_regions == {"india": 0, "world": 0}
    assert empty_priorities == {}

    targets, regions, priorities = _select_research_targets(
        candidates, evidence, query_limit=3, per_region_limit=1
    )
    assert [item["story_id"] for item in targets] == ["india-weak", "weak"]
    assert regions == {"india": 1, "world": 1}
    assert priorities == {"1": 2}


def test_research_discovery_respects_evidence_priority(monkeypatch):
    from types import SimpleNamespace
    import app.research as research

    queried = []
    def fake_get(url, **kwargs):
        queried.append(url)
        return SimpleNamespace(content=b"feed", raise_for_status=lambda: None)
    monkeypatch.setattr(research.requests, "get", fake_get)
    monkeypatch.setattr(research.feedparser, "parse", lambda _: SimpleNamespace(entries=[]))
    stories = [
        {"headline": "Already corroborated event", "importance": 99, "region": "world",
         "_research_priority": 4},
        {"headline": "Uncorroborated important event", "importance": 70, "region": "world",
         "_research_priority": 1},
    ]
    research.discover_related_articles(stories, [], max_queries=1)
    assert queried and "Uncorroborated%20important%20event" in queried[0]


def test_google_news_publisher_aliases_match_direct_domains():
    from app.research import _source_key, is_trusted_publisher

    wrapped = "https://news.google.com/rss/articles/opaque-id"
    assert _source_key("The Times of India", wrapped) == _source_key(
        "Times of India", "https://timesofindia.indiatimes.com/example"
    ) == "times of india"
    assert _source_key("The Indian Express", wrapped) == _source_key(
        "Indian Express", "https://indianexpress.com/example"
    ) == "indian express"
    assert _source_key("The Hindustan Times", wrapped) == _source_key(
        "Hindustan Times", "https://www.hindustantimes.com/example"
    ) == "hindustan times"
    assert is_trusted_publisher("The Times of India", wrapped)


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


def test_second_pass_corroboration_and_contradiction_fields():
    from app.research import verify_article
    published=datetime.now(timezone.utc).isoformat()
    story={"headline":"Company X launches emergency plant after fire","summary":"Company X launched a new plant after a fire disrupted output.","source":"Reuters","url":"https://reuters.com/x","published":published}
    evidence=[{"title":"Company X opens emergency plant following factory fire","summary":"Company X opened the emergency plant after the factory fire disrupted output.","source":"BBC","url":"https://bbc.com/x","published":published}]
    result=verify_article(story,evidence,[])
    assert result["independent_sources"]==1
    assert "contradiction_evidence" in result

def test_breaking_and_personalization_are_deterministic():
    from app.intelligence import breaking_score, personalize
    story={"headline":"Breaking: major earthquake hits India","summary":"Emergency response begins.","published":"2099-01-01T00:00:00+00:00","region":"india","category":"india","importance":70}
    assert breaking_score(story)>=50
    out=personalize([story],{"priority_categories":["india"],"preferred_regions":["india"],"category_weight":7,"region_weight":2,"breaking_weight":4,"emerging_weight":3})
    assert out and 77 <= out[0]["personalized_score"] <= 80
    assert out[0]["personalized_score"] < 100

def test_learning_exposes_source_reliability():
    from app.learning import _profile, apply_learning
    rows=[{"selected":"true","source":"Reuters","category":"world","outcome_score":"0.8"} for _ in range(5)]
    profile=_profile(rows)
    assert "source_reliability" in profile and "source_observations" in profile
    out=apply_learning([{"source":"Reuters","category":"world","importance":70}],profile)
    assert "source_reliability" in out[0]

def test_storage_and_analytics_contract(tmp_path):
    from app.analytics import build_report
    from app.storage import ensure_data, sync_sqlite

    ensure_data(tmp_path)
    db = sync_sqlite(tmp_path)
    assert db.exists()
    report = build_report(tmp_path)
    assert {"learning_samples", "source_reliability",
            "category_reliability", "outcome_horizon_coverage"} <= report.keys()


def test_backtest_and_quality_dashboard_contract(tmp_path):
    from app.analytics import backtest_learning, quality_dashboard
    from app.storage import ensure_data
    ensure_data(tmp_path)
    assert backtest_learning(tmp_path)["samples"] == 0
    dashboard=quality_dashboard(tmp_path)
    assert {"learning_samples","history_stories","daily_runs","horizon_coverage"} <= dashboard.keys()

def test_telegram_chunks_preserve_content():
    from app.telegram import chunks

    payload = "line\n" * 5000
    parts = chunks(payload, 3800)
    assert parts
    assert "".join(parts).count("line") == payload.count("line")
    assert all(len(x) <= 3800 for x in parts)


def test_single_main_workflow_separates_validation_from_production():
    workflow = yaml.safe_load(read(".github/workflows/news_intelligence.yml"))
    triggers = workflow.get(True) or workflow.get("on") or {}
    assert {"push", "pull_request", "workflow_dispatch", "schedule"} <= set(triggers)
    workflow_dir = ROOT / ".github" / "workflows"
    workflow_files = sorted(list(workflow_dir.glob("*.yml")) + list(workflow_dir.glob("*.yaml")))
    assert workflow_files == [workflow_dir / "news_intelligence.yml"]

    text = read(".github/workflows/news_intelligence.yml")
    assert "  validate:" in text and "  run-news:" in text
    assert "needs: validate" in text
    assert "github.event_name == 'schedule'" in text
    assert "inputs.mode == 'production'" in text
    assert "contents: write" in text
    assert "python -m compileall -q app" in text
    assert "python -m app.main" in text
    assert "actions/upload-artifact@v7" in text
    assert "NEWS_WORLD_TOP: '5'" in text
    assert "NEWS_CATEGORY_RESEARCH_QUERIES: '8'" in text
    assert 'assert "research_target_selection" in stats' in text
    assert 'assert "research_discovery" in stats' in text
    assert 'assert "research_verification" in stats' in text
    assert "NEWS_INDIA_TOP: '5'" in text
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
    selection = text.split("selected=rerank_stories(candidates,research)", 1)[1].split(
        "result=generate_briefing", 1
    )[0]
    assert "consolidate_event_families(selected)" not in selection
    assert "diversify_stories(selected" not in selection
    assert selection.lstrip().startswith("fast_lane=breaking_fast_lane(selected)")


def test_no_debug_or_secret_literals_in_application():
    forbidden = ("print('DEBUG')", 'print("DEBUG")', "TELEGRAM_BOT_TOKEN = '",
                 'TELEGRAM_BOT_TOKEN="', "api_key = '", 'api_key="')
    for path in (ROOT / "app").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden)


def test_telegram_output_v2_contract():
    from app.main import build_messages
    result={"top_stories":[
        {"story_id":"1","headline":"India event","importance":90,"region":"india","category":"india",
         "breaking_score":60,"verification":{"verification":"multi-source","confidence":95,"source_count":2},
         "what":"Something happened."},
        {"story_id":"2","headline":"World event","importance":80,"region":"world","category":"world",
         "breaking_score":0,"verification":{"verification":"single-source","confidence":75,"source_count":1},
         "what":"Something else happened."},
    ]}
    stats={"current_evidence":2,"total":2,"strong_verified":1,"contradictions":0,
           "source_ok":3,"source_total":3,"source_warnings":0,"source_failures":0,
           "candidates":10,"exact_duplicates":1,"semantic_filtered":2,
           "learning_labeled":100,"learning_success_rate":0.8,"learning_miss_rate":0.1,
           "learning_fp_rate":0.1,"ai_generated":1,"ai_fallback":1,"health":"PASS",
           "runtime":"1.2s","research_verification":{"independent_source_coverage":0.25,
               "duplicate_reporting_copies_excluded":7},
           "research_target_selection":{"selected":12,"zero_independent_candidates":18},
           "analytics":{"last_7_days":{"runs":5,"avg_success_rate":0.75,"avg_miss_rate":0.12}}}
    messages=build_messages(result,"2026-10-07",stats,[])
    payload="\n".join(messages)
    assert "EXECUTIVE SUMMARY" in payload
    assert "QUALITY & VERIFICATION" in payload
    assert "LEARNING PERFORMANCE" in payload
    assert "INDIA" in payload and "WORLD" in payload
    assert "DETAILED STORIES" in payload
    assert "STRONG" in payload and "SINGLE SOURCE" in payload
    assert "Independent-source coverage 25%" in payload
    assert "Near-identical syndicated copies excluded 7" in payload
    assert "research targets 12" in payload and "zero-independent candidates 18" in payload


def test_quality_intelligence_v2_contract(tmp_path):
    from app.quality import prepare_candidates, coverage_gaps, source_health, quality_snapshot, coverage_plan
    rows=[{"headline":"India economy update","category":"india","source":"Reuters","importance":80,"story_id":"1"}]
    out=prepare_candidates(rows,[])
    assert out and "novelty_score" in out[0] and "event_momentum" in out[0]
    assert isinstance(coverage_gaps(out),list)
    plan=coverage_plan(out,world_target=5,india_target=5)
    assert {"world_target","india_target","world_shortfall","india_shortfall"} <= plan.keys()
    assert source_health(out)["reuters"]["articles"]==1
    snap=quality_snapshot(out,{"1":{"verification":"multi-source","contradiction_flag":False}})
    assert snap["strong"]==1

def test_backtest_v2_contract(tmp_path):
    from app.analytics import backtest_learning_v2, build_report, calibrate_learning_threshold, calibrate_learning_threshold
    from app.storage import ensure_data
    ensure_data(tmp_path)
    result=backtest_learning_v2(tmp_path)
    assert {"samples","precision","recall","f1","hit_rate","mae","buckets"} <= result.keys()
    calibration=calibrate_learning_threshold(tmp_path)
    assert {"threshold","precision","recall","f1","samples"} <= calibration.keys()

def test_evidence_corroboration_rejects_shared_geography_only():
    from app.ai import _corroboration_score

    sanctions = "Two Mumbai-based firms, five Indian nationals face U.S. sanctions over Iran oil trade"
    unrelated_iran = "Femicide in Iran: When honor becomes a death sentence"
    unrelated_india = "India protesters defy government crackdown over voting rights"
    corroborating = "US sanctions firms over Iran oil trade network"

    assert _corroboration_score(sanctions, unrelated_iran) == 0.0
    assert _corroboration_score(sanctions, unrelated_india) == 0.0
    assert _corroboration_score(sanctions, corroborating) >= 0.55


def test_unrelated_unclustered_stories_keep_distinct_event_families():
    from app.ai import rerank_stories
    from app.advanced import consolidate_event_families

    stories = [
        {"story_id": "ecb-rate", "event_id": "ecb-rate", "headline": "European Central Bank cuts benchmark interest rate by quarter point",
         "importance": 92, "region": "world", "region_confidence": 1.0, "source": "Reuters",
         "url": "https://example.com/ecb-rate", "category": "business"},
        {"story_id": "lunar-mission", "event_id": "lunar-mission", "headline": "Japan launches new lunar exploration mission after successful rocket test",
         "importance": 90, "region": "world", "region_confidence": 1.0, "source": "BBC",
         "url": "https://example.com/lunar-mission", "category": "science"},
    ]
    research = {
        "ecb-rate": {"verification": "multi-source", "confidence": 95, "independent_sources": 2,
                     "primary_fresh": True, "primary_derivative": False},
        "lunar-mission": {"verification": "multi-source", "confidence": 93, "independent_sources": 2,
                          "primary_fresh": True, "primary_derivative": False},
    }

    selected = rerank_stories(stories, research)
    assert len(selected) == 2
    assert len({story["event_family"] for story in selected}) == 2
    assert len(consolidate_event_families(selected)) == 2


def test_advanced_intelligence_v3_contract(tmp_path):
    from app.advanced import adaptive_threshold,diversify_stories,learning_v3_snapshot,source_fallback_plan,breaking_fast_lane,calibrate_confidence,adaptive_personalization
    threshold=adaptive_threshold({"threshold":72})
    assert threshold==72
    stories=[
        {"story_id":"i1","event_id":"e1","region":"india","source":"A","importance":90,"ranking_score":90},
        {"story_id":"w1","event_id":"e2","region":"world","source":"B","importance":89,"ranking_score":89},
        {"story_id":"w2","event_id":"e3","region":"world","source":"C","importance":88,"ranking_score":88},
    ]
    out=diversify_stories(stories,max_total=3,india_target=1,world_target=2,max_per_source=2)
    assert len(out)==3 and sum(x["region"]=="world" for x in out)==2
    snap=learning_v3_snapshot([{"selected":"true","outcome_score":"0.8","false_positive":"false"}])
    assert snap["hit_rate"]==1.0
    assert source_fallback_plan({"weak":{"quality_rate":0.1}})["fallback_required"]
    assert breaking_fast_lane([{"breaking_score":80}])
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":80,"verification":"multi-source","independent_sources":2}})==80
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":99,"verification":"multi-source","independent_sources":4}})==95
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":92,"verification":"multi-source","primary_fresh":False}})==60
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":92,"verification":"multi-source","contradiction_flag":True}})==50
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":55,"verification":"single-source"}})==55
    assert adaptive_personalization({"category_weight":6},{"hit_rate":0.8})["category_weight"]==7

def test_backtest_v3_contract(tmp_path):
    from app.analytics import backtest_learning_v3
    from app.storage import ensure_data
    ensure_data(tmp_path)
    result=backtest_learning_v3(tmp_path)
    assert {"samples","hit_rate","precision","recall","f1","mae","temporal_stability"} <= result.keys()

def test_main_wires_advanced_v3():
    text=read("app/main.py")
    for item in ("apply_adaptive_threshold","learning_v3_snapshot","source_fallback_plan",
                 "breaking_fast_lane","calibrate_confidence","backtest_learning_v3"):
        assert item in text
    # Diversity/family consolidation is intentionally not applied a second time
    # after rerank_stories, because that can drop stories without regional backfill.
    advanced=read("app/advanced.py")
    assert "def diversify_stories(" in advanced
    assert "def consolidate_event_families(" in advanced
    selection=text.split("selected=rerank_stories(candidates,research)",1)[1].split(
        "result=generate_briefing",1
    )[0]
    assert "diversify_stories(selected" not in selection
    assert "consolidate_event_families(selected)" not in selection


def test_ops_and_final_audit_contract():
    from app.ops import confidence_snapshot,historical_trend,operational_health,final_audit
    stories=[{"region":"india","breaking_score":60,"calibrated_confidence":90,"verification":{"confidence":80}},
             {"region":"world","breaking_score":0,"calibrated_confidence":70,"verification":{"confidence":65}}]
    assert confidence_snapshot(stories)["high_confidence"]==1
    assert historical_trend([{"date":"2026-10-07","region":"world","event_status":"CONFIRMED"}], as_of="2026-10-07")["stories"]==1
    stats={"source_failures":0,"source_warnings":0,"current_evidence":2,"total":2,"data_quality":{"ok":True},"db_path":"data/news_knowledge.db","learning_labeled":10}
    assert operational_health(stats)["status"]=="PASS"
    assert final_audit(stats,stories)["world"]==1

def test_confidence_calibration_is_exposed():
    text=read("app/main.py")
    assert "calibrated_confidence" in text
    assert "confidence_snapshot" in text
    assert "final_audit" in text


def test_production_v4_feedback_and_monitoring(tmp_path):
    from app.production import time_series_backtest, feedback_snapshot, feedback_adjustment, monitoring_alerts
    from app.storage import ensure_data, append_rows, HEADERS
    ensure_data(tmp_path)
    rows=[]
    for i in range(45):
        rows.append({"run_date":f"2026-09-{(i%30)+1:02d}","initial_score":70 if i%2 else 40,"outcome_score":1 if i%3 else 0})
    result=time_series_backtest(rows,minimum_train=20,test_window=10)
    assert result["leakage_safe"] is True
    assert result["folds"] >= 2
    assert {"precision","recall","f1","mae","stability"} <= result.keys()
    append_rows(tmp_path/"news_feedback.csv",[{"date":"2026-10-07","story_id":"s1","event_id":"e1","feedback":"useful","note":""}],HEADERS["news_feedback.csv"])
    snap=feedback_snapshot(tmp_path)
    assert snap["useful"]==1
    assert feedback_adjustment(snap)["ranking_delta"] > 0
    alerts=monitoring_alerts({"source_failures":0,"source_warnings":0,"stories":5,"world_stories":5,"world_target":5,"india_stories":5,"india_target":5,"health":"PASS"})
    assert alerts == []


def test_operational_trend_uses_closed_calendar_window():
    from app.ops import historical_trend
    result=historical_trend([
        {"date":"2026-09-30","region":"world"},
        {"date":"2026-10-07","region":"world"},
        {"date":"2026-10-08","region":"india"},
        {"date":"2099-01-01","region":"india"},
    ],days=7,as_of="2026-10-07")
    assert result["stories"] == 1
    assert result["regions"] == {"world": 1}


def test_feedback_schema_and_production_wiring():
    text=read("app/main.py")
    assert "time_series_backtest" in text
    assert "feedback_snapshot" in text
    assert "monitoring_alerts" in text
    storage=read("app/storage.py")
    assert "news_feedback.csv" in storage


def test_intelligence_v4_contract(tmp_path):
    from app.intelligence_v4 import (
        diagnose_learning, time_bucket_metrics, event_level_metrics,
        calibration_v2, source_category_profile, apply_intelligence_v4,
        feedback_learning, walk_forward_optimization, compare_strategies,
        production_decision, calibrated_score,
    )
    rows=[]
    for i in range(120):
        rows.append({
            "run_date": f"2026-09-{(i % 30) + 1:02d}",
            "event_id": f"e{i//2}",
            "story_id": f"s{i}",
            "source": "A" if i % 2 else "B",
            "category": "india" if i % 3 else "economy",
            "initial_score": 80 if i % 4 else 45,
            "selected": "true" if i % 3 else "false",
            "outcome_score": "0.8" if i % 5 else "0.1",
        })
    diagnosis=diagnose_learning(rows, "2026-10-07")
    assert diagnosis["samples"] == 120
    assert "positive_rate" in diagnosis
    assert time_bucket_metrics(rows, "2026-10-07")
    event=event_level_metrics(rows, "2026-10-07")
    assert event["events"] < 120
    cal=calibration_v2(rows, "2026-10-07")
    profile=source_category_profile(rows, "2026-10-07")
    ranked=apply_intelligence_v4([{"story_id":"x","source":"A","category":"india","importance":80,"personalized_score":80}], profile, cal)
    assert ranked and "calibrated_intelligence_score" in ranked[0]
    feedback=feedback_learning(rows,[{"story_id":"x","feedback":"useful"}],"2026-10-07")
    assert feedback["bounded_delta"] > 0
    wf=walk_forward_optimization(rows, minimum_train=40, test_window=20)
    assert wf["leakage_safe"] is True and wf["folds"] >= 2
    comparison=compare_strategies(rows)
    assert comparison["status"] in {"PROMOTE","SHADOW"}
    assert production_decision(comparison)["status"] in {"PROMOTE","HOLD"}
    assert 0 <= calibrated_score(80, cal) <= 100


def test_intelligence_v4_production_wiring():
    text=read("app/main.py")
    for item in (
        "diagnose_learning","time_bucket_metrics","event_level_metrics",
        "calibration_v2","source_category_profile","apply_intelligence_v4",
        "feedback_learning","walk_forward_optimization","compare_strategies",
        "production_decision","intelligence_v4_diagnosis","strategy_comparison",
    ):
        assert item in text


def test_intelligence_v5_contract():
    from app.intelligence_v5 import intelligence_v5, classify_impact, event_momentum, similar_events
    stories=[{"headline":"India announces major investment deal","summary":"growth and investment","source":"A","source_count":3,"verification_level":"multi-source"}]
    history=[{"headline":"India investment deal","run_date":"2026-09-01","outcome_score":0.8}]
    v=intelligence_v5(stories,history,{"health":"PASS"})
    assert v["stories"] and "impact" in v["stories"][0]
    assert v["stories"][0]["impact"]["level"] in {"HIGH","MEDIUM","LOW"}
    assert "entities" in v and "scorecard" in v
    assert "research_queue" in v and "cross_event_links" in v


def test_intelligence_v5_plus_steps_10_25():
    from app.intelligence_v5_plus import run_v5_plus, answer_news_question, research_report
    stories=[{"headline":"India announces major investment deal","summary":"growth and investment","source":"Reuters","category":"economy","importance":82,"source_count":3,"verification_level":"multi-source","breaking_score":80}]
    history=[{"headline":"India investment deal","run_date":"2026-09-01","category":"economy","outcome_score":0.8,"source":"Reuters"}]
    learning=[{"outcome_score":"0.8","impact_level":"HIGH"}]
    feedback=[{"feedback":"positive"},{"feedback":"negative"}]
    prefs={"topics":["economy"]}
    v=run_v5_plus(stories,history,learning,feedback,prefs,{"health":"PASS"})
    for k in ("entities","entity_profiles","clusters","event_evolution","impact_learning","market_correlation","source_reliability","feedback","scorecard","personalized_feed","alerts","trend_report","knowledge_graph","contradictions","evidence_gaps","research_queue","weekly_report"):
        assert k in v
    assert v["clusters"] and v["entity_profiles"]
    assert answer_news_question("investment deal",v["stories"],history)["stories"]
    assert "sections" in research_report(v["stories"],v["research_queue"])


def test_phase1_v5_accuracy_calibration_and_utc_contracts():
    from app.production_v5 import walk_forward_v5, shadow_ab_test, calibration_monitor, calibrate_confidence
    from app.intelligence_v5_plus import research_report
    rows=[]
    for i in range(180):
        rows.append({
            "run_date": f"2026-09-{(i % 30) + 1:02d}",
            "initial_score": 85 if i % 4 else 35,
            "source": "Trusted" if i % 3 else "Unknown",
            "category": "economy" if i % 2 else "world",
            "outcome_score": "0.9" if (i % 5) else "0.1",
        })
    wf=walk_forward_v5(rows,train_min=60,test_window=20)
    ab=shadow_ab_test(rows,rows,train_min=60,test_window=20)
    assert wf["leakage_safe"] is True and wf["feature_learning"] is True
    assert len(ab["baseline_v4"]["folds"])==len(ab["candidate_v5"]["folds"])
    assert "f1_confidence_interval" in ab and "precision_confidence_interval" in ab
    cal=calibration_monitor(rows)
    assert {"ece","brier","status"} <= cal.keys()
    assert 0 <= calibrate_confidence(80,rows) <= 100
    assert "datetime.utcnow" not in read("app/intelligence_v5_plus.py")


def test_phase2_4_intelligence_layers():
    from app.intelligence_v5_plus import personalized_feed, autonomous_research, news_market_correlation
    prefs={"priority_categories":["economy"],"preferred_regions":["india"]}
    published=datetime.now(timezone.utc).isoformat()
    stories=[{"headline":"India economy update: RBI announced rate cut","summary":"RBI announced a rate cut, affecting India's economy.","category":"economy","region":"india","importance":70,"impact":{"score":80},"source":"The Hindu","url":"https://thehindu.com/primary","published":published}]
    feed=personalized_feed(stories,prefs)
    assert feed and feed[0]["preference_matches"]>=2
    evidence=[{"title":"RBI announced rate cut as India economy update confirmed","source":"Reuters","url":"https://reuters.com/x","published":published}]
    queue=autonomous_research(stories,evidence_pool=evidence)
    assert queue and queue[0]["evidence_count"]>=1
    market=[{"symbol":"NIFTY 50","status":"OK","change_pct":0.8}]
    corr=news_market_correlation(stories,market)
    assert corr and corr[0]["market_context_pct"]==0.8


def test_knowledge_storage_contract():
    from app.storage import HEADERS, ensure_data
    import tempfile
    from pathlib import Path
    root=Path(tempfile.mkdtemp())
    ensure_data(root)
    assert (root/"knowledge_daily.csv").exists()
    assert (root/"knowledge_weekly.csv").exists()
    assert "research_items" in HEADERS["knowledge_daily.csv"]


def test_production_v5_gate_27_40():
    from app.production_v5 import walk_forward_v5, shadow_ab_test, calibration_monitor, drift_monitor, contradiction_and_evidence, followup_research_plan, autonomous_research_agent, generate_research_reports
    rows=[{"initial_score":70,"outcome_score":0.8,"category":"economy"}]*150
    wf=walk_forward_v5(rows,train_min=60,test_window=20)
    assert wf["leakage_safe"] is True
    assert "f1" in wf
    assert wf["feature_learning"] is True
    assert "precision" in wf and "recall" in wf
    assert "delta_f1" in shadow_ab_test(rows,rows)
    cal=calibration_monitor(rows)
    assert cal["samples"]==cal["holdout_samples"] and cal["holdout_samples"]>=20
    assert drift_monitor(rows,rows)["status"]=="STABLE"
    assert {"contradictions","evidence_gaps"} <= set(contradiction_and_evidence([]))
    q=autonomous_research_agent([{"headline":"Test","priority":80}],rows)
    assert generate_research_reports(q)
    assert followup_research_plan([{"headline":"Test","impact":{"score":80}}])[0]["priority"]==80

def test_phase_2_to_4_plus_production_hardening(tmp_path):
    from app.intelligence_v5_plus import autonomous_research, weekly_report
    from app.production_v5 import production_quality_gate
    published=datetime.now(timezone.utc).isoformat()
    queue=autonomous_research([{"headline":"India market investment follows RBI rate cut announced","summary":"RBI announced a rate cut affecting investment markets in India.","source":"The Hindu","url":"https://thehindu.com/market-primary","published":published,"impact":{"score":80},"momentum_score":20}],
                              evidence_pool=[{"title":"RBI announced rate cut; India market investment confirmed","source":"Reuters","url":"https://reuters.com/market-followup","published":published}])
    assert queue and queue[0]["evidence_count"] >= 1
    report=weekly_report([{"headline":"India market investment","importance":80}],[])
    assert "top_entities" in report and isinstance(report["top_entities"],list)
    gate=production_quality_gate({"paired_folds":2},{"samples":10,"ece":0.05},{"status":"STABLE"},{"contradictions":[],"evidence_gaps":[]})
    assert gate["status"]=="HOLD"
    assert "insufficient_paired_folds" in gate["blockers"]

def test_knowledge_daily_is_unique_by_date(tmp_path):
    from app.storage import ensure_data, read_rows, replace_rows, HEADERS
    ensure_data(tmp_path)
    path=tmp_path/"knowledge_daily.csv"
    rows=[{"date":"2026-10-07","stories":1,"high_impact":1,"new_events":1,"developing_events":0,"confirmed_events":0,"contradictions":0,"research_items":1},
          {"date":"2026-10-07","stories":2,"high_impact":1,"new_events":0,"developing_events":1,"confirmed_events":0,"contradictions":0,"research_items":2}]
    replace_rows(path,[rows[-1]],HEADERS["knowledge_daily.csv"])
    assert len([r for r in read_rows(path) if r["date"]=="2026-10-07"])==1

def test_provisional_outcomes_are_excluded_from_training(tmp_path):
    from app.storage import HEADERS, append_rows, ensure_data, outcome_is_mature, read_rows
    from app.analytics import backtest_learning_v2, build_report, calibrate_learning_threshold
    from app.learning import _profile, learning_metrics
    from app.production import time_series_backtest
    from app.production_v5 import walk_forward_v5, calibration_monitor
    from app.intelligence_v4 import diagnose_learning
    from app.advanced import learning_v3_snapshot
    from app.intelligence_v5_plus import impact_outcome_learning

    ensure_data(tmp_path)
    provisional={"run_date":"2026-10-10","event_id":"provisional","story_id":"p","source":"Noisy","category":"world",
                 "initial_score":"90","selected":"true","seen_again_7d":"","learning_value":"1.00","outcome_score":"1.00"}
    mature={"run_date":"2026-10-01","event_id":"mature","story_id":"m","source":"Trusted","category":"india",
            "initial_score":"80","selected":"true","seen_again_7d":"1","learning_value":"0.80","outcome_score":"0.80"}
    assert not outcome_is_mature(provisional)
    assert outcome_is_mature(mature)
    append_rows(tmp_path/"news_learning.csv",[provisional,mature],HEADERS["news_learning.csv"])
    rows=read_rows(tmp_path/"news_learning.csv")
    assert backtest_learning_v2(tmp_path)["samples"] == 1
    assert build_report(tmp_path)["mature_outcome_samples"] == 1
    assert calibrate_learning_threshold(tmp_path)["samples"] == 1
    assert _profile(rows)["source_observations"] == {"Trusted":1}
    assert learning_metrics(rows)["evaluated"] == 1
    assert time_series_backtest(rows,minimum_train=1)["samples"] == 1
    assert walk_forward_v5(rows,train_min=1)["samples"] == 1
    assert calibration_monitor(rows)["samples"] == 1
    assert diagnose_learning(rows,today="2026-10-17")["samples"] == 1
    assert learning_v3_snapshot(rows)["samples"] == 1
    assert impact_outcome_learning([],rows)["samples"] == 1


def test_phase3_5_learning_audit_and_chronological_evaluation(tmp_path):
    from app.analytics import build_report, chronological_ranking_evaluation, learning_data_audit
    from app.storage import HEADERS, append_rows, ensure_data

    ensure_data(tmp_path)
    rows=[]
    for i in range(40):
        day=f"2026-09-{(i // 2) + 1:02d}"
        rows.append({
            "run_date":day,"event_id":f"event-{i}","story_id":f"story-{i}",
            "source":"Trusted" if i % 2 else "Other",
            "category":"business" if i % 3 else "india",
            "initial_score":85 if i % 4 else 55,
            "selected":"true" if i % 3 else "false",
            "seen_again_7d":"1" if i % 4 else "0",
            "outcome_score":"0.8" if i % 4 else "0.1",
            "learning_value":"0.8" if i % 4 else "0.1",
        })
    append_rows(tmp_path/"news_learning.csv",rows,HEADERS["news_learning.csv"])
    audit=learning_data_audit(tmp_path)
    assert audit["total_rows"]==40 and audit["mature_rows"]==40
    evaluation=chronological_ranking_evaluation(tmp_path)
    assert evaluation["status"]=="OK"
    assert evaluation["leakage_safe"] is True
    assert evaluation["train_dates"] < 20
    report=build_report(tmp_path)
    assert "learning_data_audit" in report
    assert "chronological_ranking_evaluation" in report


def test_guardrails_use_non_overlapping_windows_and_fail_closed():
    from app.guardrails import temporal_drift_windows, production_readiness_gate, coverage_audit
    from app.production_v5 import drift_monitor, calibration_monitor
    rows=[]
    for day in range(1,121):
        month=1+(day-1)//28; dom=1+(day-1)%28
        for j in range(2):
            rows.append({"run_date":f"2026-{month:02d}-{dom:02d}","category":"india" if day%3 else "world","outcome_score":"0.8","seen_again_7d":"1","initial_score":"70"})
    windows=temporal_drift_windows(rows,current_days=30,baseline_days=60)
    assert windows["current"] and windows["baseline"]
    assert not ({id(x) for x in windows["current"]} & {id(x) for x in windows["baseline"]})
    assert drift_monitor(windows["current"],windows["baseline"])["status"] in {"STABLE","DRIFT"}
    cal=calibration_monitor(rows)
    assert cal["leakage_safe"] is True and cal["holdout_samples"]>=20
    gate=production_readiness_gate({"paired_folds":1,"promote":False},cal,{"status":"UNKNOWN"},{"stories":0})
    assert gate["status"]=="HOLD" and "insufficient_paired_folds" in gate["blockers"]
    assert coverage_audit([{"region":"india"}],5,5)["world_shortfall"]==5

def test_evidence_audit_recognizes_nested_independent_sources():
    from app.production_v5 import contradiction_and_evidence, production_quality_gate
    stories=[{"headline":"Verified event","source":"Reuters","url":"https://reuters.com/a","summary":"A verified summary","verification":{"verification":"multi-source","independent_sources":2,"evidence":[{"source":"BBC"},{"source":"AP"}]}}]
    audit=contradiction_and_evidence(stories)
    assert audit["evidence_gaps"]==[] and audit["corroborated"]==1
    assert production_quality_gate({"paired_folds":0},{"samples":0,"ece":None},{"status":"UNKNOWN"},audit)["status"]=="HOLD"

def test_single_main_workflow_guards_production_triggers():
    workflow=yaml.safe_load(read(".github/workflows/news_intelligence.yml"))
    triggers=workflow.get(True) or workflow.get("on") or {}
    assert {"push","pull_request","workflow_dispatch","schedule"} <= set(triggers)
    text=read(".github/workflows/news_intelligence.yml")
    assert "needs: validate" in text
    assert "inputs.mode == 'production'" in text
    assert "actions/upload-artifact@v7" in text
    assert len(list((ROOT / ".github" / "workflows").glob("*.yml")))==1


def test_research_verification_rejects_unrelated_same_topic_articles():
    from app.research import verify_article

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "Two Mumbai-based firms, five Indian nationals face U.S. sanctions over Iran oil trade",
        "summary": "The United States announced sanctions on firms accused of facilitating Iranian oil trade.",
        "source": "The Hindu",
        "url": "https://thehindu.com/example-primary-story",
        "published": now,
    }
    unrelated = [
        {
            "title": "Femicide in Iran: When honor becomes a death sentence",
            "summary": "A report about violence against women and honor killings in Iran.",
            "source": "Deutsche Welle",
            "url": "https://dw.com/example-iran-femicide",
            "published": now,
        },
        {
            "title": "India protesters defy government crackdown over voting rights",
            "summary": "Protesters challenged a government crackdown during a demonstration.",
            "source": "The Guardian",
            "url": "https://theguardian.com/example-india-protest",
            "published": now,
        },
    ]
    result = verify_article(story, unrelated)
    assert result["independent_sources"] == 0
    assert result["evidence"] == []
    assert result["verification"] == "single-source"

    corroborating = {
        "title": "US sanctions firms over Iran oil trade network",
        "summary": "Officials announced sanctions against firms accused of facilitating Iranian oil exports.",
        "source": "Reuters",
        "url": "https://reuters.com/example-iran-oil-sanctions",
        "published": now,
    }
    result = verify_article(story, unrelated + [corroborating])
    assert result["independent_sources"] == 1
    assert [row["source"] for row in result["evidence"]] == ["Reuters"]


def test_research_queue_uses_event_matched_independent_evidence():
    from app.intelligence_v5_plus import autonomous_research

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "Two Mumbai-based firms face U.S. sanctions over Iran oil trade",
        "summary": "The United States sanctioned firms accused of facilitating Iranian oil exports.",
        "source": "The Hindu",
        "url": "https://www.thehindu.com/example-primary",
        "published": now,
        "impact": {"score": 90},
        "momentum_score": 0,
    }
    unrelated = {
        "title": "Femicide in Iran: When honor becomes a death sentence",
        "summary": "A report about violence against women in Iran.",
        "source": "Deutsche Welle",
        "url": "https://www.dw.com/example-femicide",
        "published": now,
    }
    reuters = {
        "title": "US sanctions firms over Iran oil trade network",
        "summary": "Officials announced sanctions against firms accused of facilitating Iranian oil exports.",
        "source": "Reuters",
        "url": "https://www.reuters.com/world/example-sanctions",
        "published": now,
    }
    bbc = {
        "title": "Iran oil trade: US sanctions target firms accused of helping exports",
        "summary": "The United States announced sanctions on firms over Iranian oil exports.",
        "source": "BBC",
        "url": "https://www.bbc.com/news/example-sanctions",
        "published": now,
    }

    result = autonomous_research([story], evidence_pool=[unrelated])[0]
    assert result["independent_source_count"] == 0
    assert result["research_status"] == "RESEARCH_REQUIRED"
    assert result["retrieved_evidence"] == []

    result = autonomous_research([story], evidence_pool=[unrelated, reuters, bbc])[0]
    assert result["independent_source_count"] == 2
    assert result["research_status"] == "CORROBORATED"
    assert {row["source"] for row in result["retrieved_evidence"]} == {"Reuters", "BBC"}


def test_research_queue_does_not_complete_with_stale_primary_or_duplicate_publisher():
    from app.intelligence_v5_plus import autonomous_research

    now = datetime.now(timezone.utc).isoformat()
    old = "2020-01-01T00:00:00+00:00"
    story = {
        "headline": "US sanctions firms over Iran oil trade network",
        "summary": "The United States announced sanctions over Iranian oil exports.",
        "source": "Reuters",
        "url": "https://www.reuters.com/example-primary",
        "published": old,
        "impact": {"score": 90},
        "momentum_score": 0,
    }
    same_publisher = [
        {
            "title": "US sanctions firms over Iran oil trade network",
            "summary": "The United States announced sanctions over Iranian oil exports.",
            "source": "Reuters",
            "url": "https://www.reuters.com/example-followup",
            "published": now,
        },
        {
            "title": "Iran oil trade: US sanctions target firms accused of helping exports",
            "summary": "The United States announced sanctions over Iranian oil exports.",
            "source": "Reuters",
            "url": "https://www.reuters.com/example-second-followup",
            "published": now,
        },
    ]
    result = autonomous_research([story], evidence_pool=same_publisher)[0]
    assert result["independent_source_count"] <= 1
    assert result["research_status"] != "CORROBORATED"


def test_research_report_status_is_not_hardcoded_to_queued():
    from app.production_v5 import generate_research_reports

    reports = generate_research_reports([
        {"headline": "A", "priority": 90, "research_status": "CORROBORATED", "independent_source_count": 2, "evidence_count": 2},
        {"headline": "B", "priority": 80, "research_status": "RESEARCH_REQUIRED", "independent_source_count": 0, "evidence_count": 0},
    ])
    assert [row["status"] for row in reports] == ["CORROBORATED", "RESEARCH_REQUIRED"]
    assert reports[0]["actions"] != reports[1]["actions"]


def test_telegram_chunks_split_oversized_single_lines():
    from app.telegram import chunks

    payload = "<b>" + ("longheadline " * 900) + "</b>"
    parts = chunks(payload, 1200)
    assert len(parts) > 1
    assert all(len(part) <= 1200 for part in parts)
    assert all(part.startswith("<b>") and part.endswith("</b>") for part in parts)
    assert sum(part.count("longheadline") for part in parts) == 900


def test_diversification_source_limit_uses_canonical_publisher_domain():
    from app.advanced import diversify_stories

    stories = [
        {"story_id": "r1", "event_id": "e1", "region": "india", "source": "Reuters India", "url": "https://www.reuters.com/world/a", "importance": 99},
        {"story_id": "r2", "event_id": "e2", "region": "india", "source": "Reuters", "url": "https://reuters.com/world/b", "importance": 98},
        {"story_id": "b1", "event_id": "e3", "region": "world", "source": "BBC News", "url": "https://www.bbc.com/news/c", "importance": 97},
    ]
    result = diversify_stories(stories, max_total=3, india_target=2, world_target=1, max_per_source=1)
    assert len(result) == 2
    assert sum("reuters.com" in row["url"] for row in result) == 1
    assert sum("bbc.com" in row["url"] for row in result) == 1

def test_v5_scorecard_reads_nested_verification_and_source_counts():
    from app.intelligence_v5_plus import missing_evidence, scorecard

    stories = [
        {
            "headline": "Corroborated event",
            "source": "Reuters",
            "url": "https://reuters.com/story",
            "summary": "A specific event summary.",
            "verification": {
                "verification": "multi-source",
                "independent_sources": 2,
                "source_count": 3,
                "evidence": [{"source": "BBC"}],
            },
        },
        {
            "headline": "Single-source event",
            "source": "AP",
            "url": "https://apnews.com/story",
            "summary": "Another event summary.",
            "verification": {
                "verification": "single-source",
                "source_count": 1,
                "independent_sources": 0,
            },
        },
    ]
    assert scorecard(stories, {"health": "PASS"})["verified"] == 1
    assert missing_evidence(stories) == []


def test_final_audit_does_not_hide_evidence_or_coverage_gaps(tmp_path):
    from app.ops import final_audit

    stats = {
        "source_failures": 0,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(tmp_path / "news_knowledge.db"),
        "learning_labeled": 0,
        "v5_production_evaluation": {
            "evidence": {"stories": 2, "evidence_gap_rate": 0.5}
        },
        "regional_coverage_audit": {
            "india_shortfall": 1,
            "world_shortfall": 0,
        },
        "v5_quality_gate": {"status": "HOLD"},
    }
    (tmp_path / "news_knowledge.db").touch()
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert result["checks"]["evidence"] is False
    assert result["checks"]["regional_coverage"] is False
    assert set(result["blockers"]) == {
        "evidence_gaps",
        "regional_coverage_shortfall",
        "production_quality_gate_hold",
        "research_incomplete",
    }
    assert result["production_quality_gate"] == "HOLD"

def test_final_audit_surfaces_non_evidence_production_gate_blockers(tmp_path):
    from app.ops import final_audit

    db = tmp_path / "news_knowledge.db"
    db.touch()
    stats = {
        "source_failures": 0,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(db),
        "learning_labeled": 0,
        "v5_production_evaluation": {
            "evidence": {"stories": 2, "evidence_gap_rate": 0.0}
        },
        "regional_coverage_audit": {
            "india_shortfall": 0,
            "world_shortfall": 0,
        },
        "v5_quality_gate": {
            "status": "HOLD",
            "blockers": ["ranking_improvement_not_proven", "poor_calibration"],
        },
    }
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert result["checks"]["production_quality_gate"] is False
    assert set(result["blockers"]) == {
        "ranking_improvement_not_proven", "poor_calibration", "research_incomplete"
    }


def test_append_rows_preserves_records_with_atomic_replacement(tmp_path):
    from app.storage import append_rows, read_rows

    path = tmp_path / "history.csv"
    fields = ["date", "story_id"]
    append_rows(path, [{"date": "2026-10-16", "story_id": "old"}], fields)
    append_rows(path, [{"date": "2026-10-17", "story_id": "new"}], fields)
    assert read_rows(path) == [
        {"date": "2026-10-16", "story_id": "old"},
        {"date": "2026-10-17", "story_id": "new"},
    ]
    assert not path.with_name(".history.csv.tmp").exists()

def test_restore_source_metadata_preserves_real_publication_time():
    from app.main import _restore_source_metadata

    stories = [
        {"story_id": "fresh", "url": "https://example.com/fresh", "headline": "Fresh story"},
        {"story_id": "unknown", "url": "https://example.com/unknown", "headline": "No feed match"},
    ]
    articles = [
        {
            "url": "https://example.com/fresh",
            "source": "Example News",
            "published": "2026-10-18T03:00:00+00:00",
        }
    ]

    result = _restore_source_metadata(stories, articles)
    assert result[0]["published"] == "2026-10-18T03:00:00+00:00"
    assert result[0]["source"] == "Example News"
    assert "published" not in result[1]

def test_final_audit_blocks_hold_status_without_explicit_blockers(tmp_path):
    from app.ops import final_audit

    db = tmp_path / "news_knowledge.db"
    db.touch()
    stats = {
        "source_failures": 0,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(db),
        "learning_labeled": 10,
        "v5_production_evaluation": {
            "evidence": {"stories": 2, "evidence_gap_rate": 0.0}
        },
        "regional_coverage_audit": {"india_shortfall": 0, "world_shortfall": 0},
        "v5_quality_gate": {"status": "HOLD"},
    }
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert result["checks"]["production_quality_gate"] is False
    assert "production_quality_gate_hold" in result["blockers"]



def test_research_does_not_corroborate_shared_names_without_same_event():
    from app.research import verify_article
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "Trump's war chief goes on anti-Russia, anti-China rant: Putin and Xi in Hegseth's crosshairs",
        "summary": "The defence chief criticized Russia and China during a speech.",
        "source": "Hindustan Times",
        "url": "https://www.hindustantimes.com/example-war-chief",
        "published": now,
    }
    unrelated = [
        {
            "title": "Trump's pause on Russia sanctions is a reward for Putin, Zelenskyy says",
            "summary": "The US president temporarily paused sanctions on Russian oil buyers.",
            "source": "The Guardian",
            "url": "https://www.theguardian.com/example-russia-sanctions",
            "published": now,
        },
        {
            "title": "US sanctions firms over Iran oil trade network",
            "summary": "Officials announced sanctions against firms accused of facilitating Iranian oil exports.",
            "source": "Reuters",
            "url": "https://www.reuters.com/example-iran-sanctions",
            "published": now,
        },
    ]
    result = verify_article(story, unrelated)
    assert result["independent_sources"] == 0
    assert result["evidence"] == []
    assert result["verification"] == "single-source"


def test_canadian_military_story_is_not_classified_as_india_from_feed_category():
    from app.news import _region

    region, confidence, evidence = _region(
        "india",
        "Major fire at Canadian military base in Alberta",
        "A serious incident was reported at a Canadian military installation.",
    )
    assert region == "world"
    assert confidence >= 0.85
    assert "canadian" in evidence.lower() or "alberta" in evidence.lower()


def test_production_gate_holds_for_source_failures_and_incomplete_research():
    from app.guardrails import production_readiness_gate

    ranking = {"paired_folds": 8, "promote": True}
    calibration = {"samples": 100, "ece": 0.05}
    drift = {"status": "STABLE"}
    evidence = {"stories": 10, "evidence_gap_rate": 0.0}
    coverage = {
        "stories": 10,
        "india_shortfall": 0,
        "world_shortfall": 0,
        "source_failures": 2,
        "source_warnings": 0,
        "research_completion_rate": 0.8,
    }
    gate = production_readiness_gate(ranking, calibration, drift, evidence, coverage)
    assert gate["status"] == "HOLD"
    assert "source_collection_failures" in gate["blockers"]
    assert "research_incomplete" in gate["blockers"]


def test_final_audit_surfaces_source_collection_failures(tmp_path):
    from app.ops import final_audit

    db = tmp_path / "news_knowledge.db"
    db.touch()
    stats = {
        "source_failures": 2,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(db),
        "learning_labeled": 1,
        "v5_production_evaluation": {"evidence": {"stories": 2, "evidence_gap_rate": 0.0}},
        "regional_coverage_audit": {"india_shortfall": 0, "world_shortfall": 0},
        "v5_quality_gate": {"status": "HOLD", "blockers": ["source_collection_failures"]},
    }
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert "source_collection_failures" in result["blockers"]

def test_final_audit_fails_closed_when_quality_gate_or_research_metric_is_missing(tmp_path):
    from app.ops import final_audit

    db = tmp_path / "news_knowledge.db"
    db.touch()
    stats = {
        "source_failures": 0,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(db),
        "learning_labeled": 1,
        "v5_production_evaluation": {"evidence": {"stories": 2, "evidence_gap_rate": 0.0}},
        "regional_coverage_audit": {"india_shortfall": 0, "world_shortfall": 0},
    }
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert result["production_quality_gate"] == "UNKNOWN"
    assert "production_quality_gate_unresolved" in result["blockers"]
    assert "research_incomplete" in result["blockers"]
    assert result["checks"]["research_completion"] is False


def test_final_audit_requires_complete_research_even_if_gate_claims_pass(tmp_path):
    from app.ops import final_audit

    db = tmp_path / "news_knowledge.db"
    db.touch()
    stats = {
        "source_failures": 0,
        "source_warnings": 0,
        "current_evidence": 2,
        "total": 2,
        "data_quality": {"ok": True},
        "db_path": str(db),
        "learning_labeled": 1,
        "research_completion_rate": 0.75,
        "v5_production_evaluation": {"evidence": {"stories": 2, "evidence_gap_rate": 0.0}},
        "regional_coverage_audit": {"india_shortfall": 0, "world_shortfall": 0},
        "v5_quality_gate": {"status": "PASS", "blockers": []},
    }
    result = final_audit(stats, [{"region": "india"}, {"region": "world"}])
    assert result["health"] == "DEGRADED"
    assert "research_incomplete" in result["blockers"]


def test_fetch_feed_uses_explicit_http_and_reports_status(monkeypatch):
    from app import news
    import requests

    class BadResponse:
        status_code = 503
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            raise requests.HTTPError("503 Server Error", response=self)

    seen = {}
    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return BadResponse()

    monkeypatch.setattr(news.requests, "get", fake_get)
    articles, ok, error = news.fetch_feed("https://example.com/feed.xml", "india")
    assert articles == [] and ok is False
    assert "HTTP 503" in error
    assert seen["timeout"] == (5, 15)
    assert "User-Agent" in seen["headers"]


def test_reports_on_same_canadian_military_base_fire_share_one_event_family():
    from app.ai import _same_event_family

    first = {
        "headline": "Deaths confirmed in major fire at Canada military base",
        "event_id": "report-a",
    }
    second = {
        "headline": "Major fire at Canadian military base in Alberta, Carney calls it serious incident",
        "event_id": "report-b",
    }
    assert _same_event_family(first, second)



def test_lookalike_domains_never_receive_trusted_or_official_status():
    from app.research import _is_official, _source_key, _source_trust

    assert _source_key("PIB", "https://pib.gov.in/news") == "pib"
    assert _source_key("PIB", "https://notpib.gov.in/news") == "notpib.gov.in"
    assert _source_key("BBC News", "https://notbbc.com/story") == "notbbc.com"
    assert _source_key("Reuters", "https://reuters.com/story") == "reuters"
    assert _is_official("pib")
    assert not _is_official("notpib.gov.in")
    assert _source_trust("bbc") == 0.95
    assert _source_trust("notbbc.com") == 0.65


def test_official_label_cannot_override_untrusted_article_domain():
    from app.research import verify_article

    published = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "Ministry announces a new public programme",
        "summary": "The ministry announced the programme today.",
        "source": "PIB",
        "url": "https://notpib.gov.in/story",
        "published": published,
    }
    result = verify_article(story, [], [])
    assert result["verification"] == "single-source"
    assert result["official_source"] is False
    assert result["primary_trust"] == 0.65


def test_distinct_supreme_court_events_do_not_collapse_into_obc_family():
    from app.ai import _event_family_key, _same_event

    obc = "Supreme Court issues verdict on retrospective OBC creamy layer rule"
    environment = "Supreme Court orders hearing on environmental pollution case"
    assert _event_family_key(obc) == "obc_creamy_layer"
    assert _event_family_key(environment) != "obc_creamy_layer"
    assert not _same_event(obc, environment)


def test_single_source_trust_requires_a_real_publisher_domain():
    from app.research import is_trusted_publisher

    assert is_trusted_publisher("BBC News", "https://www.bbc.com/news")
    assert is_trusted_publisher("Reuters", "https://www.reuters.com/world/story")
    assert not is_trusted_publisher("BBC News", "https://notbbc.com/news")
    assert not is_trusted_publisher("PIB", "https://notpib.gov.in/news")


def test_publisher_diversity_does_not_alias_lookalike_domains():
    from app.ai import _publisher_key

    assert _publisher_key({"source":"BBC News","url":"https://www.bbc.com/news"}) == "bbc"
    assert _publisher_key({"source":"BBC News","url":"https://notbbc.com/news"}) == "notbbc.com"
    assert _publisher_key({"source":"PIB","url":"https://notpib.gov.in/news"}) == "notpib.gov.in"



def test_selection_diagnostics_explain_regional_and_verification_rejections(monkeypatch):
    from app.ai import selection_diagnostics

    monkeypatch.setenv("NEWS_SINGLE_SOURCE_MIN_IMPORTANCE", "85")
    monkeypatch.setenv("NEWS_INDIA_MIN_REGION_CONFIDENCE", "0.45")
    candidates=[
        {"story_id":"india-low","url":"https://example.com/i","headline":"India story","region":"india","region_confidence":0.2,"importance":90,"source":"Reuters"},
        {"story_id":"world-unverified","url":"https://example.com/w","headline":"World story","region":"world","region_confidence":1.0,"importance":95,"source":"Unknown"},
    ]
    research={
        "india-low":{"verification":"multi-source","primary_fresh":True},
        "world-unverified":{"verification":"unverified","primary_fresh":True},
    }
    out=selection_diagnostics(candidates,research,[])
    assert out["candidate_regions"]=={"india":1,"world":1,"other":0}
    assert out["eligible_before_geography"]["india"]==1
    assert out["eligible_after_geography"]["india"]==0
    assert out["rejections"]["india_region_confidence"]==1
    assert out["rejections"]["unverified"]==1


def test_personalization_preserves_headroom_for_high_importance_stories():
    from app.intelligence import personalize

    story={
        "headline":"Breaking India economy update",
        "importance":95,
        "category":"india",
        "region":"india",
        "breaking_score":90,
        "emerging_topic":True,
        "novelty_score":90,
        "event_momentum":90,
    }
    out=personalize([story],{
        "priority_categories":["india"],
        "preferred_regions":["india"],
        "category_weight":6,
        "region_weight":2,
        "breaking_weight":4,
        "emerging_weight":3,
        "novelty_weight":1,
        "momentum_weight":2,
    })[0]
    assert out["personalized_score"] < 100
    assert out["personalization_adjustment"] <= 2


def test_official_indian_domains_are_exactly_canonicalized():
    from app.research import _is_official, _source_key

    assert _is_official(_source_key("PM India", "https://www.pmindia.gov.in/"))
    assert _is_official(_source_key("Supreme Court", "https://www.sci.gov.in/"))
    assert _is_official(_source_key("Ministry of Defence", "https://mod.gov.in/"))
    assert not _is_official(_source_key("PM India", "https://notpmindia.gov.in/"))


def test_final_audit_cannot_pass_with_any_production_gate_blocker():
    from app.ops import final_audit

    stats={
        "source_failures":0,
        "source_warnings":0,
        "current_evidence":1,
        "total":1,
        "data_quality":{"ok":True},
        "db_path":"data/news_knowledge.db",
        "learning_labeled":10,
        "v5_quality_gate":{"status":"HOLD","blockers":["research_incomplete"]},
    }
    audit=final_audit(stats,[{"region":"world","importance":90,"verification":{"verification":"multi-source","confidence":90}}])
    assert audit["health"] != "PASS"
    assert "research_incomplete" in audit["blockers"]


def test_final_audit_fails_closed_when_regional_coverage_is_missing(tmp_path):
    from app.ops import final_audit

    db=tmp_path/"news_knowledge.db"
    db.touch()
    stats={
        "source_failures":0,
        "source_warnings":0,
        "current_evidence":2,
        "total":2,
        "data_quality":{"ok":True},
        "db_path":str(db),
        "learning_labeled":0,
        "v5_production_evaluation":{"evidence":{"stories":2,"evidence_gap_rate":0.0}},
        "v5_quality_gate":{"status":"PASS"},
    }
    result=final_audit(stats,[{"region":"india"},{"region":"world"}])
    assert result["checks"]["regional_coverage"] is False
    assert result["health"]=="DEGRADED"
    assert "regional_coverage_shortfall" in result["blockers"]


def test_final_audit_fails_closed_when_coverage_shortfall_fields_are_missing(tmp_path):
    from app.ops import final_audit

    db=tmp_path/"news_knowledge.db"
    db.touch()
    stats={
        "source_failures":0,"source_warnings":0,"current_evidence":2,"total":2,
        "data_quality":{"ok":True},"db_path":str(db),"learning_labeled":0,
        "v5_production_evaluation":{"evidence":{"stories":2,"evidence_gap_rate":0.0}},
        "regional_coverage_audit":{"india_shortfall":0},
        "v5_quality_gate":{"status":"PASS"},
    }
    result=final_audit(stats,[{"region":"india"},{"region":"world"}])
    assert result["checks"]["regional_coverage"] is False
    assert "regional_coverage_shortfall" in result["blockers"]


def test_learning_adjustments_are_neutral_without_history_and_signed_with_evidence():
    from app.learning import _profile, apply_learning

    empty=apply_learning([{"source":"New source","category":"new category","importance":70}],{})
    assert empty[0]["learning_adjustment"] == 0.0

    rows=[]
    for i in range(6):
        rows.append({
            "run_date":"2026-09-01","event_id":f"good-{i}","story_id":f"good-{i}",
            "source":"Strong source","category":"business","selected":"true",
            "outcome_score":"0.9","learning_value":"0.9","seen_again_7d":"1",
        })
    rows.append({
        "run_date":"2026-09-01","event_id":"weak","story_id":"weak",
        "source":"Weak source","category":"india","selected":"true",
        "outcome_score":"0.0","learning_value":"0.0","seen_again_7d":"0",
    })
    profile=_profile(rows)
    out=apply_learning([
        {"source":"Strong source","category":"business","importance":70},
        {"source":"Weak source","category":"india","importance":70},
    ],profile)
    assert out[0]["learning_adjustment"] > 0
    assert out[1]["learning_adjustment"] < 0
    assert all(abs(x["learning_adjustment"]) <= 4 for x in out)


def test_research_matches_same_event_across_verb_inflections():
    from app.research import verify_article
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "India regulator approves Nova Bank merger after review",
        "summary": "The regulator approved the merger following a review.",
        "source": "India Today",
        "url": "https://www.indiatoday.in/example-merger",
        "published": now,
    }
    corroborating = {
        "title": "Regulator approves Nova Bank merger after review",
        "summary": "Officials confirmed the merger approval.",
        "source": "The Guardian",
        "url": "https://www.theguardian.com/example-merger",
        "published": now,
    }
    result = verify_article(story, [corroborating])
    assert result["independent_sources"] == 1
    assert result["verification"] == "multi-report"
    assert result["evidence"][0]["url"] == corroborating["url"]


def test_research_rejects_same_publisher_and_stale_reports():
    from app.research import verify_article
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    story = {
        "headline": "ISRO launches new weather satellite from Sriharikota",
        "summary": "ISRO launched a weather satellite today.",
        "source": "NDTV",
        "url": "https://www.ndtv.com/example-satellite",
        "published": now.isoformat(),
    }
    same_publisher = {
        "title": "ISRO launched new weather satellite from Sriharikota",
        "summary": "The satellite was launched today.",
        "source": "NDTV",
        "url": "https://www.ndtv.com/another-satellite-report",
        "published": now.isoformat(),
    }
    stale = {
        "title": "ISRO launches new weather satellite from Sriharikota",
        "summary": "Satellite launch details.",
        "source": "Reuters",
        "url": "https://www.reuters.com/example-satellite",
        "published": (now - timedelta(days=5)).isoformat(),
    }
    result = verify_article(story, [same_publisher, stale])
    assert result["independent_sources"] == 0
    assert result["evidence"] == []
    assert result["verification"] == "single-source"


def test_research_status_reason_explains_unresolved_evidence():
    from app.intelligence_v5_plus import autonomous_research

    story = {
        "headline": "Example major public policy announcement",
        "importance": 90,
        "impact": {"score": 90},
        "source": "Unknown publisher",
        "url": "https://example.org/policy",
        "published": "2000-01-01T00:00:00+00:00",
        "summary": "A public policy announcement was reported.",
    }
    queue = autonomous_research([story], evidence_pool=[])
    assert queue
    assert queue[0]["research_status"] == "RESEARCH_REQUIRED"
    assert queue[0]["research_status_reason"] in {
        "primary_source_missing_or_stale",
        "no_strict_event_matched_independent_evidence",
    }
    assert queue[0]["evidence_publishers"] == []


def test_research_diagnostics_survive_into_operational_report():
    from app.production_v5 import autonomous_research_agent, generate_research_reports

    queue = [{
        "headline": "Example event",
        "priority": 90,
        "research_status": "RESEARCH_REQUIRED",
        "research_status_reason": "no_strict_event_matched_independent_evidence",
        "evidence_publishers": [],
        "primary_fresh": True,
        "independent_source_count": 0,
        "evidence_count": 0,
    }]
    agent = autonomous_research_agent(queue, [])
    report = generate_research_reports(agent)[0]
    assert agent[0]["research_status_reason"] == "no_strict_event_matched_independent_evidence"
    assert report["research_status_reason"] == "no_strict_event_matched_independent_evidence"
    assert report["primary_fresh"] is True
    assert report["evidence_publishers"] == []


def test_region_classifier_prefers_explicit_foreign_headline_over_feed_category():
    from app.news import _region

    cases = [
        ("India", "Why is France burning? Khanna pits wealth theory against Vance's imports", "A debate about French protests and US political commentary.", "world"),
        ("india", "Charles Schwab blocks AI agents as US banks weigh automation", "A US financial-services story.", "world"),
        ("business", "Supreme Court ruling changes policy in France", "French officials discussed the ruling.", "world"),
        ("india", "Supreme Court of India issues a ruling in Delhi", "The ruling affects Indian law.", "india"),
    ]
    for category, headline, summary, expected in cases:
        region, confidence, evidence = _region(category, headline, summary)
        assert region == expected, (headline, region, confidence, evidence)


def test_business_category_does_not_bias_mixed_geography_toward_india():
    from app.news import _region

    headline = "Global firms respond to policy changes"
    summary = "Companies in France and India reported different responses."
    business = _region("business", headline, summary)
    world = _region("world", headline, summary)
    assert business[0] == "world"
    assert business[0] == world[0]


def test_single_source_is_not_counted_as_independently_verified():
    from app.quality import quality_snapshot

    stories = [
        {"story_id": "multi", "importance": 80},
        {"story_id": "single", "importance": 85},
        {"story_id": "official", "importance": 75},
    ]
    research = {
        "multi": {"verification": "multi-source", "independent_sources": 2},
        "single": {"verification": "single-source", "independent_sources": 0},
        "official": {"verification": "official-source", "independent_sources": 0},
    }
    result = quality_snapshot(stories, research)
    assert result["stories"] == 3
    assert result["verified"] == 2
    assert result["strong"] == 2
    assert result["verification_rate"] == round(2 / 3, 3)


def test_production_gate_fails_closed_when_research_completion_metric_missing():
    from app.guardrails import production_readiness_gate

    gate = production_readiness_gate(
        {"paired_folds": 8, "promote": True},
        {"samples": 100, "ece": 0.05},
        {"status": "STABLE"},
        {"stories": 10, "evidence_gap_rate": 0.0},
        {"stories": 10, "india_shortfall": 0, "world_shortfall": 0},
    )
    assert gate["status"] == "HOLD"
    assert "research_incomplete" in gate["blockers"]


def test_main_verification_counts_do_not_promote_single_source_to_evidence():
    from app.main import _verification_counts

    rows = [
        {"verification": "single-source"},
        {"verification": "unverified"},
        {"verification": "multi-report"},
        {"verification": "multi-source"},
        {"verification": "official-source"},
    ]
    evidence, verified, strong = _verification_counts(rows)
    assert evidence == 3
    assert verified == 3
    assert strong == 2


def test_region_classifier_covers_additional_world_geographies():
    from app.news import _region

    cases = [
        ("india", "German parliament debates a new budget in Berlin", "German officials outlined the proposal.", "world"),
        ("india", "Spain announces new climate measures in Madrid", "Spanish officials announced the policy.", "world"),
        ("india", "Brazil central bank changes its interest-rate outlook", "Brazilian markets reacted to the announcement.", "world"),
        ("india", "Pakistan announces new energy policy in Islamabad", "Pakistani officials described the changes.", "world"),
        ("india", "Kenya launches new public health initiative", "Officials in Nairobi described the initiative.", "world"),
        ("india", "Indonesia announces new technology export rules", "The policy applies across Indonesia.", "world"),
        ("india", "Saudi Arabia announces new investment plan in Riyadh", "Officials discussed the investment plan.", "world"),
        ("india", "London officials announce a new transport plan", "The policy affects commuters in Britain.", "world"),
        ("india", "Indian parliament debates a new bill in Delhi", "Indian officials outlined the proposal.", "india"),
    ]
    for category, headline, summary, expected in cases:
        region, confidence, evidence = _region(category, headline, summary)
        assert region == expected, (headline, region, confidence, evidence)


def test_research_discovery_parses_google_news_publisher_and_freshness(monkeypatch):
    from types import SimpleNamespace
    import time
    import app.research as research

    class Response:
        content = b"<rss/>"
        def raise_for_status(self):
            return None

    published_parsed = time.gmtime()
    entry = {
        "title": "Major fire at Canadian military base - BBC News",
        "source": {"title": "BBC News"},
        "link": "https://news.google.com/rss/articles/example",
        "summary": "Four people were killed in a fire.",
        "published_parsed": published_parsed,
    }
    monkeypatch.setattr(research.requests, "get", lambda *a, **k: Response())
    monkeypatch.setattr(research.feedparser, "parse", lambda content: SimpleNamespace(entries=[entry]))
    found, metrics = research.discover_related_articles(
        [{"headline": "Major fire at Canadian military base", "importance": 90, "region": "world"}],
        existing_articles=[],
        max_queries=1,
    )
    assert len(found) == 1
    assert found[0]["source"] == "BBC News"
    assert found[0]["published"].startswith(time.strftime("%Y-%m-%dT%H:%M:%S", published_parsed))
    assert metrics["queries"] == 1
    assert metrics["failed_queries"] == 0
    assert metrics["articles_found"] == 1
    assert metrics["stale_skipped"] == 0
    assert metrics["unique_publishers"] == 1
    assert research._source_key(found[0]["source"], found[0]["url"]) == "bbc"


def test_research_discovery_is_bounded_and_tolerates_network_failures(monkeypatch):
    import app.research as research

    def fail(*args, **kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(research.requests, "get", fail)
    found, metrics = research.discover_related_articles(
        [{"headline": f"Important world event number {i}", "importance": 90-i, "region": "world"} for i in range(5)],
        max_queries=2,
    )
    assert found == []
    assert metrics["queries"] == 2
    assert metrics["failed_queries"] == 2
    assert metrics["articles_found"] == 0
    assert metrics["unique_publishers"] == 0


def test_research_completion_rate_treats_empty_queue_as_complete():
    from app.ops import research_completion_rate

    assert research_completion_rate(0, 0) == 1.0
    assert research_completion_rate(4, 4) == 1.0
    assert research_completion_rate(4, 3) == 0.75
    assert research_completion_rate(4, 9) == 1.0


def test_research_completion_rate_fails_closed_on_invalid_counts():
    from app.ops import research_completion_rate

    assert research_completion_rate(None, 0) == 0.0
    assert research_completion_rate(4, -1) == 0.0
    assert research_completion_rate(-1, 0) == 0.0


def test_story_and_vocabulary_renderers_have_one_authoritative_definition():
    import ast

    tree = ast.parse(read("app/main.py"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert names.count("_story_block") == 1
    assert names.count("_vocab_block") == 1


def test_main_anchors_historical_trend_to_ist_run_date():
    source = read("app/main.py")
    assert 'historical_trend(read_rows(DATA/"news_history.csv"),7,as_of=today)' in source


def test_research_stats_do_not_count_stale_single_source_as_current(monkeypatch):
    import app.research as research

    fixtures = {
        "stale": {
            "verification": "single-source", "primary_fresh": False,
            "independent_sources": 0, "historical": [], "contradiction_flag": False,
        },
        "corroborated": {
            "verification": "multi-report", "primary_fresh": False,
            "independent_sources": 1, "historical": [], "contradiction_flag": False,
        },
    }
    monkeypatch.setattr(research, "verify_article", lambda story, pool, memory: fixtures[story["story_id"]])
    result = research.research_stories([
        {"story_id": "stale"}, {"story_id": "corroborated"},
    ])
    stats = result["_stats"]
    assert stats["current"] == 1
    assert stats["coverage"] == 0.5
    assert stats["single_source"] == 1
    assert stats["multi_report"] == 1
    assert stats["independent_source_coverage"] == 0.5
    assert stats["single_source_rate"] == 0.5
    assert stats["stale_primary"] == 2


def test_research_stats_expose_contradiction_and_source_counts(monkeypatch):
    import app.research as research

    monkeypatch.setattr(research, "verify_article", lambda story, pool, memory: {
        "verification": "multi-source", "primary_fresh": True,
        "independent_sources": 2, "historical": [], "contradiction_flag": True,
    })
    result = research.research_stories([{"story_id": "event"}])
    stats = result["_stats"]
    assert stats["strong"] == 1
    assert stats["independent_sources_total"] == 2
    assert stats["mean_independent_sources"] == 2.0
    assert stats["contradictions"] == 1
    assert stats["contradiction_rate"] == 1.0


def test_source_identity_rejects_lookalike_domains():
    from app.research import _source_key

    assert _source_key("Reuters", "https://www.reuters.com/world/story") == "reuters"
    assert _source_key("Reuters", "https://reuters.com.example.org/story") == "reuters.com.example.org"
    assert _source_key("BBC News", "https://news.google.com/rss/articles/example") == "bbc"


def test_research_verification_metrics_are_persisted_to_audit_snapshot():
    source = read("app/main.py")
    assert 'research_stats=research.get("_stats",{})' in source
    assert 'stats["research_verification"]=research_stats' in source


def test_source_health_and_diversity_use_canonical_publisher_identity():
    from app.quality import prepare_candidates, source_health

    candidates = [
        {"headline": "Story A", "source": "BBC News", "url": "https://www.bbc.co.uk/news/a", "importance": 80},
        {"headline": "Story B", "source": "BBC", "url": "https://www.bbc.com/news/b", "importance": 60},
        {"headline": "Story C", "source": "Reuters", "url": "https://www.reuters.com/world/c", "importance": 90},
    ]
    health = source_health(candidates)
    assert health["bbc"]["articles"] == 2
    assert health["bbc"]["high_value"] == 1
    assert health["reuters"]["articles"] == 1

    prepared = prepare_candidates(candidates, [])
    bbc_rows = [row for row in prepared if row["source"] in {"BBC News", "BBC"}]
    assert len(bbc_rows) == 2
    assert all(row["source_diversity_score"] == 2.0 for row in bbc_rows)


def test_coverage_plan_keeps_requested_targets_visible_when_candidates_are_missing():
    from app.quality import coverage_plan

    plan = coverage_plan([
        {"region": "india", "category": "india"},
        {"region": "world", "category": "world"},
        {"region": "world", "category": "world"},
    ], world_target=5, india_target=5)
    assert plan["india_target"] == 5
    assert plan["world_target"] == 5
    assert plan["india_available"] == 1
    assert plan["world_available"] == 2
    assert plan["india_shortfall"] == 4
    assert plan["world_shortfall"] == 3


def test_coverage_plan_clamps_negative_requested_targets_to_zero():
    from app.quality import coverage_plan

    plan = coverage_plan([], world_target=-3, india_target=-1)
    assert plan["world_target"] == 0
    assert plan["india_target"] == 0
    assert plan["world_shortfall"] == 0
    assert plan["india_shortfall"] == 0


def test_coverage_audit_counts_canonical_publishers_not_alias_labels():
    from app.guardrails import coverage_audit

    result = coverage_audit([
        {"region": "india", "source": "BBC News", "url": "https://www.bbc.co.uk/news/a", "category": "india"},
        {"region": "world", "source": "BBC", "url": "https://www.bbc.com/news/b", "category": "world"},
        {"region": "world", "source": "Reuters", "url": "https://www.reuters.com/world/c", "category": "world"},
    ])
    assert result["distinct_sources"] == 2
    assert result["distinct_categories"] == 2
    assert result["india_target"] == 5
    assert result["india_shortfall"] == 4
    assert result["world_shortfall"] == 3


def test_evidence_audit_reports_source_metrics_and_handles_malformed_counts():
    from app.guardrails import evidence_audit

    result = evidence_audit([
        {
            "headline": "Corroborated event", "source": "Reuters",
            "url": "https://reuters.com/a", "summary": "An event happened.",
            "verification": {
                "verification": "multi-report", "independent_sources": 2,
                "evidence": [{"source": "BBC"}], "contradiction_flag": True,
            },
        },
        {
            "headline": "Malformed metadata", "source": "Unknown",
            "url": "https://example.org/b", "summary": "Another event.",
            "verification": {"verification": "single-source", "independent_sources": "invalid"},
        },
    ])
    assert result["stories"] == 2
    assert result["corroborated"] == 1
    assert result["independent_source_stories"] == 1
    assert result["independent_sources_total"] == 2
    assert result["independent_source_coverage"] == 0.5
    assert result["mean_independent_sources"] == 1.0
    assert result["contradiction_count"] == 1
    assert result["contradiction_rate"] == 0.5
    assert result["verification_tiers"] == {"multi-report": 1, "single-source": 1}
    assert len(result["evidence_gaps"]) == 1


def test_quality_scores_ignore_nan_infinite_and_malformed_numeric_values():
    from app.quality import prepare_candidates, source_health

    rows = [
        {"headline": "Valid headline about central bank policy", "source": "Reuters",
         "url": "https://www.reuters.com/a", "importance": 70, "trend_score": 20},
        {"headline": "Invalid numeric headline about market policy", "source": "BBC",
         "url": "https://www.bbc.com/news/b", "importance": float("nan"),
         "trend_score": float("inf"), "breaking_score": "not-a-number"},
        {"headline": "Overflow numeric headline about science policy", "source": "AP",
         "url": "https://apnews.com/c", "importance": "-inf", "trend_score": None},
    ]
    prepared = prepare_candidates(rows, history=None)
    assert len(prepared) == 3
    assert all(row["quality_score"] == row["quality_score"] for row in prepared)
    assert all(abs(row["quality_score"]) != float("inf") for row in prepared)
    health = source_health(rows)
    assert health["reuters"]["high_value"] == 0
    assert health["bbc"]["high_value"] == 0
    assert health["associated press"]["high_value"] == 0


def test_prepare_candidates_handles_none_and_non_mapping_rows():
    from app.quality import prepare_candidates

    assert prepare_candidates(None) == []
    assert prepare_candidates([None, "bad row", {"headline": "A valid story", "importance": 50}])
    assert len(prepare_candidates([None, "bad row", {"headline": "A valid story", "importance": 50}])) == 1


def test_coverage_audit_surfaces_unknown_and_missing_regions():
    from app.guardrails import coverage_audit

    result = coverage_audit([
        {"region": "india", "source": "Reuters"},
        {"region": "world", "source": "BBC"},
        {"region": "other", "source": "AP"},
        {"source": "Unknown"},
    ], india_target=1, world_target=1)
    assert result["india"] == 1
    assert result["world"] == 1
    assert result["other_region"] == 1
    assert result["missing_region"] == 1
    assert result["india_shortfall"] == 0
    assert result["world_shortfall"] == 0


def test_confidence_snapshot_never_emits_non_finite_values():
    from app.ops import confidence_snapshot

    snapshot = confidence_snapshot([
        {"verification": {"confidence": float("nan")}, "calibrated_confidence": float("inf")},
        {"verification": {"confidence": "invalid"}, "calibrated_confidence": "-inf"},
        {"verification": {"confidence": 85}, "calibrated_confidence": 82},
    ])
    assert snapshot["avg_raw"] == 28.3
    assert snapshot["avg_calibrated"] == 27.3
    assert snapshot["high_confidence"] == 1
    assert snapshot["low_confidence"] == 2


def test_quality_ranking_has_stable_tiebreakers_independent_of_input_order():
    from app.quality import prepare_candidates

    rows = [
        {"story_id": "b", "headline": "Beta policy development", "source": "Reuters",
         "url": "https://www.reuters.com/b", "importance": 70},
        {"story_id": "a", "headline": "Alpha policy development", "source": "BBC",
         "url": "https://www.bbc.com/news/a", "importance": 70},
        {"story_id": "c", "headline": "Gamma policy development", "source": "AP",
         "url": "https://apnews.com/c", "importance": 70},
    ]
    first = [row["story_id"] for row in prepare_candidates(rows, [])]
    second = [row["story_id"] for row in prepare_candidates(list(reversed(rows)), [])]
    assert first == second == ["a", "b", "c"]


def test_quality_snapshots_fail_safely_on_malformed_rows_and_research_records():
    from app.quality import quality_snapshot, source_health

    assert source_health(None) == {}
    assert source_health([None, "bad", {"source": "Reuters", "importance": float("nan")}])["reuters"]["articles"] == 1
    snapshot = quality_snapshot([
        None,
        {"story_id": "good", "importance": float("inf"), "quality_score": "invalid"},
        {"story_id": "bad-record", "importance": 50},
    ], {
        "good": {"verification": "multi-source", "contradiction_flag": True},
        "bad-record": None,
    })
    assert snapshot["stories"] == 2
    assert snapshot["verified"] == 1
    assert snapshot["strong"] == 1
    assert snapshot["conflicts"] == 1
    assert snapshot["avg_importance"] == 25.0
    assert snapshot["avg_quality"] == 25.0
    assert quality_snapshot(None, None)["stories"] == 0


def test_production_readiness_gate_fails_closed_on_malformed_telemetry():
    from app.guardrails import production_readiness_gate

    result = production_readiness_gate(
        {"paired_folds": "many", "promote": True},
        {"samples": float("inf"), "ece": float("nan")},
        {"status": "STABLE"},
        {"stories": 2, "evidence_gap_rate": float("nan")},
        {
            "stories": 2,
            "india_shortfall": "unknown",
            "world_shortfall": 0,
            "source_failures": float("inf"),
            "source_warnings": "bad",
            "research_completion_rate": float("nan"),
        },
    )
    assert result["status"] == "HOLD"
    assert "insufficient_paired_folds" in result["blockers"]
    assert "insufficient_calibration_holdout" in result["blockers"]
    assert "poor_calibration" in result["blockers"]
    assert "evidence_gaps" in result["blockers"]
    assert "research_incomplete" in result["blockers"]


def test_production_readiness_gate_handles_non_mapping_inputs():
    from app.guardrails import production_readiness_gate

    result = production_readiness_gate(None, [], None, "bad", [])
    assert result["status"] == "HOLD"
    assert "insufficient_paired_folds" in result["blockers"]
    assert "missing_evidence_audit" in result["blockers"]
    assert "research_incomplete" in result["blockers"]


def test_adaptive_selection_diversifies_categories_within_verification_tier(monkeypatch):
    from app import ai

    monkeypatch.setattr(ai, "_same_event_family", lambda left, right: False)
    monkeypatch.setattr(ai, "_event_family_key", lambda headline: "")
    pool = [
        (95, {"headline": "Politics update one", "category": "politics", "_verification": "multi-source", "source": "Reuters", "url": "https://reuters.com/1"}),
        (90, {"headline": "Politics update two", "category": "politics", "_verification": "multi-source", "source": "BBC", "url": "https://bbc.com/2"}),
        (85, {"headline": "Economy update", "category": "economy", "_verification": "multi-source", "source": "AP", "url": "https://apnews.com/3"}),
        (80, {"headline": "Science update", "category": "science", "_verification": "multi-source", "source": "DW", "url": "https://dw.com/4"}),
    ]

    selected = ai._select_diverse(pool, 4)
    assert [item["category"] for item in selected] == ["politics", "economy", "science", "politics"]


def test_adaptive_category_diversity_never_overrides_verification_tier(monkeypatch):
    from app import ai

    monkeypatch.setattr(ai, "_same_event_family", lambda left, right: False)
    monkeypatch.setattr(ai, "_event_family_key", lambda headline: "")
    pool = [
        (95, {"headline": "Politics one", "category": "politics", "_verification": "multi-source", "source": "Reuters", "url": "https://reuters.com/1"}),
        (90, {"headline": "Politics two", "category": "politics", "_verification": "multi-source", "source": "BBC", "url": "https://bbc.com/2"}),
        (99, {"headline": "Science report", "category": "science", "_verification": "multi-report", "source": "AP", "url": "https://apnews.com/3"}),
    ]

    selected = ai._select_diverse(pool, 2)
    assert [item["_verification"] for item in selected] == ["multi-source", "multi-source"]


def test_model_benchmark_rewards_evidence_and_rejects_unsupported_claims():
    from scripts.benchmark_ollama_models import TASKS, score_response

    supported = next(task for task in TASKS if task["name"] == "supported_fact_extraction")
    assert score_response(supported, '{"fact":"repo rate reduction","number":"25 basis points"}')["passed"]
    restraint = next(task for task in TASKS if task["name"] == "unsupported_claim_restraint")
    assert score_response(restraint, "The rate decision is not stated in the evidence.")["passed"]
    assert not score_response(restraint, "The central bank cut the rate.")["passed"]


def test_independent_source_search_budget_defaults_are_expanded():
    source = read("app/main.py")
    assert 'NEWS_RESEARCH_SEARCH_QUERIES","20"' in source
    assert 'NEWS_RESEARCH_QUERIES_PER_REGION","10"' in source


def test_official_rbi_economy_feed_is_configured():
    sources = yaml.safe_load(read("config/sources.yaml"))
    assert "economy" in sources["sources"]
    assert any("rbi.org.in/pressreleases_rss.xml" in url for url in sources["sources"]["economy"])


def test_category_research_second_pass_uses_distinct_query_variants(monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlparse
    import app.research as research

    requested = []
    monkeypatch.setattr(research.requests, "get", lambda url, **kwargs: (
        requested.append(url) or SimpleNamespace(content=b"feed", raise_for_status=lambda: None)
    ))
    monkeypatch.setattr(research.feedparser, "parse", lambda _: SimpleNamespace(entries=[]))
    _, first = research.discover_category_articles(["defence"], max_queries=2, pass_index=0)
    first_queries = [parse_qs(urlparse(url).query)["q"][0] for url in requested]
    requested.clear()
    _, second = research.discover_category_articles(["defence"], max_queries=2, pass_index=1)
    second_queries = [parse_qs(urlparse(url).query)["q"][0] for url in requested]

    assert first["queries"] == second["queries"] == 2
    assert len(set(first_queries + second_queries)) == 4
    assert not (set(first_queries) & set(second_queries))


def test_category_research_parses_rfc2822_dates_without_parsed_time(monkeypatch):
    from datetime import datetime, timezone
    from email.utils import format_datetime
    from types import SimpleNamespace
    import app.research as research

    entry = {
        "title": "India defence procurement update - Example News",
        "link": "https://example.com/defence-rfc2822",
        "published": format_datetime(datetime.now(timezone.utc)),
        "summary": "A fresh defence procurement update.",
        "source": {"title": "Example News"},
    }
    monkeypatch.setattr(research.requests, "get", lambda *a, **k: SimpleNamespace(
        content=b"feed", raise_for_status=lambda: None
    ))
    monkeypatch.setattr(research.feedparser, "parse", lambda _: SimpleNamespace(entries=[entry]))
    articles, metrics = research.discover_category_articles(
        ["defence"], max_queries=1, existing_articles=[]
    )
    assert metrics["articles_found"] == 1
    assert articles[0]["url"] == entry["link"]


def test_verification_does_not_count_publisher_aliases_as_independent_sources():
    from datetime import datetime, timezone
    from app.research import verify_article

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "headline": "Company X launches emergency plant after factory fire",
        "summary": "Company X launched an emergency plant after a factory fire.",
        "source": "Reuters", "url": "https://reuters.com/example-primary", "published": now,
    }
    evidence = [
        {
            "title": "Company X opens emergency plant following factory fire",
            "summary": "Company X opened an emergency plant after the factory fire.",
            "source": "DW", "url": "https://news.google.com/rss/articles/dw-report",
            "published": now,
        },
        {
            "title": "Company X opens emergency plant following factory fire",
            "summary": "Company X opened an emergency plant after the factory fire.",
            "source": "Deutsche Welle", "url": "https://news.google.com/rss/articles/deutsche-welle-report",
            "published": now,
        },
    ]
    result = verify_article(story, evidence)
    assert result["independent_sources"] == 1
    assert result["verification"] == "multi-report"


def test_near_identical_syndicated_reports_count_as_one_independent_source():
    from app.research import _same_reporting_copy, verify_article

    primary = {
        "headline": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production.",
        "source": "Reuters",
        "url": "https://reuters.com/acme-primary",
        "published": datetime.now(timezone.utc).isoformat(),
    }
    copied_a = {
        "title": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production. The new plant will restore output.",
        "source": "Example Wire",
        "url": "https://wire.example/acme",
        "published": datetime.now(timezone.utc).isoformat(),
    }
    copied_b = {
        "title": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production. The new plant will restore output.",
        "source": "Example Daily",
        "url": "https://daily.example/acme",
        "published": datetime.now(timezone.utc).isoformat(),
    }
    assert _same_reporting_copy(copied_a, copied_b)
    result = verify_article(primary, [copied_a, copied_b], [])
    assert result["independent_sources"] == 1
    assert len(result["evidence"]) == 1


def test_similar_event_with_distinct_reporting_is_not_automatically_syndicated():
    from app.research import _same_reporting_copy

    first = {
        "title": "Acme launches emergency battery plant after factory fire",
        "summary": "Officials said the new facility will restore production capacity after last week's incident.",
    }
    second = {
        "title": "Battery maker Acme opens replacement plant following industrial blaze",
        "summary": "The company described a separate investment plan and outlined new safety systems at the site.",
    }
    assert not _same_reporting_copy(first, second)


def test_verification_audits_near_identical_reporting_copies_excluded():
    from datetime import datetime, timezone
    from app.research import research_stories, verify_article

    now = datetime.now(timezone.utc).isoformat()
    primary = {
        "headline": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production.",
        "source": "Reuters",
        "url": "https://reuters.com/acme-primary",
        "published": now,
    }
    copied_a = {
        "title": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production. The new plant will restore output.",
        "source": "Example Wire",
        "url": "https://wire.example/acme",
        "published": now,
    }
    copied_b = {
        "title": "Acme launches emergency battery plant after factory fire",
        "summary": "Acme opened an emergency battery plant after a factory fire disrupted production. The new plant will restore output.",
        "source": "Example Daily",
        "url": "https://daily.example/acme",
        "published": now,
    }

    verified = verify_article(primary, [copied_a, copied_b])
    assert verified["independent_sources"] == 1
    assert verified["duplicate_reporting_copies_excluded"] == 1

    aggregate = research_stories(
        [{"story_id": "acme-1", **primary}],
        articles=[copied_a, copied_b],
    )
    assert aggregate["_stats"]["duplicate_reporting_copies_excluded"] == 1


def test_duplicate_reporting_audit_metric_defaults_to_zero_without_copies():
    from datetime import datetime, timezone
    from app.research import research_stories

    now = datetime.now(timezone.utc).isoformat()
    story = {
        "story_id": "acme-2",
        "headline": "Acme launches emergency battery plant after factory fire",
        "source": "Reuters",
        "url": "https://reuters.com/acme-primary",
        "published": now,
    }
    result = research_stories([story], articles=[])
    assert result["acme-2"]["duplicate_reporting_copies_excluded"] == 0
    assert result["_stats"]["duplicate_reporting_copies_excluded"] == 0



def test_feed_collection_preserves_description_and_atom_content_summaries(monkeypatch):
    from types import SimpleNamespace
    from app import news

    entries = [
        {
            "title": "RSS article with description",
            "link": "https://example.com/rss",
            "summary": "",
            "description": "<p>Fallback &amp; useful description.</p>",
        },
        {
            "title": "Atom article with content",
            "link": "https://example.com/atom",
            "summary": "",
            "content": [{"value": "<p>Atom body content.</p>"}],
        },
    ]
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: SimpleNamespace(
        content=b"feed", status_code=200, headers={"Content-Type": "application/rss+xml"},
        raise_for_status=lambda: None,
    ))
    monkeypatch.setattr(news.feedparser, "parse", lambda _: SimpleNamespace(
        entries=entries, feed={"title": "Example Feed"}, bozo=False,
    ))

    articles, ok, warning = news.fetch_feed("https://example.com/feed", "world")

    assert ok is True
    assert warning == ""
    assert [article.summary for article in articles] == [
        "Fallback & useful description.",
        "Atom body content.",
    ]



def test_feed_collection_uses_detail_and_namespaced_summary_fallbacks(monkeypatch):
    from types import SimpleNamespace
    from app import news

    entries = [
        {
            "title": "RSS detail field",
            "link": "https://example.com/detail",
            "summary": "",
            "summary_detail": {"value": "<p>Publisher supplied detail &amp; context.</p>"},
        },
        {
            "title": "Media extension field",
            "link": "https://example.com/media",
            "media_description": "<p>Media namespace description.</p>",
        },
        {
            "title": "Atom content fallback",
            "link": "https://example.com/content",
            "content": [{"value": "<p>Actual Atom content.</p>"}],
        },
    ]
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: SimpleNamespace(
        content=b"feed", status_code=200, headers={"Content-Type": "application/rss+xml"},
        raise_for_status=lambda: None,
    ))
    monkeypatch.setattr(news.feedparser, "parse", lambda _: SimpleNamespace(
        entries=entries, feed={"title": "Example Feed"}, bozo=False,
    ))

    articles, ok, warning = news.fetch_feed("https://example.com/feed", "world")

    assert ok is True
    assert warning == ""
    assert [article.summary for article in articles] == [
        "Publisher supplied detail & context.",
        "Media namespace description.",
        "Actual Atom content.",
    ]


def test_review_packet_defaults_to_latest_capture_without_hardcoded_filename():
    workflow = yaml.safe_load(read(".github/workflows/news_intelligence.yml"))
    triggers = workflow.get(True) or workflow.get("on") or {}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["record_path"]["default"] == ""
    assert inputs["record_path"]["required"] is False
    text = read(".github/workflows/news_intelligence.yml")
    assert "selected latest capture: $RECORD_PATH" in text
    assert "find data/historical_evaluation_records -maxdepth 1 -type f -name '*.json'" in text
    assert "sort | tail -n 1" in text
    assert "No historical capture JSON files are available" in text
