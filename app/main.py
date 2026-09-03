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
IST=ZoneInfo("Asia/Kolkata");RUN_SLOT=os.getenv("RUN_SLOT","morning").lower()

def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)
def sim(a,b):
    x=set(re.findall(r"[a-z]{4,}",a.lower()));y=set(re.findall(r"[a-z]{4,}",b.lower()));return len(x&y)/max(1,len(x|y))
def previous_change(stories,rows,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat();old=[r.get("headline","") for r in rows if r.get("date")==yesterday]
    for s in stories:s["change_since_yesterday"]="Continuing story" if any(sim(s.get("headline",""),x)>=.48 for x in old) else "New topic today"
    return stories
def persist(stories,today):
    path=DATA/"news_history.csv";rows=read_rows(path);ids={r.get("story_id") for r in rows};timeline=read_rows(DATA/"story_timeline.csv");keys={(r.get("story_id"),r.get("date")) for r in timeline};added=0
    for s in stories:
        sid=s.get("story_id");v=s.get("verification") or {}
        if sid and sid not in ids:
            append_rows(path,[{"date":today,"story_id":sid,"headline":s.get("headline",""),"source":s.get("source",""),"url":s.get("url",""),"category":s.get("category",""),"importance":s.get("importance",0),"region":s.get("region","world"),"verification":v.get("verification",""),"confidence":v.get("confidence","")}],HEADERS["news_history.csv"]);ids.add(sid);added+=1
        if sid and (sid,today) not in keys:
            append_rows(DATA/"story_timeline.csv",[{"story_id":sid,"date":today,"headline":s.get("headline",""),"event":s.get("what",s.get("latest_update","")),"importance":s.get("importance",0),"source":s.get("source",""),"url":s.get("url",""),"change_type":s.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]);keys.add((sid,today))
    return added
def build_messages(result,today,stats):
    stories=result.get("top_stories",[]);label="MORNING" if RUN_SLOT=="morning" else "AFTERNOON";india=sum(s.get("region")=="india" for s in stories);world=sum(s.get("region")=="world" for s in stories);messages=[]
    for i,s in enumerate(stories,1):
        flag="🇮🇳 INDIA" if s.get("region")=="india" else "🌍 WORLD";v=s.get("verification") or {};e=v.get("evidence",[])
        messages.append(f"📰 <b>{flag} — {label} {i}/{len(stories)}</b>\n<b>{s.get('headline','')}</b>\n\n🔴 <b>EVENT</b> → {s.get('what','')}\n👤 <b>WHO</b> → {s.get('who','')}\n📅 <b>WHEN</b> → {s.get('when','')}\n📍 <b>WHERE</b> → {s.get('where','')}\n   ↓\n❓ <b>WHY</b> → {s.get('why','')}\n   ↓\n💡 <b>IMPACT</b> → {s.get('why_important','')}\n   ↓\n🔄 <b>CHANGE</b> → {s.get('change_since_yesterday','')}\n   ↓\n🔮 <b>NEXT</b> → {s.get('next','')}\n   ↓\n🔗 <b>CONNECTION</b> → {s.get('connection','')}\n   ↓\n🧠 <b>REMEMBER</b> → {s.get('memory_hook','')}\n\n🔎 <b>VERIFY</b> → {v.get('verification','not checked')} | {v.get('confidence','n/a')}% | {v.get('source_count',0)} sources"+("\n"+"\n".join(f"• {x.get('source','')} — {x.get('title','')[:100]}" for x in e[:3]) if e else ""))
    messages.append(f"📊 <b>{label} NEWS STATUS</b>\n🇮🇳 India: {india}\n🌍 World: {world}\n📰 Scanned: {stats['articles']}\n♻️ Filtered: {stats['duplicates']}\n✅ Delivered: {stats['stories']}\n🔎 Verified: {stats['verified']}/{stats['total']}\n⏱ Runtime: {stats['runtime']}\n🎯 Target: 6 India + 6 World")
    return messages
def main():
    started=time.monotonic();ensure_data(DATA);cfg=load_sources();limits=cfg.get("limits",{});articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",700));today=datetime.now(IST).date().isoformat();rows=read_rows(DATA/"news_history.csv");delivered=[r.get("headline","") for r in rows if r.get("date")==today];all_articles=[a.__dict__ for a in articles];selected=previous_change(select_stories(all_articles,12,delivered),rows,today);research=research_stories(selected,rows,all_articles);rs=research.pop("_stats",{});result=generate_briefing(selected,all_articles,rows,today,research)
    for s in result.get("top_stories",[]):s["verification"]=research.get(s.get("story_id"),{});s["source"]=next((a.get("source","") for a in all_articles if a.get("url")==s.get("url")),"")
    added=persist(result.get("top_stories",[]),today);runtime=f"{time.monotonic()-started:.1f}s";stats={"articles":len(articles),"duplicates":max(0,len(articles)-len(selected)),"stories":len(result.get("top_stories",[])),"verified":rs.get("ok",0),"total":rs.get("total",len(selected)),"runtime":runtime}
    print(f"[PASS] NEWS ONLY | model={configured_model()} | stories={stats['stories']} | India/World target 6/6 | verified={stats['verified']}/{stats['total']} | new={added}",flush=True)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for m in build_messages(result,today,stats):send_text(m)
if __name__=="__main__":main()
