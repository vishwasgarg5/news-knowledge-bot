from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yaml

from .ai import configured_model, generate_briefing, select_stories
from .news import collect
from .research import research_stories
from .settings import CONFIG, DATA, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .storage import HEADERS, append_rows, ensure_data, read_rows
from .telegram import send_text

IST = ZoneInfo("Asia/Kolkata")
RUN_SLOT = os.getenv("RUN_SLOT", "manual").lower()


def load_sources():
    with CONFIG.open(encoding="utf-8") as f: return yaml.safe_load(f) or {}

def sim(a,b):
    x=set(re.findall(r"[a-z]{4,}",str(a).lower())); y=set(re.findall(r"[a-z]{4,}",str(b).lower())); return len(x&y)/max(1,len(x|y))

def previous_change(stories,timeline,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat(); old=[r.get("headline","") for r in timeline if r.get("date")==yesterday]
    for story in stories: story["change_since_yesterday"]="Continuing" if any(sim(story.get("headline",""),x)>=0.48 for x in old) else "New today"
    return stories

def _history_line(story):
    history=(story.get("verification") or {}).get("historical") or []
    if not history: return "No close prior story"
    first=history[0]; title=str(first.get("title","")).strip(); title=title[:127].rstrip()+"..." if len(title)>130 else title
    return f"{first.get('date','prior')}: {title} · {first.get('source','memory')}"

def _priority(story):
    h=str(story.get("headline","")).lower(); imp=float(story.get("importance",0) or 0); v=(story.get("verification") or {}).get("verification","")
    breaking_terms=("breaking","just in","live","major","emergency","earthquake","cyclone","war","ceasefire","attack","killed","resigns","resignation","verdict","ruling","rate cut","rate hike","default")
    score=imp + (18 if any(x in h for x in breaking_terms) else 0) + (8 if v in {"multi-source","official-source"} else 0) + (5 if story.get("change_since_yesterday")=="New today" else 0)
    return score

def _category(story):
    cat=str(story.get("category","")).lower(); h=str(story.get("headline","")).lower()
    if any(x in cat for x in ("business","economy")) or any(x in h for x in ("market","stock","rbi","inflation","gdp","bank","trade","tariff","economy","budget")): return "BUSINESS"
    if "technology" in cat or any(x in h for x in ("ai","artificial intelligence","technology","chip","cyber","software")): return "TECHNOLOGY"
    if "science" in cat or any(x in h for x in ("space","isro","nasa","climate","scientist","research")): return "SCIENCE"
    return "INDIA" if story.get("region")=="india" else "WORLD"

def _freshness_filter(stories,history):
    # Suppress unchanged repeats from recent memory; continuing stories return only when their headline/event changed materially.
    recent=[r for r in history if r.get("date")]
    kept=[]
    for story in stories:
        title=story.get("headline",""); duplicate=False
        for old in recent:
            old_title=old.get("headline","")
            if old_title and sim(title,old_title)>=0.80:
                duplicate=True; break
        if not duplicate: kept.append(story)
    return kept

def persist(stories,today):
    path=DATA/"news_history.csv"; rows=read_rows(path); ids={r.get("story_id") for r in rows}; timeline_path=DATA/"story_timeline.csv"; timeline=read_rows(timeline_path); keys={(r.get("story_id"),r.get("date")) for r in timeline}; added=0
    for story in stories:
        sid=story.get("story_id"); verification=story.get("verification") or {}
        if sid and sid not in ids:
            append_rows(path,[{"date":today,"story_id":sid,"headline":story.get("headline",""),"source":story.get("source",""),"url":story.get("url",""),"category":story.get("category",""),"importance":story.get("importance",0),"region":story.get("region","world"),"verification":verification.get("verification",""),"confidence":verification.get("confidence","")}],HEADERS["news_history.csv"]); ids.add(sid); added+=1
        if sid and (sid,today) not in keys:
            append_rows(timeline_path,[{"story_id":sid,"date":today,"headline":story.get("headline",""),"event":story.get("what",story.get("headline","")),"importance":story.get("importance",0),"source":story.get("source",""),"url":story.get("url",""),"change_type":story.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]); keys.add((sid,today))
    return added

def _story_block(story,index,total):
    flag="🇮🇳" if story.get("region")=="india" else "🌍"; v=story.get("verification") or {}; status={"multi-source":"Confirmed · multi-source","official-source":"Confirmed · official source","single-source":"Single source","unverified":"Unverified"}.get(v.get("verification",""),"Unverified")
    return (f"{flag} <b>{index}/{total} · {story.get('headline','')}</b>\n🔴 {story.get('what','Not available')}\n❓ {story.get('why','Not available')}\n💡 {story.get('why_important','Not available')}\n🕰️ {_history_line(story)}\n🔄 {story.get('change_since_yesterday','Unknown')}\n🔮 {story.get('next','No clear next step reported')}\n🧠 {story.get('memory_hook',story.get('what',''))}\n🔎 {status} · {v.get('confidence','n/a')}% · {v.get('source_count',0)} sources")

def build_messages(result,today,stats):
    stories=sorted(result.get("top_stories",[]),key=lambda s:-_priority(s)); total=len(stories)
    headline_lines=[f"📰 <b>NEWS INTELLIGENCE · {today}</b>",f"{total} important stories",""]
    sections={"BREAKING":[],"INDIA":[],"WORLD":[],"BUSINESS":[],"TECHNOLOGY":[],"SCIENCE":[]}
    for s in stories:
        section="BREAKING" if _priority(s)>=float(s.get("importance",0) or 0)+18 else _category(s); sections.setdefault(section,[]).append(s)
    ordered=[]
    for name in ("BREAKING","INDIA","WORLD","BUSINESS","TECHNOLOGY","SCIENCE"):
        if sections.get(name):
            headline_lines.append(f"\n<b>{'🚨' if name=='BREAKING' else '🇮🇳' if name=='INDIA' else '🌍' if name=='WORLD' else '💰' if name=='BUSINESS' else '💻' if name=='TECHNOLOGY' else '🔬'} {name}</b>")
            for s in sections[name]:
                ordered.append(s); headline_lines.append(f"{len(ordered)}. {s.get('headline','')}")
    headline_lines.extend(["",f"📊 scanned {stats['articles']} · fresh {stats['stories']} · verified {stats['verified']}/{stats['total']}",f"♻️ duplicates filtered {stats['exact_duplicates']+stats['semantic_filtered']} · ⚠️ source failures {stats['source_failures']}",f"⏱️ {stats['runtime']} · model {configured_model()}","","👇 Detailed news follows — one message per story"])
    messages=["\n".join(headline_lines)]
    for index,story in enumerate(ordered,1): messages.append(_story_block(story,index,total))
    return messages

def main():
    started=time.monotonic(); ensure_data(DATA); cfg=load_sources(); limits=cfg.get("limits",{})
    articles,collect_stats=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",40),limits.get("max_total_articles",700))
    today=datetime.now(IST).date().isoformat(); history=read_rows(DATA/"news_history.csv"); timeline=read_rows(DATA/"story_timeline.csv")
    delivered_today=[r.get("headline","") for r in history if r.get("date")==today] if RUN_SLOT=="morning" else []
    all_articles=[a.__dict__ for a in articles]
    selected=select_stories(all_articles,excluded_headlines=delivered_today)
    selected=_freshness_filter(selected,history)
    selected=previous_change(selected,timeline,today)
    research=research_stories(selected,timeline,all_articles); research_stats=research.pop("_stats",{})
    result=generate_briefing(selected,all_articles,timeline,today,research)
    source_by_url={a.get("url"):a.get("source","") for a in all_articles}
    for story in result.get("top_stories",[]): story["verification"]=research.get(story.get("story_id"),{}); story["source"]=source_by_url.get(story.get("url"),story.get("source",""))
    added=persist(result.get("top_stories",[]),today)
    stats={"articles":collect_stats.get("scanned",len(articles)),"exact_duplicates":collect_stats.get("exact_duplicates",0),"semantic_filtered":collect_stats.get("semantic_filtered",0),"source_failures":collect_stats.get("source_failures",0),"stories":len(result.get("top_stories",[])),"verified":research_stats.get("ok",0),"total":research_stats.get("total",len(selected)),"runtime":f"{time.monotonic()-started:.1f}s"}
    print(f"[PASS] FINAL NEWS INTELLIGENCE | stories={stats['stories']} | verified={stats['verified']}/{stats['total']} | source_failures={stats['source_failures']} | new={added}",flush=True)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for message in build_messages(result,today,stats): send_text(message)

if __name__ == "__main__": main()
