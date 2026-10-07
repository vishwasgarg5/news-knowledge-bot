from __future__ import annotations
import json,os,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import yaml
from .ai import configured_model,generate_briefing,rerank_stories,select_stories
from .news import collect, _region
from .research import research_stories
from .settings import CONFIG,DATA,TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
from .storage import HEADERS,append_rows,ensure_data,read_rows,sync_sqlite
from .telegram import send_text
from .learning import evaluate_and_learn,apply_learning,learning_metrics
from .intelligence import enrich_trends,personalize,intelligence_summary
from .analytics import build_report,write_reports,backtest_learning_v2,backtest_learning_v3,quality_dashboard
from .quality import prepare_candidates,source_health,quality_snapshot,coverage_gaps,coverage_plan
from .advanced import adaptive_threshold,apply_adaptive_threshold,diversify_stories,consolidate_event_families,learning_v3_snapshot,source_fallback_plan,breaking_fast_lane,calibrate_confidence,adaptive_personalization
from .ops import confidence_snapshot,historical_trend,operational_health,final_audit
from .production import time_series_backtest,feedback_snapshot,feedback_adjustment,source_fallback_order,lifecycle_summary,monitoring_alerts,persist_operational_snapshot
from .intelligence_v5 import intelligence_v5
from .intelligence_v5_plus import run_v5_plus,answer_news_question,research_report
from .production_v5 import walk_forward_v5,shadow_ab_test,calibration_monitor,drift_monitor,autonomous_research_agent,generate_research_reports,contradiction_and_evidence,followup_research_plan,production_evaluation
from .intelligence_v4 import diagnose_learning,time_bucket_metrics,event_level_metrics,calibration_v2,source_category_profile,apply_intelligence_v4,feedback_learning,walk_forward_optimization,compare_strategies,production_decision,calibrated_score

IST=ZoneInfo("Asia/Kolkata"); RUN_SLOT=os.getenv("RUN_SLOT","manual").lower()

def _safe_float(v):
    try:return float(v)
    except:return 0.0

def load_preferences():
    p=CONFIG.parent/"preferences.yaml"
    if not p.exists(): return {}
    with p.open(encoding="utf-8") as f:return yaml.safe_load(f) or {}

def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f) or {}

def sim(a,b):
    x=set(re.findall(r"[a-z]{4,}",str(a).lower())); y=set(re.findall(r"[a-z]{4,}",str(b).lower()))
    return len(x&y)/max(1,len(x|y))

def normalize_regions(candidates, articles_by_url):
    """Recompute event geography from the actual headline/body before ranking.
    Feed category is not reliable enough for regional ordering."""
    out=[]
    for c in candidates:
        a=articles_by_url.get(str(c.get("url","")), {})
        region, confidence, evidence = _region(c.get("category",""), c.get("headline",""), a.get("summary",""))
        x=dict(c)
        x["region"]=region
        x["region_confidence"]=round(float(confidence or 0),2)
        x["region_evidence"]=evidence
        out.append(x)
    return out

