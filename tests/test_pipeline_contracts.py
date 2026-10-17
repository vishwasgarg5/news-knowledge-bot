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
    assert "actions/upload-artifact@v7" in text
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
    stories=[{"headline":"India economy growth update","summary":"growth outlook","category":"economy","region":"india","importance":70,"impact":{"score":80}}]
    feed=personalized_feed(stories,prefs)
    assert feed and feed[0]["preference_matches"]>=2
    evidence=[{"title":"India economy growth update confirmed","source":"Reuters","url":"https://reuters.com/x","published":datetime.now(timezone.utc).isoformat()}]
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
    queue=autonomous_research([{"headline":"India market investment","impact":{"score":80},"momentum_score":20}],
                              evidence_pool=[{"title":"India market investment confirmed","source":"Reuters","url":"https://reuters.example","published":datetime.now(timezone.utc).isoformat()}])
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

def test_single_main_workflow_and_no_push_trigger_after_guardrail_changes():
    workflow=yaml.safe_load(read(".github/workflows/morning_news.yml"))
    triggers=workflow.get(True) or workflow.get("on") or {}
    assert "workflow_dispatch" in triggers and "schedule" in triggers
    assert "push" not in triggers and "pull_request" not in triggers
    assert "actions/upload-artifact@v7" in read(".github/workflows/morning_news.yml")


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
