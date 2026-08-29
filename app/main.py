from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from .ai import configured_model, generate_briefing, select_stories
from .learning import daily_learning
from .news import collect
from .research import research_stories
from .settings import CONFIG, DATA, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .storage import HEADERS, append_rows, ensure_data, read_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata")
TEST_MODE=os.environ.get("TEST_MODE","0").lower() in {"1","true","yes"}
def log(stage,status,message): print(f"[{status}] {stage}: {message}",flush=True)
def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)
def history_snapshot():
    return {name[:-4]:read_rows(DATA/name)[-500:] for name in HEADERS}
def build_messages(result,today):
    msgs=[f"🧠 <b>DAILY NEWS + KNOWLEDGE BRIEF</b>\n{today}\n\nAutomatic morning briefing • zero daily input"]
    top=result.get("top_stories",[]); text="🔥 <b>TOP NEWS</b>\n"
    for i,s in enumerate(top,1):
        text+=f"\n<b>{i}. {s.get('headline','')}</b> — {s.get('importance',0)}/100\n<b>What:</b> {s.get('what','')}\n<b>Who:</b> {s.get('who','')}\n<b>When:</b> {s.get('when','')}\n<b>Where:</b> {s.get('where','')}\n<b>Why:</b> {s.get('why','')}\n<b>Why important:</b> {s.get('why_important','')}\n<b>Latest:</b> {s.get('latest_update','')}\n"
        if s.get("timeline"): text+="<b>Past:</b> "+" | ".join(x.get("title","") for x in s["timeline"][:3])+"\n"
        if s.get("sources"):text+="🔗 "+" | ".join(s["sources"][:3])+"\n"
    msgs.append(text)
    rh=result.get("research_stats",{}); msgs.append(f"📚 <b>HISTORICAL CONTEXT</b>\nResearch evidence: {rh.get('ok',0)}/{rh.get('total',0)} stories\nGitHub memory matches: {rh.get('memory_ok',0)}\nStatus: {rh.get('status','UNKNOWN')}\n")
    extra=result.get("learning_text","")
    if extra:msgs.append("📅 <b>LEARNING / CURRENT AFFAIRS</b>\n"+extra)
    return msgs
def persist(result,today):
    ensure_data(DATA)
    stories=result.get("top_stories",[])
    existing={r.get("story_id") for r in read_rows(DATA/"news_history.csv")}
    for s in stories:
        sid=s.get("story_id"); url=(s.get("sources") or [""])[0]
        if sid and sid not in existing:
            append_rows(DATA/"news_history.csv",[{"date":today,"story_id":sid,"headline":s.get("headline"),"source":"","url":url,"category":s.get("category"),"importance":s.get("importance",0)}],HEADERS["news_history.csv"])
        # Preserve long-term knowledge even when the AI does not populate every specialized card.
        append_rows(DATA/"story_timeline.csv",[{"story_id":sid,"date":today,"headline":s.get("headline"),"event":s.get("latest_update",s.get("what","")),"importance":s.get("importance",0),"source":"","url":url}],HEADERS["story_timeline.csv"])
        append_rows(DATA/"current_affairs.csv",[{"date":today,"topic":s.get("headline"),"category":s.get("category",""),"summary":s.get("what",s.get("latest_update","")),"why_important":s.get("why_important",""),"source_url":url}],HEADERS["current_affairs.csv"])
        for p in s.get("people",[]) or []:
            append_rows(DATA/"people.csv",[{"name":p.get("name",p) if isinstance(p,dict) else p,"role":p.get("role","") if isinstance(p,dict) else "","background":p.get("background","") if isinstance(p,dict) else "","why_in_news":s.get("why",""),"last_seen":today}],HEADERS["people.csv"])
        for p in s.get("places",[]) or []:
            append_rows(DATA/"places.csv",[{"name":p.get("name",p) if isinstance(p,dict) else p,"location":p.get("location","") if isinstance(p,dict) else "","background":p.get("background","") if isinstance(p,dict) else "","why_important":s.get("why_important",""),"last_seen":today}],HEADERS["places.csv"])
def main():
    print("="*60);print("🧠 NEWS KNOWLEDGE BOT — MORNING RUN");print("="*60)
    log("Environment","PASS",f"Python runtime ready; test_mode={TEST_MODE}");log("AI provider","INFO",f"Local Ollama; model={configured_model()}")
    tg=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID);log("Credentials","PASS" if tg else "SKIP","Telegram configured" if tg else "Telegram secrets missing")
    ensure_data(DATA);log("CSV storage","PASS","All knowledge CSV schemas validated")
    cfg=load_sources();limits=cfg.get("limits",{})
    articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",500));log("News collection","PASS" if articles else "FAIL",f"Collected {len(articles)} articles")
    today=datetime.now(IST).date().isoformat();previous=history_snapshot();daily_learning();log("Learning memory","PASS",f"Loaded {sum(len(v) for v in previous.values())} historical rows across {len(previous)} CSVs")
    selected=select_stories([a.__dict__ for a in articles],top_n=min(12,limits.get("top_stories",12)));log("Story selection","PASS",f"Selected {len(selected)} priority stories")
    historical=research_stories(selected,previous.get("news_history",[]));stats=historical.pop("_stats",{"ok":0,"memory_ok":0,"failed":len(selected),"total":len(selected),"status":"FAIL"});log("Historical research",stats["status"],f"Evidence {stats['ok']}/{stats['total']}; GitHub memory {stats['memory_ok']}")
    result=generate_briefing(selected,[a.__dict__ for a in articles],previous,today,historical);result["research_stats"]=stats;log("AI final briefing","PASS",f"Generated {len(result.get('top_stories',[]))} stories")
    persist(result,today);log("CSV persistence","PASS","Long-term news history, timeline and current-affairs memory updated")
    if tg:
        for message in build_messages(result,today): send_text(message)
        log("Telegram delivery","PASS","Morning messages sent")
    else: log("Telegram delivery","SKIP","Telegram secrets not configured")
    log("FINAL","PASS" if stats["status"]=="PASS" else "WARN","Morning knowledge pipeline completed" + (" with partial historical context" if stats["status"]!="PASS" else ""))
if __name__=="__main__":main()
