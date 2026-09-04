from __future__ import annotations
import os,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import yaml
from .ai import configured_model,generate_briefing,select_stories
from .news import collect
from .research import research_stories
from .settings import CONFIG,DATA,TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
from .storage import HEADERS,append_rows,ensure_data,read_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata"); RUN_SLOT=os.getenv("RUN_SLOT","manual").lower()
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
            append_rows(path,[{"date":today,"story_id":sid,"headline":s.get("headline",""),"source":s.get("source",""),"url":s.get("url",""),"category":s.get("category",""),"importance":s.get("importance",0),"region":s.get("region","world"),"verification":v.get("verification",""),"confidence":v.get("confidence","")}],HEADERS["news_history.csv"]); ids.add(sid); added+=1
        if sid and (sid,today) not in keys:
            append_rows(tp,[{"story_id":sid,"date":today,"headline":s.get("headline",""),"event":s.get("what",s.get("headline","")),"importance":s.get("importance",0),"source":s.get("source",""),"url":s.get("url",""),"change_type":s.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]); keys.add((sid,today))
    return added
def _story_block(s,index,total):
    flag="🇮🇳" if s.get("region")=="india" else "🌍"; v=s.get("verification") or {}
    return (f"{flag} <b>{index}/{total} · {s.get('headline','')}</b>\n🔴 {s.get('what','Not available')}\n❓ {s.get('why','Not available')}\n💡 {s.get('why_important','Not available')}\n🕰️ {_history_line(s)}\n🔄 {s.get('change_since_yesterday','Unknown')}\n🔮 {s.get('next','No clear next step reported')}\n🧠 {s.get('memory_hook',s.get('what',''))}\n🔎 {v.get('verification','unverified')} · {v.get('confidence','n/a')}% · {v.get('source_count',0)} src")
def _vocab_block(s,index):
    vocab=str(s.get("vocabulary","")).strip()
    if not vocab or vocab.upper()=="NONE":return None
    terms=[]
    for raw in re.split(r"\s*;\s*|\s*\|\s*\n",vocab):
        raw=raw.strip(" -•")
        if raw and raw.upper()!="NONE":terms.append(raw)
    if not terms:return None
    lines=[f"📚 <b>VOCABULARY · NEWS {index}</b>"]
    for n,term in enumerate(terms[:3],1):lines.append(f"{n}. {term}")
    return "\n".join(lines)
def build_messages(result,today,stats):
    stories=result.get("top_stories",[]); total=len(stories); lines=[f"📰 <b>NEWS INTELLIGENCE · MANUAL</b>",f"{total} stories",""]
    for i,s in enumerate(stories,1):
        flag="🇮🇳" if s.get("region")=="india" else "🌍"; lines.append(f"{i}. {flag} {s.get('headline','')}")
    lines += ["",f"📊 scanned {stats['articles']} · selected {stats['stories']} · verified {stats['verified']}/{stats['total']}",f"♻️ exact dup {stats['exact_duplicates']} · similar filtered {stats['semantic_filtered']} · ⚠️ source failures {stats['source_failures']}",f"⏱️ {stats['runtime']} · model {configured_model()}","","👇 Detailed news follows — one message per story"]
    messages=["\n".join(lines)]
    for i,s in enumerate(stories,1):
        messages.append(_story_block(s,i,total)); vocab=_vocab_block(s,i)
        if vocab:messages.append(vocab)
    return messages
def main():
    started=time.monotonic(); ensure_data(DATA); cfg=load_sources(); limits=cfg.get("limits",{}); articles,cstats=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",40),limits.get("max_total_articles",700)); today=datetime.now(IST).date().isoformat(); history=read_rows(DATA/"news_history.csv"); timeline=read_rows(DATA/"story_timeline.csv"); delivered=[r.get("headline","") for r in history if r.get("date")==today] if RUN_SLOT=="morning" else []; all_articles=[a.__dict__ for a in articles]; selected=select_stories(all_articles,excluded_headlines=delivered); selected=previous_change(selected,timeline,today); research=research_stories(selected,timeline,all_articles); rstats=research.pop("_stats",{}); result=generate_briefing(selected,all_articles,timeline,today,research); source_by_url={a.get("url"):a.get("source","") for a in all_articles}
    for s in result.get("top_stories",[]):s["verification"]=research.get(s.get("story_id"),{});s["source"]=source_by_url.get(s.get("url"),s.get("source",""))
    added=persist(result.get("top_stories",[]),today); stats={"articles":cstats.get("scanned",len(articles)),"exact_duplicates":cstats.get("exact_duplicates",0),"semantic_filtered":cstats.get("semantic_filtered",0),"source_failures":cstats.get("source_failures",0),"stories":len(result.get("top_stories",[])),"verified":rstats.get("ok",0),"total":rstats.get("total",len(selected)),"runtime":f"{time.monotonic()-started:.1f}s"}; print(f"[PASS] FINAL NEWS INTELLIGENCE | stories={stats['stories']} | verified={stats['verified']}/{stats['total']} | source_failures={stats['source_failures']} | new={added}",flush=True)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for m in build_messages(result,today,stats):send_text(m)
if __name__=="__main__":main()
