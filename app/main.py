from __future__ import annotations
import os,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import yaml
from .ai import configured_model,generate_briefing,rerank_stories,select_stories
from .news import collect
from .research import research_stories
from .settings import CONFIG,DATA,TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
from .storage import HEADERS,append_rows,ensure_data,read_rows
from .telegram import send_text
from .learning import evaluate_and_learn,apply_learning,learning_metrics

IST=ZoneInfo("Asia/Kolkata"); RUN_SLOT=os.getenv("RUN_SLOT","manual").lower()
def _safe_float(v):
    try:return float(v)
    except:return 0.0
def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f) or {}
def sim(a,b):
    x=set(re.findall(r"[a-z]{4,}",str(a).lower())); y=set(re.findall(r"[a-z]{4,}",str(b).lower())); return len(x&y)/max(1,len(x|y))
def previous_change(stories,timeline,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat(); old=[r.get("headline","") for r in timeline if r.get("date")==yesterday]
    for s in stories:s["change_since_yesterday"]="Continuing" if any(sim(s.get("headline",""),x)>=.48 for x in old) else "New today"
    return stories
def _history_line(story):
    history=(story.get("verification") or {}).get("historical") or []
    if not history:return "No close prior story"
    first=history[0]; title=str(first.get("title","")).strip(); title=title[:127].rstrip()+"..." if len(title)>130 else title
    return f"{first.get('date','prior')}: {title} · {first.get('source','memory')}"
def persist(stories,today):
    path=DATA/"news_history.csv"; rows=read_rows(path); ids={r.get("story_id") for r in rows}; tp=DATA/"story_timeline.csv"; timeline=read_rows(tp); keys={(r.get("story_id"),r.get("date")) for r in timeline}; added=0
    for s in stories:
        sid=s.get("story_id"); v=s.get("verification") or {}
        if sid and sid not in ids:
            append_rows(path,[{"date":today,"story_id":sid,"event_id":s.get("event_id",""),"headline":s.get("headline",""),"source":s.get("source",""),"url":s.get("url",""),"category":s.get("category",""),"importance":s.get("importance",0),"region":s.get("region","world"),"verification":v.get("verification",""),"confidence":v.get("confidence","")}],HEADERS["news_history.csv"]); ids.add(sid); added+=1
        if sid and (sid,today) not in keys:
            append_rows(tp,[{"story_id":sid,"event_id":s.get("event_id",""),"date":today,"headline":s.get("headline",""),"event":s.get("what",s.get("headline","")),"importance":s.get("importance",0),"source":s.get("source",""),"url":s.get("url",""),"change_type":s.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]); keys.add((sid,today))
    return added
def _story_block(s,index,total):
    flag="🇮🇳" if s.get("region")=="india" else "🌍"; v=s.get("verification") or {}
    importance=float(s.get("importance",0) or 0); rank=float(s.get("ranking_score",importance) or importance)
    lines=[f"{flag} <b>#{index} · {s.get('category','NEWS').upper()} · {importance:.0f}/100</b>",f"<b>{s.get('headline','')}</b>"]
    if s.get("what"): lines += ["",f"<b>WHAT</b>\n{s.get('what')}"]
    if s.get("why"): lines += ["",f"<b>WHY</b>\n{s.get('why')}"]
    if s.get("why_important"): lines += ["",f"<b>IMPACT</b>\n{s.get('why_important')}"]
    history=(v.get("historical") or [])
    if history:
        lines += ["",f"<b>HISTORY</b>\n{_history_line(s)}"]
    change=s.get("change_since_yesterday")
    if change and change.lower() not in {"unknown","new today"}:
        lines += ["",f"<b>CHANGE</b>\n{change}"]
    if s.get("next"): lines += ["",f"<b>NEXT</b>\n{s.get('next')}"]
    verification=v.get('verification','unverified'); confidence=v.get('confidence','n/a'); sources=v.get('source_count',0)
    lines += ["",f"🔎 {verification} · {confidence}% · {sources} sources · rank {rank:.0f}"]
    return "\n".join(lines)

def _vocab_block(s,index):
    vocab=str(s.get("vocabulary","")).strip()
    if not vocab or vocab.upper()=="NONE":return None
    terms=[]
    for raw in re.split(r"\s*;\s*|\s*\|\s*\n",vocab):
        raw=raw.strip(" -•")
        if raw and raw.upper()!="NONE":terms.append(raw)
    if not terms:return None
    return "\n".join([f"📚 <b>VOCABULARY · #{index}</b>"]+[f"{n}. {term}" for n,term in enumerate(terms[:3],1)])

def build_messages(result,today,stats):
    stories=sorted(result.get("top_stories",[]),key=lambda s:float(s.get("importance",0) or 0),reverse=True)
    total=len(stories); india=sum(1 for s in stories if s.get("region")=="india"); world=total-india
    threshold=stats.get("importance_threshold",62)
    lines=[f"📰 <b>NEWS INTELLIGENCE · {RUN_SLOT.upper()}</b>","",f"🔥 <b>{total} IMPORTANT STORIES</b>",f"🇮🇳 India: {india} · 🌍 World: {world}",f"🎯 Importance threshold: {threshold}/100","",f"📊 Scanned {stats['articles']} · Candidates {stats['candidates']} · Reported {total}",f"🔎 Verified {stats['verified']}/{stats['total']}",f"📡 Sources {stats.get('source_ok',0)}/{stats.get('source_total',0)} · Health {stats.get('health','WARN')}",
             f"⚠️ Failed: {', '.join(stats.get('failed_sources',[])[:4]) if stats.get('failed_sources') else 'None'}",f"♻️ Duplicates {stats['exact_duplicates']} · Similar filtered {stats['semantic_filtered']}",f"🧠 Learning {stats['learning_labeled']} evaluated · {stats['learning_misses']} misses · {stats['learning_false_positives']} false positives · success {stats['learning_success_rate']:.0%}",f"⏱️ {stats['runtime']} · {configured_model()}","","👇 Stories ranked by importance"]
    messages=["\n".join(lines)]
    for i,s in enumerate(stories,1):
        messages.append(_story_block(s,i,total)); vocab=_vocab_block(s,i)
        if vocab:messages.append(vocab)
    return messages
def main():
    started=time.monotonic(); ensure_data(DATA); cfg=load_sources(); limits=cfg.get("limits",{})
    articles,cstats=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",40),limits.get("max_total_articles",700))
    today=datetime.now(IST).date().isoformat(); timeline=read_rows(DATA/"story_timeline.csv"); all_articles=[a.__dict__ for a in articles]
    candidate_limit=max(1,int(os.getenv("NEWS_CANDIDATE_LIMIT","700")))
    candidates=select_stories(all_articles,top_n=candidate_limit,excluded_headlines=[])
    learning_stats=evaluate_and_learn(DATA,candidates,today)
    candidates=apply_learning(candidates,learning_stats.get("profile",{})); candidates=previous_change(candidates,timeline,today)
    research=research_stories(candidates,timeline,all_articles); research_stats=research.get("_stats",{}); research.pop("_stats",None)
    selected=rerank_stories(candidates,research); result=generate_briefing(selected,all_articles,timeline,today,research)
    source_by_url={a.get("url"):a.get("source","") for a in all_articles}
    for s in result.get("top_stories",[]):s["verification"]=research.get(s.get("story_id"),{});s["source"]=source_by_url.get(s.get("url"),s.get("source",""))
    added=persist(result.get("top_stories",[]),today)
    final_learning=evaluate_and_learn(DATA,candidates,today,selected_ids={s.get("story_id") for s in result.get("top_stories",[])},record_current=True)
    lm=learning_metrics(read_rows(DATA/"news_learning.csv"))
    daily_path=DATA/"news_learning_daily.csv"
    daily_rows=read_rows(daily_path)
    if not any(r.get("date")==today for r in daily_rows):
        learning_rows=read_rows(DATA/"news_learning.csv")
        run_evaluated=final_learning.get("evaluated",0)
        run_selected=final_learning.get("selected_evaluated",0)
        run_fp=final_learning.get("false_positives",0)
        run_misses=final_learning.get("misses",0)
        run_success=sum(1 for r in learning_rows if r.get("run_date")==today and str(r.get("selected","")).lower()=="true" and r.get("learning_value") and _safe_float(r.get("learning_value"))>=.45)/max(1,run_selected)
        append_rows(daily_path,[{"date":today,"evaluated":run_evaluated,"selected_evaluated":run_selected,"misses":run_misses,"false_positives":run_fp,"success_rate":run_success,"false_positive_rate":run_fp/max(1,run_selected),"miss_rate":run_misses/max(1,run_evaluated-run_selected)}],HEADERS["news_learning_daily.csv"])
    stats={"importance_threshold":float(os.getenv("NEWS_MIN_IMPORTANCE","62")),"articles":cstats.get("scanned",len(articles)),"candidates":len(candidates),"exact_duplicates":cstats.get("exact_duplicates",0),"semantic_filtered":cstats.get("semantic_filtered",0),"source_failures":cstats.get("source_failures",0),"source_total":len(cstats.get("source_status") or []),"source_ok":sum(1 for x in (cstats.get("source_status") or []) if x.get("ok")),"stories":len(result.get("top_stories",[])),"verified":research_stats.get("ok",sum(1 for s in result.get("top_stories",[]) if (s.get("verification") or {}).get("verification") in {"multi-source","official-source"})),"total":len(selected),"runtime":f"{time.monotonic()-started:.1f}s","learning_labeled":final_learning.get("evaluated",0),"learning_misses":final_learning.get("misses",0),"learning_false_positives":final_learning.get("false_positives",0),"learning_success_rate":lm.get("success_rate",0),"failed_sources":[str(x.get("url","")).split("//")[-1].split("/")[0] for x in (cstats.get("source_status") or []) if not x.get("ok")],"learning_fp_rate":lm.get("false_positive_rate",0),"learning_miss_rate":lm.get("miss_rate",0)}
    coverage=stats["verified"]/max(1,stats["total"])
    stats["health"]="PASS" if stats["source_failures"]==0 and coverage>=0.50 else ("WARN" if coverage>=0.20 or stats["source_failures"]<=2 else "DEGRADED")
    print(f"[PASS] FINAL NEWS INTELLIGENCE | candidates={stats['candidates']} | stories={stats['stories']} | verified={stats['verified']}/{stats['total']} | learning={stats['learning_labeled']} | misses={stats['learning_misses']} | false_positive={stats['learning_false_positives']} | source_failures={stats['source_failures']} | health={stats['health']} | new={added}",flush=True)
    for failure in (cstats.get("source_status") or []):
        if not failure.get("ok"):
            print(f"[WARN] source failed | category={failure.get('category','')} | url={failure.get('url','')} | error={failure.get('error','')}",flush=True)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            for m in build_messages(result,today,stats):
                send_text(m)
        except Exception as exc:
            print(f"[WARN] Telegram full briefing failed: {exc}", flush=True)
            fallback = [
                "📰 <b>NEWS INTELLIGENCE · FALLBACK</b>",
                "",
                "⚠️ <b>Full briefing was partially unavailable.</b>",
                f"📊 Candidates {stats['candidates']} · Stories {stats['stories']}",
                f"🔎 Verified {stats['verified']}/{stats['total']}",
                f"📡 Sources {stats.get('source_ok',0)}/{stats.get('source_total',0)} · {stats.get('health','DEGRADED')}",
                "",
                "<b>TOP STORIES</b>"
            ]
            for i, s in enumerate(sorted(result.get("top_stories",[]), key=lambda x: float(x.get("importance",0) or 0), reverse=True)[:10], 1):
                fallback.append(f"{i}. <b>{s.get('headline','')}</b> · {float(s.get('importance',0) or 0):.0f}/100")
            try:
                send_text("\n".join(fallback))
            except Exception as fallback_exc:
                print(f"[ERROR] Telegram fallback failed: {fallback_exc}", flush=True)
if __name__=="__main__":main()
