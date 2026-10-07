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
    assert out and out[0]["personalized_score"]>=79

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


def test_workflow_is_schedule_only_and_linked():
    workflow = yaml.safe_load(read(".github/workflows/morning_news.yml"))
    triggers = workflow.get(True) or workflow.get("on") or {}
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "push" not in triggers

    text = read(".github/workflows/morning_news.yml")
    assert "python -m compileall -q app" in text
    assert "python -m app.main" in text
    assert "actions/upload-artifact@v5" in text
    assert "NEWS_WORLD_TOP: '5'" in text
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
           "runtime":"1.2s","analytics":{"last_7_days":{"runs":5,"avg_success_rate":0.75,"avg_miss_rate":0.12}}}
    messages=build_messages(result,"2026-10-07",stats,[])
    payload="\n".join(messages)
    assert "EXECUTIVE SUMMARY" in payload
    assert "QUALITY & VERIFICATION" in payload
    assert "LEARNING PERFORMANCE" in payload
    assert "INDIA" in payload and "WORLD" in payload
    assert "DETAILED STORIES" in payload
    assert "STRONG" in payload and "SINGLE SOURCE" in payload


def test_quality_intelligence_v2_contract(tmp_path):
    from app.quality import prepare_candidates, coverage_gaps, source_health, quality_snapshot, coverage_plan
    rows=[{"headline":"India economy update","category":"india","source":"Reuters","importance":80,"story_id":"1"}]
    out=prepare_candidates(rows,[])
    assert out and "novelty_score" in out[0] and "event_momentum" in out[0]
    assert isinstance(coverage_gaps(out),list)
    plan=coverage_plan(out,world_target=5,india_target=5)
    assert {"world_target","india_target","world_shortfall","india_shortfall"} <= plan.keys()
    assert source_health(out)["Reuters"]["articles"]==1
    snap=quality_snapshot(out,{"1":{"verification":"multi-source","contradiction_flag":False}})
    assert snap["strong"]==1

def test_backtest_v2_contract(tmp_path):
    from app.analytics import backtest_learning_v2, calibrate_learning_threshold
    from app.storage import ensure_data
    ensure_data(tmp_path)
    result=backtest_learning_v2(tmp_path)
    assert {"samples","precision","recall","f1","hit_rate","mae","buckets"} <= result.keys()
    calibration=calibrate_learning_threshold(tmp_path)
    assert {"threshold","precision","recall","f1","samples"} <= calibration.keys()

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
    assert calibrate_confidence({"story_id":"x"},{"x":{"confidence":80,"verification":"multi-source","independent_sources":2}})>80
    assert adaptive_personalization({"category_weight":6},{"hit_rate":0.8})["category_weight"]==7

def test_backtest_v3_contract(tmp_path):
    from app.analytics import backtest_learning_v3
    from app.storage import ensure_data
    ensure_data(tmp_path)
    result=backtest_learning_v3(tmp_path)
    assert {"samples","hit_rate","precision","recall","f1","mae","temporal_stability"} <= result.keys()

def test_main_wires_advanced_v3():
    text=read("app/main.py")
    for item in ("apply_adaptive_threshold","diversify_stories","consolidate_event_families",
                 "learning_v3_snapshot","source_fallback_plan","breaking_fast_lane",
                 "calibrate_confidence","backtest_learning_v3"):
        assert item in text


def test_ops_and_final_audit_contract():
    from app.ops import confidence_snapshot,historical_trend,operational_health,final_audit
    stories=[{"region":"india","breaking_score":60,"calibrated_confidence":90,"verification":{"confidence":80}},
             {"region":"world","breaking_score":0,"calibrated_confidence":70,"verification":{"confidence":65}}]
    assert confidence_snapshot(stories)["high_confidence"]==1
    assert historical_trend([{"date":"2026-10-07","region":"world","event_status":"CONFIRMED"}])["stories"]==1
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


def test_operational_trend_uses_calendar_window():
    from app.ops import historical_trend
    result=historical_trend([
        {"date":"2020-01-01","region":"world"},
        {"date":"2099-01-01","region":"india"},
    ],days=7)
    assert result["stories"] <= 1


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
