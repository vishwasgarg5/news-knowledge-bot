from __future__ import annotations
import os,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import yaml
from .ai import generate_briefing,select_stories,configured_model
from .news import collect
from .research import research_stories
from .settings import CONFIG,DATA,TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
from .storage import HEADERS,append_rows,ensure_data,read_rows
from .telegram import send_text

IST=ZoneInfo("Asia/Kolkata"); RUN_SLOT=os.getenv("RUN_SLOT","morning").lower()

def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)

def sim(a,b):
    x=set(re.findall(r"[a-z]{4,}",a.lower())); y=set(re.findall(r"[a-z]{4,}",b.lower())); return len(x&y)/max(1,len(x|y))

def previous_change(stories,rows,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat()
    old=[r.get("headline","") for r in rows if r.get("date")==yesterday]
    for s in stories:
        s["change_since_yesterday"]="Continuing" if any(sim(s.get("headline",""),x)>=.48 for x in old) else "New today"
    return stories

def persist(stories,today):
    path=DATA/"news_history.csv"; rows=read_rows(path); ids={r.get("story_id") for r in rows}
    timeline_path=DATA/"story_timeline.csv"; timeline=read_rows(timeline_path); keys={(r.get("story_id"),r.get("date")) for r in timeline}; added=0
    for s in stories:
        sid=s.get("story_id"); v=s.get("verification") or {}
        if sid and sid not in ids:
            append_rows(path,[{"date":today,"story_id":sid,"headline":s.get("headline",""),"source":s.get("source",""),"url":s.get("url",""),"category":s.get("category",""),"importance":s.get("importance",0),"region":s.get("region","world"),"verification":v.get("verification",""),"confidence":v.get("confidence","")}],HEADERS["news_history.csv"]); ids.add(sid); added+=1
        if sid and (sid,today) not in keys:
            append_rows(timeline_path,[{"story_id":sid,"date":today,"headline":s.get("headline",""),"event":s.get("what",s.get("headline","")),"importance":s.get("importance",0),"source":s.get("source",""),"url":s.get("url",""),"change_type":s.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]); keys.add((sid,today))
    return added

def _story_block(s,i,total):
    flag="🇮🇳" if s.get("region")=="india" else "🌍"; v=s.get("verification") or {}
    return (f"{flag} <b>{i}/{total} · {s.get('headline','')}</b>\n"
            f"🔴 {s.get('what','')}\n"
            f"❓ {s.get('why','')}\n"
            f"💡 {s.get('why_important','')}\n"
            f"🔄 {s.get('change_since_yesterday','')}\n"
            f"🔮 {s.get('next','')}\n"
            f"🧠 {s.get('memory_hook','')}\n"
            f"🔎 {v.get('verification','unverified')} · {v.get('confidence','n/a')}% · {v.get('source_count',0)} src")

def build_messages(result,today,stats):
    stories=result.get("top_stories",[]); label="MORNING" if RUN_SLOT=="morning" else "AFTERNOON"; messages=[]
    for region,title in (("india","🇮🇳 INDIA"),("world","🌍 WORLD")):
        group=[s for s in stories if s.get("region")==region]
        if not group: continue
        blocks=[f"📰 <b>{title} · {label}</b>","EVENT ↓ WHY ↓ IMPACT ↓ CHANGE ↓ NEXT ↓ REMEMBER","" ]
        for i,s in enumerate(group,1): blocks.append(_story_block(s,i,len(group))+"\n")
        messages.append("\n".join(blocks).strip())
    messages.append(f"📊 <b>{label} · NEWS STATUS</b>\n🇮🇳 {sum(s.get('region')=='india' for s in stories)}  |  🌍 {sum(s.get('region')=='world' for s in stories)}\n📰 scanned {stats['articles']} · selected {stats['stories']} · verified {stats['verified']}/{stats['total']}\n♻️ duplicates {stats['duplicates']} · {stats['runtime']} · model {configured_model()}")
    return messages

def main():
    started=time.monotonic(); ensure_data(DATA); cfg=load_sources(); limits=cfg.get("limits",{})
    articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",40),limits.get("max_total_articles",700))
    today=datetime.now(IST).date().isoformat(); rows=read_rows(DATA/"news_history.csv"); delivered=[r.get("headline","") for r in rows if r.get("date")==today]
    all_articles=[a.__dict__ for a in articles]; selected=previous_change(select_stories(all_articles,limits.get("top_stories",12),delivered),rows,today)
    research=research_stories(selected,rows,all_articles); rs=research.pop("_stats",{}); result=generate_briefing(selected,all_articles,rows,today,research)
    for s in result.get("top_stories",[]):
        s["verification"]=research.get(s.get("story_id"),{}); s["source"]=next((a.get("source","") for a in all_articles if a.get("url")==s.get("url")),"")
    added=persist(result.get("top_stories",[]),today); runtime=f"{time.monotonic()-started:.1f}s"
    stats={"articles":len(articles),"duplicates":max(0,len(all_articles)-len(selected)),"stories":len(result.get("top_stories",[])),"verified":rs.get("ok",0),"total":rs.get("total",len(selected)),"runtime":runtime}
    print(f"[PASS] FINAL NEWS INTELLIGENCE | model={configured_model()} | stories={stats['stories']} | verified={stats['verified']}/{stats['total']} | new={added}",flush=True)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for message in build_messages(result,today,stats): send_text(message)

if __name__=="__main__": main()