def previous_change(stories,timeline,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat()
    old=[r.get("headline","") for r in timeline if r.get("date")==yesterday]
    for s in stories:s["change_since_yesterday"]="Continuing" if any(sim(s.get("headline",""),x)>=.48 for x in old) else "New today"
    return stories

def _history_line(story):
    history=(story.get("verification") or {}).get("historical") or []
    if not history:return "No close prior story"
    first=history[0]; title=str(first.get("title","")).strip(); title=title[:127].rstrip()+"..." if len(title)>130 else title
    return f"{first.get('date','prior')}: {title} · {first.get('source','memory')}"

def _event_status(story, timeline=None):
    v=story.get("verification") or {}
    headline=str(story.get("headline","") or "").lower()
    if any(x in headline for x in ("resolved","resolution","ended","ends","withdrawn","withdraws","settled","settlement")):
        return "RESOLVED"
    base="CONFIRMED" if v.get("verification")=="official-source" or int(v.get("independent_sources",0) or 0)>=2 else ("DEVELOPING" if int(v.get("independent_sources",0) or 0)>=1 else "NEW")
    prior=[]
    event_id=str(story.get("event_id","") or "")
    for row in (timeline or []):
        if event_id and str(row.get("event_id",""))==event_id: prior.append(row)
    if prior:
        old=max(float(x.get("importance",0) or 0) for x in prior)
        current=float(story.get("importance",0) or 0)
        old_status=str(max(prior,key=lambda x:float(x.get("importance",0) or 0)).get("event_status","") or "")
        if current-old>=8 and base in {"DEVELOPING","CONFIRMED"}: return "ESCALATING"
        if old_status=="ESCALATING" and base!="NEW": return "ESCALATING"
        if base=="CONFIRMED": return "CONFIRMED"
        return "DEVELOPING"
    return base

def persist(stories,today):
    path=DATA/"news_history.csv"; rows=read_rows(path); ids={r.get("story_id") for r in rows}
    tp=DATA/"story_timeline.csv"; timeline=read_rows(tp); keys={(r.get("story_id"),r.get("date")) for r in timeline}; added=0
    for s in stories:
        sid=s.get("story_id"); v=s.get("verification") or {}
        if sid and sid not in ids:
            append_rows(path,[{"date":today,"story_id":sid,"event_id":s.get("event_id",""),"headline":s.get("headline",""),"source":s.get("source",""),"url":s.get("url",""),"category":s.get("category",""),"importance":s.get("importance",0),"region":s.get("region","world"),"verification":v.get("verification",""),"confidence":v.get("confidence",""),"event_status":_event_status(s,timeline),"source_count":v.get("source_count",1)}],HEADERS["news_history.csv"]); ids.add(sid); added+=1
        if sid and (sid,today) not in keys:
            append_rows(tp,[{"story_id":sid,"event_id":s.get("event_id",""),"date":today,"headline":s.get("headline",""),"event":s.get("what",s.get("headline","")),"importance":s.get("importance",0),"source":s.get("source",""),"url":s.get("url",""),"change_type":s.get("change_since_yesterday",""),"event_status":_event_status(s,timeline)}],HEADERS["story_timeline.csv"]); keys.add((sid,today))
    return added

def _story_block(s,index,total):
    flag="🇮🇳" if s.get("region")=="india" else "🌍"; v=s.get("verification") or {}
    importance=float(s.get("importance",0) or 0); rank=float(s.get("ranking_score",importance) or importance)
    lines=[f"{flag} <b>#{index} · {s.get('category','NEWS').upper()} · {importance:.0f}/100</b>",f"<b>{s.get('headline','')}</b>"]
    if s.get("what"): lines += ["",f"<b>WHAT</b>\n{s.get('what')}"]
    if s.get("why") and str(s.get("why")).strip(): lines += ["",f"<b>WHY</b>\n{s.get('why')}"]
    if s.get("who") and str(s.get("who")).strip():
        lines += ["",f"<b>WHO</b>\n{s.get('who')}"]
    if s.get("who_detail") and str(s.get("who_detail")).lower() not in {"not stated in supplied sources","none"}:
        lines += ["",f"<b>PERSON / ROLE</b>\n{s.get('who_detail')}"]
    if s.get("how") and str(s.get("how")).lower() not in {"not stated in supplied sources","none"}:
        lines += ["",f"<b>HOW</b>\n{s.get('how')}"]
    if s.get("when") and str(s.get("when")).strip(): lines += ["",f"<b>WHEN</b>\n{s.get('when')}"]
    if s.get("where") and str(s.get("where")).strip(): lines += ["",f"<b>WHERE</b>\n{s.get('where')}"]
    if s.get("why_important") and str(s.get("why_important")).strip(): lines += ["",f"<b>IMPACT</b>\n{s.get('why_important')}"]
    key_data=str(s.get("key_data","")).strip()
    if key_data and key_data.upper() not in {"NONE","NOT STATED IN SUPPLIED SOURCES"}:
        lines += ["",f"<b>KEY DATA</b>\n{key_data}"]
    background=str(s.get("background","")).strip()
    if background and background.lower() not in {"not stated in supplied sources","none"}:
        lines += ["",f"<b>BACKGROUND</b>\n{background}"]
    history=v.get("historical") or []
    if history: lines += ["",f"<b>HISTORY</b>\n{_history_line(s)}"]
    change=s.get("change_since_yesterday")
    if change and change.lower() not in {"unknown","new today"}: lines += ["",f"<b>CHANGE</b>\n{change}"]
    if s.get("next") and str(s.get("next")).strip(): lines += ["",f"<b>NEXT</b>\n{s.get('next')}"]
    if s.get("connection") and str(s.get("connection")).lower() not in {"not stated in supplied sources","none"}:
        lines += ["",f"<b>CONNECTION</b>\n{s.get('connection')}"]
    if s.get("memory_hook") and str(s.get("memory_hook")).lower() not in {"not stated in supplied sources","none"}:
        lines += ["",f"<b>MEMORY</b>\n{s.get('memory_hook')}"]
    verification=v.get("verification","unverified")
    confidence=v.get("confidence","n/a")
    sources=v.get("source_count",0)
    if v.get("contradiction_flag"):
        status="⚠️ CONFLICTING REPORTS"
    elif verification=="unverified":
        status="SINGLE SOURCE / PENDING" if sources==1 else "UNVERIFIED"
    elif verification=="single-source":
        status="SINGLE SOURCE"
    elif verification=="multi-report":
        status="CONFIRMED · 1 INDEPENDENT SOURCE"
    elif verification=="multi-source":
        status="CONFIRMED · MULTI-SOURCE"
    elif verification=="official-source":
        status="OFFICIAL SOURCE"
    else:
        status=str(verification).upper()
    ai="AI" if s.get("ai_generated") else "FALLBACK"
    lines += ["",f"🔎 {status} · {confidence}% · {sources} source{'s' if sources!=1 else ''} · {ai}"]
    if verification=="unverified" and sources==1:
        lines += ["", "<b>VERIFICATION</b>\nCredible single-source report; independent confirmation is pending. This does not mean the report is false."]
    return "\n".join(lines)

def _vocab_block(s,index):
    vocab=str(s.get("vocabulary","")).strip()
    if not vocab or vocab.upper()=="NONE":return None
    terms=[]
    for raw in re.split(r"\s*;\s*|\s*\|\s*\n",vocab):
        raw=raw.strip(" -•")
        if raw and raw.upper()!="NONE":terms.append(raw)
    return "\n".join([f"📚 <b>VOCABULARY · #{index}</b>"]+[f"{n}. {term}" for n,term in enumerate(terms[:3],1)]) if terms else None

def _status_label(story):
    v=story.get("verification") or {}
    if v.get("contradiction_flag"): return "⚠️ CONFLICT"
    verification=str(v.get("verification","unverified"))
    if verification=="multi-source": return "STRONG"
    if verification=="official-source": return "OFFICIAL"
    if verification=="multi-report": return "CORROBORATED"
    if verification=="single-source": return "SINGLE SOURCE"
    return "UNVERIFIED"


def _executive_summary(stories):
    if not stories:
        return "No story passed the final quality gate."
    top=sorted(stories,key=lambda x:float(x.get("importance",0) or 0),reverse=True)[:3]
    return " · ".join(str(x.get("headline","")).strip() for x in top)


def _daily_comparison(stories, timeline, today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat()
    old=[r for r in timeline if r.get("date")==yesterday]
    continuing=sum(1 for s in stories if s.get("change_since_yesterday")=="Continuing")
    new=max(0,len(stories)-continuing)
    old_regions={"india":0,"world":0}
    for r in old:
        region=str(r.get("region","world")).lower()
        old_regions["india" if region=="india" else "world"]+=1
    return {
        "yesterday_stories":len(old),
        "new":new,
        "continuing":continuing,
        "india_delta":sum(1 for s in stories if s.get("region")=="india")-old_regions["india"],
        "world_delta":sum(1 for s in stories if s.get("region")!="india")-old_regions["world"],
    }


def _story_block(s,index,total):
    flag="🇮🇳" if s.get("region")=="india" else "🌍"; v=s.get("verification") or {}
    importance=float(s.get("importance",0) or 0)
    lines=[f"{flag} <b>#{index} · {s.get('category','NEWS').upper()} · {importance:.0f}/100 · {_status_label(s)}</b>",f"<b>{s.get('headline','')}</b>"]
    if s.get("what"): lines += ["",f"<b>WHAT</b>\n{s.get('what')}"]
    if s.get("why") and str(s.get("why")).strip(): lines += ["",f"<b>WHY</b>\n{s.get('why')}"]
    if s.get("who") and str(s.get("who")).strip(): lines += ["",f"<b>WHO</b>\n{s.get('who')}"]
    if s.get("who_detail") and str(s.get("who_detail")).lower() not in {"not stated in supplied sources","none"}: lines += ["",f"<b>PERSON / ROLE</b>\n{s.get('who_detail')}"]
    if s.get("how") and str(s.get("how")).lower() not in {"not stated in supplied sources","none"}: lines += ["",f"<b>HOW</b>\n{s.get('how')}"]
    if s.get("when") and str(s.get("when")).strip(): lines += ["",f"<b>WHEN</b>\n{s.get('when')}"]
    if s.get("where") and str(s.get("where")).strip(): lines += ["",f"<b>WHERE</b>\n{s.get('where')}"]
    if s.get("why_important") and str(s.get("why_important")).strip(): lines += ["",f"<b>IMPACT</b>\n{s.get('why_important')}"]
    key_data=str(s.get("key_data","")).strip()
    if key_data and key_data.upper() not in {"NONE","NOT STATED IN SUPPLIED SOURCES"}: lines += ["",f"<b>KEY DATA</b>\n{key_data}"]
    background=str(s.get("background","")).strip()
    if background and background.lower() not in {"not stated in supplied sources","none"}: lines += ["",f"<b>BACKGROUND</b>\n{background}"]
    history=v.get("historical") or []
    if history: lines += ["",f"<b>HISTORY</b>\n{_history_line(s)}"]
    change=s.get("change_since_yesterday")
    if change and change.lower() not in {"unknown","new today"}: lines += ["",f"<b>CHANGE</b>\n{change}"]
    if s.get("next") and str(s.get("next")).strip(): lines += ["",f"<b>NEXT</b>\n{s.get('next')}"]
    if s.get("connection") and str(s.get("connection")).lower() not in {"not stated in supplied sources","none"}: lines += ["",f"<b>CONNECTION</b>\n{s.get('connection')}"]
    if s.get("memory_hook") and str(s.get("memory_hook")).lower() not in {"not stated in supplied sources","none"}: lines += ["",f"<b>MEMORY</b>\n{s.get('memory_hook')}"]
    confidence=v.get("confidence","n/a"); sources=v.get("source_count",0)
    lines += ["",f"🔎 {_status_label(s)} · confidence {confidence}% · {sources} source{'s' if sources!=1 else ''} · {'AI' if s.get('ai_generated') else 'FALLBACK'}"]
    if v.get("contradiction_flag"):
        lines += ["<b>VERIFICATION NOTE</b>\nConflicting evidence was detected; treat the story as provisional."]
    elif str(v.get("verification"))=="single-source":
        lines += ["<b>VERIFICATION NOTE</b>\nCredible single-source report; independent confirmation is pending."]
    return "\n".join(lines)


def _vocab_block(s,index):
    vocab=str(s.get("vocabulary","")).strip()
    if not vocab or vocab.upper()=="NONE": return None
    terms=[]
    for raw in re.split(r"\s*;\s*|\s*\|\s*\n",vocab):
        raw=raw.strip(" -•")
        if raw and raw.upper()!="NONE": terms.append(raw)
    return "\n".join([f"📚 <b>VOCABULARY · #{index}</b>"]+[f"{n}. {term}" for n,term in enumerate(terms[:3],1)]) if terms else None


def build_messages(result,today,stats,timeline=None):
    stories=list(result.get("top_stories",[]))
    timeline=timeline or []
    stories=sorted(stories,key=lambda x:float(x.get("importance",0) or 0),reverse=True)
    india=[s for s in stories if s.get("region")=="india"]
    world=[s for s in stories if s.get("region")!="india"]
    breaking=[s for s in stories if s.get("breaking_score",0) >= 50]
    conflicts=[s for s in stories if (s.get("verification") or {}).get("contradiction_flag")]
    strong=sum(1 for s in stories if _status_label(s) in {"STRONG","OFFICIAL"})
    comparison=_daily_comparison(stories,timeline,today)
    analytics=stats.get("analytics") or {}
    weekly=analytics.get("last_7_days") or {}
    learning_total=max(1,int(stats.get("learning_labeled",0) or 0))
    miss_rate=float(stats.get("learning_miss_rate",0) or 0)
    fp_rate=float(stats.get("learning_fp_rate",0) or 0)

    header=[
        f"📰 <b>DAILY NEWS INTELLIGENCE · {RUN_SLOT.upper()}</b>",
        f"📅 {today}",
        "",
        "🎯 <b>EXECUTIVE SUMMARY</b>",
        _executive_summary(stories),
        "",
        f"🔥 Stories {len(stories)} · 🔴 Breaking {len(breaking)} · ⭐ Strong {strong} · ⚠️ Conflicts {len(conflicts)}",
        f"🇮🇳 India {len(india)} · 🌍 World {len(world)} · 🆕 New {comparison['new']} · 🔄 Continuing {comparison['continuing']}",
        f"📈 Yesterday {comparison['yesterday_stories']} · India Δ {comparison['india_delta']:+d} · World Δ {comparison['world_delta']:+d}",
        "",
        "🧪 <b>QUALITY & VERIFICATION</b>",
        f"Coverage {stats.get('current_evidence',0)}/{stats.get('total',0)} · Strong {stats.get('strong_verified',0)}/{stats.get('total',0)} · Contradictions {stats.get('contradictions',0)}",
        f"Sources {stats.get('source_ok',0)}/{stats.get('source_total',0)} healthy · warnings {stats.get('source_warnings',0)} · failures {stats.get('source_failures',0)}",
        f"Candidates {stats.get('candidates',0)} · filtered duplicates {stats.get('exact_duplicates',0)} · semantic {stats.get('semantic_filtered',0)}",
        "",
        "🧠 <b>LEARNING PERFORMANCE</b>",
        f"Evaluated {stats.get('learning_labeled',0)} · success {stats.get('learning_success_rate',0):.0%} · miss {miss_rate:.1%} · false-positive {fp_rate:.1%}",
        f"7-day runs {weekly.get('runs',0)} · avg success {float(weekly.get('avg_success_rate',0) or 0):.1%} · avg miss {float(weekly.get('avg_miss_rate',0) or 0):.1%}",
        f"Backtest hit {float((stats.get('backtest_v2') or {}).get('hit_rate',0)):.1%} · precision {float((stats.get('backtest_v2') or {}).get('precision',0)):.1%} · recall {float((stats.get('backtest_v2') or {}).get('recall',0)):.1%}",
        f"Adaptive threshold {stats.get('importance_threshold',62):.0f} · calibration F1 {float((stats.get('learning_calibration') or {}).get('f1',0)):.1%}",
        f"Confidence calibrated {float((stats.get('confidence_snapshot') or {}).get('avg_calibrated',0)):.1f} · high {int((stats.get('confidence_snapshot') or {}).get('high_confidence',0))}",
        f"7-day history {int((stats.get('historical_trend') or {}).get('stories',0))} stories · health {(stats.get('operational_health') or {}).get('status','UNKNOWN')}",
        f"Backtest V3 stability {float((stats.get('backtest_v3') or {}).get('temporal_stability',0)):.1%} · breaking fast-lane {stats.get('breaking_fast_lane',0)}",
        f"V4 event F1 {float((stats.get('intelligence_v4_event_level') or {}).get('f1',0)):.1%} · walk-forward F1 {float((stats.get('walk_forward_v4') or {}).get('f1',0)):.1%}",
        f"V4 decision {(stats.get('production_decision') or {}).get('status','HOLD')} · feedback net {int((stats.get('intelligence_v4_feedback') or {}).get('net',0))}",
        f"V5+ scorecard · high impact {int((stats.get('intelligence_scorecard') or {}).get('high_impact',0))} · early signals {int((stats.get('intelligence_scorecard') or {}).get('early_signals',0))} · verified {int((stats.get('intelligence_scorecard') or {}).get('verified',0))}",
        f"🚨 Smart alerts {len(stats.get('smart_alerts') or [])} · research queue {len(stats.get('research_queue') or [])} · evidence gaps {len(stats.get('evidence_gaps') or [])}",
        f"🔗 Knowledge graph nodes {len((stats.get('knowledge_graph') or {}).get('nodes',[]))} · edges {len((stats.get('knowledge_graph') or {}).get('edges',[]))} · anomalies {len((stats.get('weekly_intelligence') or {}).get('anomalies',[]))}",
        f"AI generated {stats.get('ai_generated',0)} · fallback {stats.get('ai_fallback',0)} · learning records {learning_total}",
        "",
        f"📡 <b>SYSTEM</b> · health {stats.get('health','UNKNOWN')} · runtime {stats.get('runtime')} · model {configured_model()}",
        f"Coverage gaps: {', '.join(stats.get('coverage_gaps') or []) or 'none'}",
        f"Fallback sources: {len((stats.get('source_fallback') or {}).get('weak_sources',[]))}",
        f"Final audit: {(stats.get('final_audit') or {}).get('health','UNKNOWN')}",
    ]
    messages=["\n".join(header)]
    if breaking:
        messages.append("🔴 <b>BREAKING / FAST-MOVING</b>\n" + "\n".join(f"• {s.get('headline','')} · {float(s.get('importance',0) or 0):.0f}/100" for s in breaking[:5]))
    if india:
        messages.append("🇮🇳 <b>INDIA</b>\n" + "\n".join(f"• {s.get('headline','')} · {float(s.get('importance',0) or 0):.0f}/100 · {_status_label(s)}" for s in india))
    if world:
        messages.append("🌍 <b>WORLD</b>\n" + "\n".join(f"• {s.get('headline','')} · {float(s.get('importance',0) or 0):.0f}/100 · {_status_label(s)}" for s in world))
    messages.append("👇 <b>DETAILED STORIES</b>")
    for i,s in enumerate(stories,1):
        messages.append(_story_block(s,i,len(stories)))
        vocab=_vocab_block(s,i)
        if vocab: messages.append(vocab)
    return messages

def main():
    started=time.monotonic(); ensure_data(DATA); cfg=load_sources(); limits=cfg.get("limits",{})
    articles,cstats=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",40),limits.get("max_total_articles",700))
    today=datetime.now(IST).date().isoformat(); preferences=load_preferences(); timeline=read_rows(DATA/"story_timeline.csv"); all_articles=[a.__dict__ for a in articles]
    feedback=feedback_snapshot(DATA); feedback_adj=feedback_adjustment(feedback)
    from .analytics import calibrate_learning_threshold
    calibration=calibrate_learning_threshold(DATA)
    production_floor=float(os.getenv("NEWS_MIN_IMPORTANCE","62")); adaptive=apply_adaptive_threshold(calibration,production_floor)
    os.environ["NEWS_MIN_IMPORTANCE"]=str(int(adaptive))
    print(f"[LEARNING] calibrated_threshold={calibration.get('threshold')} production_threshold={adaptive}",flush=True)
    candidate_limit=max(1,int(os.getenv("NEWS_CANDIDATE_LIMIT","700")))
    candidates=select_stories(all_articles,top_n=candidate_limit,excluded_headlines=[])

    # Evaluate only mature historical records here. Do not record today's run yet.
    learning_stats=evaluate_and_learn(DATA,candidates,today)
    candidates=apply_learning(candidates,learning_stats.get("profile",{})); candidates=normalize_regions(candidates,{a.get("url"):a for a in all_articles}); candidates=previous_change(candidates,timeline,today); candidates=enrich_trends(candidates,read_rows(DATA/"news_history.csv"))
    learning_rows=read_rows(DATA/"news_learning.csv")
    learning_v3=learning_v3_snapshot(learning_rows)
    preferences=adaptive_personalization(preferences,learning_v3)
    candidates=personalize(candidates,preferences)
    v4_calibration=calibration_v2(learning_rows,today)
    v4_profile=source_category_profile(learning_rows,today)
    v4_feedback=feedback_learning(learning_rows,read_rows(DATA/"news_feedback.csv"),today)
    for x in candidates:
        x['feedback_adjustment']=feedback_adj['ranking_delta'] + v4_feedback['bounded_delta']
        x['personalized_score']=max(0.0,float(x.get('personalized_score',x.get('importance',0)) or 0)+x['feedback_adjustment'])
    candidates=prepare_candidates(candidates,read_rows(DATA/"news_history.csv"))
    candidates=apply_intelligence_v4(candidates,v4_profile,v4_calibration)
    plan=coverage_plan(candidates,world_target=int(os.getenv("NEWS_WORLD_TOP","5")),india_target=int(os.getenv("NEWS_INDIA_TOP","5")))
    print(f"[INTELLIGENCE] coverage_gaps={coverage_gaps(candidates)} plan={plan}",flush=True)

    research=research_stories(candidates,timeline,all_articles); research_stats=research.get("_stats",{}); research.pop("_stats",None)
    selected=rerank_stories(candidates,research)
    selected=consolidate_event_families(selected)
    selected=diversify_stories(selected,max_total=int(os.getenv("NEWS_MAX_STORIES","10")),india_target=int(os.getenv("NEWS_INDIA_TOP","5")),world_target=int(os.getenv("NEWS_WORLD_TOP","5")),max_per_source=int(os.getenv("NEWS_MAX_STORIES_PER_SOURCE","2")))
    fast_lane=breaking_fast_lane(selected)
    result=generate_briefing(selected,all_articles,timeline,today,research)
    source_by_url={a.get("url"):a.get("source","") for a in all_articles}
    for s in result.get("top_stories",[]):
        s["verification"]=research.get(s.get("story_id"),{})
        s["calibrated_confidence"]=calibrate_confidence(s,research)
        v=s.get("verification") or {}; v["calibrated_confidence"]=s["calibrated_confidence"]; s["verification"]=v
        s["source"]=source_by_url.get(s.get("url"),s.get("source",""))

    current_ids={s.get("story_id") for s in result.get("top_stories",[])}
    current_research=[research.get(sid,{}) for sid in current_ids]
    current_evidence=sum(1 for r in current_research if r.get("verification") in {"multi-source","multi-report","official-source","single-source"})
    current_verified=sum(1 for r in current_research if r.get("verification") in {"multi-source","official-source","single-source"})
    strong_verified=sum(1 for r in current_research if r.get("verification") in {"multi-source","official-source"})
    total_selected=len(result.get("top_stories",[]))
    current_coverage=current_evidence/max(1,total_selected)
    source_failures=cstats.get("source_failures",0)
    source_warnings=cstats.get("source_warnings",0)

    # Final story-quality gate: never send malformed/duplicate/under-threshold stories.
    clean=[]; seen_ids=set(); seen_urls=set()
    for s in result.get("top_stories",[]):
        sid=str(s.get("story_id","")).strip(); url=str(s.get("url","")).strip()
        imp=_safe_float(s.get("importance",0))
        if not sid or not url or sid in seen_ids or url in seen_urls or imp < float(os.getenv("NEWS_MIN_IMPORTANCE","62")):
            continue
        if str(s.get("region","")).lower() not in {"india","world"}: continue
        if not str(s.get("headline","")).strip(): continue
        if not (research.get(sid) or {}).get("verification"): continue
        seen_ids.add(sid); seen_urls.add(url); clean.append(s)
    result["top_stories"]=clean
    current_ids={s.get("story_id") for s in clean}
    current_research=[research.get(sid,{}) for sid in current_ids]
    current_evidence=sum(1 for r in current_research if r.get("verification") in {"multi-source","multi-report","official-source","single-source"})
    current_verified=sum(1 for r in current_research if r.get("verification") in {"multi-source","official-source","single-source"})
    strong_verified=sum(1 for r in current_research if r.get("verification") in {"multi-source","official-source"})
    total_selected=len(clean)
    current_coverage=current_evidence/max(1,total_selected)

    # Learning is recorded only when source collection is clean and fresh verification is adequate.
    quality_ok=(source_failures==0 and source_warnings==0 and current_coverage>=0.50)
    final_learning=evaluate_and_learn(DATA,candidates,today,selected_ids=current_ids,record_current=quality_ok)
    added=persist(result.get("top_stories",[]),today)
    db=sync_sqlite(DATA)
    from .storage import validate_data
    data_quality=validate_data(DATA)
    if not data_quality["ok"]: print(f"[WARN] data integrity issues: {data_quality['issues']}",flush=True)
    lm=learning_metrics(read_rows(DATA/"news_learning.csv"))

    intel=intelligence_summary(result.get("top_stories",[]))
    stats={"data_quality":data_quality,"db_path":str(db),"importance_threshold":float(os.getenv("NEWS_MIN_IMPORTANCE","62")),"articles":cstats.get("scanned",len(articles)),"candidates":len(candidates),"exact_duplicates":cstats.get("exact_duplicates",0),"semantic_filtered":cstats.get("semantic_filtered",0),"source_failures":source_failures,"source_warnings":cstats.get("source_warnings",0),"source_total":len(cstats.get("source_status") or []),"source_ok":sum(1 for x in (cstats.get("source_status") or []) if x.get("ok")),"stories":total_selected,"current_evidence":current_evidence,"verified":current_verified,"strong_verified":strong_verified,"total":total_selected,"runtime":f"{time.monotonic()-started:.1f}s","learning_labeled":final_learning.get("evaluated",0),"learning_misses":final_learning.get("misses",0),"learning_false_positives":final_learning.get("false_positives",0),"learning_success_rate":lm.get("success_rate",0),"failed_sources":[str(x.get("url","")).split("//")[-1].split("/")[0] for x in (cstats.get("source_status") or []) if not x.get("ok")],"learning_fp_rate":lm.get("false_positive_rate",0),"learning_miss_rate":lm.get("miss_rate",0),"ai_generated":sum(1 for s in result.get("top_stories",[]) if s.get("ai_generated")),"ai_fallback":sum(1 for s in result.get("top_stories",[]) if not s.get("ai_generated")),
"contradictions":sum(1 for s in result.get("top_stories",[]) if (s.get("verification") or {}).get("contradiction_flag")),"contradiction_evidence":sum(len((s.get("verification") or {}).get("contradiction_evidence") or []) for s in result.get("top_stories",[])),"breaking_stories":intel["breaking"],"emerging_topics":intel["emerging"],"avg_personalized_score":intel["avg_personalized"]}
    stats["health"]="PASS" if source_failures==0 and source_warnings==0 and current_coverage>=0.50 and strong_verified/max(1,total_selected)>=0.30 else ("WARN" if current_coverage>=0.20 and source_failures<=2 else "DEGRADED")

    # Keep an exact, machine-readable snapshot of the final briefing outside the
    # repository. The workflow uploads this snapshot as an artifact so content
    # quality can be audited after every run instead of relying only on counters.
    audit_path="/tmp/news_briefing.json"
    try:
        audit={"date":today,"run_slot":RUN_SLOT,"stats":stats,"analytics":build_report(DATA),"stories":result.get("top_stories",[])}
        with open(audit_path,"w",encoding="utf-8") as fh:
            json.dump(audit,fh,ensure_ascii=False,indent=2)
        print("[AUDIT] FINAL STORY SNAPSHOT",flush=True)
        for i,s in enumerate(result.get("top_stories",[]),1):
            v=s.get("verification") or {}
            print(f"[AUDIT] #{i:02d} | {s.get('region','')} | {float(s.get('importance',0) or 0):.1f} | {v.get('verification','')} | {s.get('headline','')}",flush=True)
    except Exception as exc:
        print(f"[WARN] audit snapshot failed: {exc}",flush=True)

    daily_path=DATA/"news_learning_daily.csv"; daily_rows=read_rows(daily_path)
    if quality_ok and not any(r.get("date")==today for r in daily_rows):
        append_rows(daily_path,[{"date":today,"evaluated":final_learning.get("evaluated",0),"selected_evaluated":final_learning.get("selected_evaluated",0),"misses":final_learning.get("misses",0),"false_positives":final_learning.get("false_positives",0),"success_rate":lm.get("success_rate",0),"false_positive_rate":lm.get("false_positive_rate",0),"miss_rate":lm.get("miss_rate",0)}],HEADERS["news_learning_daily.csv"])

    report=write_reports(DATA)
    stats["analytics"]=report
    stats["quality_snapshot"]=quality_snapshot(result.get("top_stories",[]),research)
    stats["coverage_gaps"]=coverage_gaps(candidates)
    stats["coverage_plan"]=plan
    stats["source_health"]=source_health(candidates)
    stats["backtest_v2"]=backtest_learning_v2(DATA)
    stats["backtest_v3"]=backtest_learning_v3(DATA)
    stats["backtest_v4"]=time_series_backtest(read_rows(DATA/"news_learning.csv"))
    stats["intelligence_v4_diagnosis"]=diagnose_learning(learning_rows,today)
    stats["intelligence_v4_dimensions"]=time_bucket_metrics(learning_rows,today)
    stats["intelligence_v4_event_level"]=event_level_metrics(learning_rows,today)
    stats["intelligence_v4_calibration"]=v4_calibration
    stats["intelligence_v4_profile"]=v4_profile
    stats["intelligence_v4_feedback"]=v4_feedback
    stats["walk_forward_v4"]=walk_forward_optimization(learning_rows)
    stats["strategy_comparison"]=compare_strategies(learning_rows)
    stats["production_decision"]=production_decision(stats["strategy_comparison"])
    v5=intelligence_v5(result.get("top_stories",[]),read_rows(DATA/"news_history.csv"),stats)
    stats["intelligence_v5"]=v5
    v5plus=run_v5_plus(v5.get("stories",result.get("top_stories",[])),read_rows(DATA/"news_history.csv"),learning_rows,read_rows(DATA/"news_feedback.csv"),preferences,stats,[])
    stats["intelligence_v5_plus"]=v5plus
    stats["entity_profiles"]=v5plus["entity_profiles"]
    stats["event_clusters"]=v5plus["clusters"]
    stats["event_evolution"]=v5plus["event_evolution"]
    stats["impact_learning"]=v5plus["impact_learning"]
    stats["market_correlation"]=v5plus["market_correlation"]
    stats["source_event_reliability"]=v5plus["source_reliability"]
    stats["advanced_feedback"]=v5plus["feedback"]
    stats["intelligence_scorecard"]=v5plus["scorecard"]
    stats["personalized_feed"]=v5plus["personalized_feed"]
    stats["smart_alerts"]=v5plus["alerts"]
    stats["trend_report"]=v5plus["trend_report"]
    stats["knowledge_graph"]=v5plus["knowledge_graph"]
    stats["contradiction_scan"]=v5plus["contradictions"]
    stats["evidence_gaps"]=v5plus["evidence_gaps"]
    stats["research_queue"]=v5plus["research_queue"]
    stats["weekly_intelligence"]=v5plus["weekly_report"]
    v5_wf=walk_forward_v5(learning_rows)
    v5_ab=shadow_ab_test(learning_rows,learning_rows)
    v5_calibration=calibration_monitor(learning_rows)
    v5_drift=drift_monitor(v5plus["stories"],read_rows(DATA/"news_history.csv"))
    v5_evidence=contradiction_and_evidence(v5plus["stories"])
    v5_followups=followup_research_plan(v5plus["stories"])
    v5_agent=autonomous_research_agent(v5plus["research_queue"],read_rows(DATA/"news_history.csv"))
    v5_reports=generate_research_reports(v5_agent)
    v5_eval=production_evaluation(learning_rows,learning_rows,v5plus["stories"],read_rows(DATA/"news_history.csv"))
    stats["v5_walk_forward"]=v5_wf
    stats["v5_ab_test"]=v5_ab
    stats["v5_calibration"]=v5_calibration
    stats["v5_drift"]=v5_drift
    stats["v5_evidence"]=v5_evidence
    stats["v5_followups"]=v5_followups
    stats["v5_research_agent"]=v5_agent
    stats["v5_research_reports"]=v5_reports
    stats["v5_production_evaluation"]=v5_eval

    for s in result.get("top_stories",[]):
        s["event_id"]=s.get("event_id") or next((x.get("event_id") for x in v5plus["stories"] if x.get("headline")==s.get("headline")), "")
        match=next((x for x in v5plus["stories"] if x.get("headline")==s.get("headline")),None)
        if match:
            for k in ("impact","momentum_score","early_signal","similar_historical_events"):
                if k in match:s[k]=match[k]
    today_rows=[{"date":today,**p} for p in v5plus["entity_profiles"]]
    append_rows(DATA/"entity_memory.csv",today_rows,HEADERS["entity_memory.csv"])
    append_rows(DATA/"event_memory.csv",[{"date":today,"event_id":e["event_id"],"headline":e["headline"],"status":e["status"],"story_count":e["story_count"],"source_count":len(e["sources"])} for e in v5plus["event_evolution"]],HEADERS["event_memory.csv"])
    append_rows(DATA/"knowledge_edges.csv",[{"date":today,"from_node":e["from"],"to_node":e["to"],"edge_type":e["type"]} for e in v5plus["knowledge_graph"]["edges"]],HEADERS["knowledge_edges.csv"])
    rr=research_report(v5plus["stories"],v5plus["research_queue"])
    append_rows(DATA/"research_reports.csv",[{"date":today,"headline":x["headline"],"priority":x["priority"],"finding":x["finding"]} for x in rr["sections"]],HEADERS["research_reports.csv"])

    stats["impact_summary"]={"high":sum(1 for s in v5plus["stories"] if s["impact"]["level"]=="HIGH"),"medium":sum(1 for s in v5plus["stories"] if s["impact"]["level"]=="MEDIUM"),"low":sum(1 for s in v5plus["stories"] if s["impact"]["level"]=="LOW")}
    stats["entity_summary"]=v5plus["entities"]
    stats["cross_event_links"]=v5["cross_event_links"]
    stats["source_event_matrix"]=v5["source_event_matrix"]

    from .analytics import calibrate_learning_threshold
    stats["learning_calibration"]=calibrate_learning_threshold(DATA)
    stats["quality_dashboard"]=quality_dashboard(DATA)
    stats["confidence_snapshot"]=confidence_snapshot(result.get("top_stories",[]))
    stats["historical_trend"]=historical_trend(read_rows(DATA/"news_history.csv"),7)
    stats["operational_health"]=operational_health(stats)
    stats["final_audit"]=final_audit(stats,result.get("top_stories",[]))
    stats["learning_v3"]=learning_v3
    stats["source_fallback"]=source_fallback_plan(stats["source_health"])
    stats["breaking_fast_lane"]=len(fast_lane)
    stats["feedback"]=feedback
    stats["feedback_adjustment"]=feedback_adj
    stats["lifecycle"]=lifecycle_summary(read_rows(DATA/"story_timeline.csv"))
    stats["india_stories"]=sum(1 for s in result.get("top_stories",[]) if s.get("region")=="india")
    stats["world_stories"]=sum(1 for s in result.get("top_stories",[]) if s.get("region")=="world")
    stats["india_target"]=int(os.getenv("NEWS_INDIA_TOP","5")); stats["world_target"]=int(os.getenv("NEWS_WORLD_TOP","5"))
    stats["source_fallback_order"]=source_fallback_order(stats["source_health"])
    stats["monitoring_alerts"]=monitoring_alerts(stats)
    stats["learning_calibration"]=calibration
    persist_operational_snapshot(DATA,{"date":today,"health":stats.get("health"),"operational_health":stats.get("operational_health"),"source_health":stats.get("source_health"),"fallback_order":stats.get("source_fallback_order"),"alerts":stats.get("monitoring_alerts"),"backtest_v4":stats.get("backtest_v4"),"intelligence_v4":stats.get("strategy_comparison"),"production_decision":stats.get("production_decision"),"intelligence_v5":stats.get("intelligence_v5"),"intelligence_v5_plus":stats.get("intelligence_v5_plus"),"smart_alerts":stats.get("smart_alerts"),"evidence_gaps":stats.get("evidence_gaps"),"v5_production_evaluation":stats.get("v5_production_evaluation"),"v5_drift":stats.get("v5_drift"),"v5_calibration":stats.get("v5_calibration")})
    # Refresh the uploaded audit only after every final stat has been populated.
    try:
        audit={"date":today,"run_slot":RUN_SLOT,"stats":stats,"analytics":build_report(DATA),"stories":result.get("top_stories",[])}
        with open(audit_path,"w",encoding="utf-8") as fh: json.dump(audit,fh,ensure_ascii=False,indent=2)
        print("[AUDIT] FINAL AUDIT REFRESHED",flush=True)
    except Exception as exc: print(f"[WARN] final audit refresh failed: {exc}",flush=True)
    print(f"[ANALYTICS] samples={report['learning_samples']} avg_outcome={report['avg_outcome']} top_categories={report['top_categories'][:5]}",flush=True)
    print(f"[PASS] FINAL NEWS INTELLIGENCE | candidates={stats['candidates']} | stories={stats['stories']} | current_verified={current_verified}/{total_selected} | strong={strong_verified}/{total_selected} | learning={stats['learning_labeled']} | source_failures={source_failures} | source_warnings={source_warnings} | health={stats['health']} | learning_recorded={'yes' if quality_ok else 'no'} | new={added}",flush=True)
    for failure in (cstats.get("source_status") or []):
        if not failure.get("ok"): print(f"[WARN] source failed | category={failure.get('category','')} | url={failure.get('url','')} | error={failure.get('error','')}",flush=True)
    for warning in (cstats.get("source_status") or []):
        if warning.get("warning"): print(f"[WARN] source recovered with parser warning | category={warning.get('category','')} | url={warning.get('url','')} | warning={warning.get('error','')}",flush=True)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            for m in build_messages(result,today,stats,timeline): send_text(m)
        except Exception as exc:
            print(f"[WARN] Telegram full briefing failed: {exc}",flush=True)
            fallback=["📰 <b>NEWS INTELLIGENCE · FALLBACK</b>","",f"📊 Candidates {stats['candidates']} · Stories {stats['stories']}",f"🔎 Verified {stats['verified']}/{stats['total']} · Strong {stats['strong_verified']}/{stats['total']}",f"📡 Sources {stats.get('source_ok',0)}/{stats.get('source_total',0)} · {stats.get('health','DEGRADED')}","","<b>TOP STORIES</b>"]
            for i,s in enumerate(sorted(result.get("top_stories",[]),key=lambda x:float(x.get("importance",0) or 0),reverse=True)[:10],1):
                fallback.append(f"{i}. <b>{s.get('headline','')}</b> · {float(s.get('importance',0) or 0):.0f}/100")
            try: send_text("\n".join(fallback))
            except Exception as fallback_exc: print(f"[ERROR] Telegram fallback failed: {fallback_exc}",flush=True)

if __name__=="__main__":main()
