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
        f"AI generated {stats.get('ai_generated',0)} · fallback {stats.get('ai_fallback',0)} · learning records {learning_total}",
        "",
        f"📡 <b>SYSTEM</b> · health {stats.get('health','UNKNOWN')} · runtime {stats.get('runtime')} · model {configured_model()}",
        f"Coverage gaps: {', '.join(stats.get('coverage_gaps') or []) or 'none'}",
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
    learning_v3=learning_v3_snapshot(read_rows(DATA/"news_learning.csv"))
    preferences=adaptive_personalization(preferences,learning_v3)
    candidates=personalize(candidates,preferences)
    candidates=prepare_candidates(candidates,read_rows(DATA/"news_history.csv"))
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
    from .analytics import calibrate_learning_threshold
    stats["learning_calibration"]=calibrate_learning_threshold(DATA)
    stats["quality_dashboard"]=quality_dashboard(DATA)
    stats["learning_v3"]=learning_v3
    stats["source_fallback"]=source_fallback_plan(stats["source_health"])
    stats["breaking_fast_lane"]=len(fast_lane)
    stats["learning_calibration"]=calibration
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
