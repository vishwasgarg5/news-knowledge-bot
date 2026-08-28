from __future__ import annotations
import json, os
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
    return {"knowledge_cards":read_rows(DATA/"knowledge_cards.csv")[-80:],"vocabulary":read_rows(DATA/"vocabulary.csv")[-80:],"people":read_rows(DATA/"people.csv")[-40:],"places":read_rows(DATA/"places.csv")[-40:],"story_timeline":read_rows(DATA/"story_timeline.csv")[-100:],"current_affairs":read_rows(DATA/"current_affairs.csv")[-80:]}
def build_messages(result,today):
    msgs=[f"🧠 <b>DAILY NEWS + KNOWLEDGE BRIEF</b>\n{today}\n\nAutomatic morning briefing • zero daily input"]
    top=result.get("top_stories",[]); text="🔥 <b>TOP NEWS</b>\n"
    for i,s in enumerate(top,1):
        text+=f"\n<b>{i}. {s.get('headline','')}</b> — {s.get('importance',0)}/100\n<b>What:</b> {s.get('what','')}\n<b>Who:</b> {s.get('who','')}\n<b>When:</b> {s.get('when','')}\n<b>Where:</b> {s.get('where','')}\n<b>Why:</b> {s.get('why','')}\n<b>Why important:</b> {s.get('why_important','')}\n<b>Latest:</b> {s.get('latest_update','')}\n"
        if s.get("sources"):text+="🔗 "+" | ".join(s["sources"][:3])+"\n"
    msgs.append(text)
    rh=result.get("research_stats",{}); msgs.append(f"📚 <b>HISTORICAL CONTEXT</b>\nResearch evidence: {rh.get('ok',0)}/{rh.get('total',0)} stories\nStatus: {rh.get('status','UNKNOWN')}\n")
    extra=result.get("learning_text","")
    if extra:msgs.append("📅 <b>LEARNING / CURRENT AFFAIRS</b>\n"+extra)
    return msgs

def persist(result,today):
    ensure_data(DATA)
    for s in result.get("top_stories",[]):
        url=(s.get("sources") or [""])[0]
        append_rows(DATA/"news_history.csv",[{"date":today,"story_id":s.get("story_id"),"headline":s.get("headline"),"source":"","url":url,"category":s.get("category"),"importance":s.get("importance",0)}],HEADERS["news_history.csv"])

def main():
    print("="*60);print("🧠 NEWS KNOWLEDGE BOT — MORNING RUN");print("="*60)
    log("Environment","PASS",f"Python runtime ready; test_mode={TEST_MODE}");log("AI provider","INFO",f"Local Ollama; model={configured_model()}");log("Credentials","PASS","No paid AI API key required")
    tg=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID);log("Credentials","PASS" if tg else "SKIP","Telegram configured" if tg else "Telegram secrets missing")
    ensure_data(DATA);log("CSV storage","PASS","Data directory and CSV schemas validated")
    cfg=load_sources();limits=cfg.get("limits",{})
    try: articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",500))
    except Exception as exc: log("News collection","FAIL",f"{type(exc).__name__}: {exc}");raise
    log("News collection","PASS" if articles else "FAIL",f"Collected {len(articles)} articles")
    today=datetime.now(IST).date().isoformat();previous=history_snapshot();learning=daily_learning();log("Learning memory","PASS",f"Loaded {sum(len(v) for v in previous.values())} historical rows")
    selected=select_stories([a.__dict__ for a in articles],top_n=min(12,limits.get("top_stories",12)));log("Story selection","PASS",f"Deterministic scoring reduced {len(articles)} articles to {len(selected)} priority stories; no LLM tokens used")
    historical=research_stories(selected); stats=historical.pop("_stats",{"ok":0,"failed":len(selected),"total":len(selected),"status":"FAIL"});log("Historical research",stats["status"],f"Research evidence {stats['ok']}/{stats['total']} stories; {stats['failed']} empty/failed")
    result=generate_briefing(selected,[a.__dict__ for a in articles],previous,today,historical);result["research_stats"]=stats;result["learning_text"]=result.get("learning_text") or "";log("AI final briefing","PASS",f"Generated {len(result.get('top_stories',[]))} stories")
    persist(result,today);log("CSV persistence","PASS","Knowledge CSVs updated")
    if tg:
        for message in build_messages(result,today):send_text(message)
        log("Telegram delivery","PASS","Morning messages sent")
    else:log("Telegram delivery","SKIP","Telegram secrets not configured")
    if stats["status"]=="FAIL": log("FINAL","WARN","Briefing completed, but historical research returned no evidence")
    elif stats["status"]=="WARN": log("FINAL","WARN","Briefing completed with partial historical research")
    else: log("FINAL","PASS","Morning knowledge pipeline completed")
if __name__=="__main__":main()
