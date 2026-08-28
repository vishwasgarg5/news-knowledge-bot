from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

from .ai import configured_model, generate
from .learning import daily_learning
from .news import collect
from .research import research_stories
from .settings import CONFIG, DATA, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .storage import HEADERS, append_rows, ensure_data, read_rows
from .telegram import send_text

IST = ZoneInfo("Asia/Kolkata")
TEST_MODE = os.environ.get("TEST_MODE", "0").lower() in {"1", "true", "yes"}


def log(stage: str, status: str, message: str):
    print(f"[{status}] {stage}: {message}", flush=True)


def load_sources():
    with CONFIG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def history_snapshot():
    return {
        "knowledge_cards": read_rows(DATA / "knowledge_cards.csv")[-250:],
        "vocabulary": read_rows(DATA / "vocabulary.csv")[-250:],
        "people": read_rows(DATA / "people.csv")[-150:],
        "places": read_rows(DATA / "places.csv")[-150:],
        "story_timeline": read_rows(DATA / "story_timeline.csv")[-300:],
        "current_affairs": read_rows(DATA / "current_affairs.csv")[-250:],
    }


def build_messages(result: dict, today: str) -> list[str]:
    msgs = [f"🧠 <b>DAILY NEWS + KNOWLEDGE BRIEF</b>\n{today}\n\nAutomatic morning briefing • zero daily input"]
    top = result.get("top_stories", [])
    text = "🔥 <b>TOP NEWS</b>\n"
    for i, s in enumerate(top, 1):
        text += f"\n<b>{i}. {s.get('headline','')}</b> — {s.get('importance',0)}/100\n"
        text += f"<b>What:</b> {s.get('what','')}\n<b>Who:</b> {s.get('who','')}\n<b>When:</b> {s.get('when','')}\n<b>Where:</b> {s.get('where','')}\n<b>Why:</b> {s.get('why','')}\n<b>Why important:</b> {s.get('why_important','')}\n<b>Latest:</b> {s.get('latest_update','')}\n"
        sources = [u for u in s.get("sources", []) if u]
        if sources: text += "🔗 " + " | ".join(sources[:3]) + "\n"
    msgs.append(text)
    timeline = "📚 <b>STORY HISTORY & TIMELINES</b>\n"
    for s in top:
        events = s.get("timeline", [])
        if not events: continue
        timeline += f"\n<b>{s.get('headline','')}</b>\n"
        for e in events[:6]: timeline += f"• {e.get('date','')} — {e.get('headline','')}\n"
    if len(timeline) > 60: msgs.append(timeline)
    text = "📅 <b>CURRENT AFFAIRS</b>\n"
    for x in result.get("current_affairs", []): text += f"\n<b>{x.get('topic','')}</b> [{x.get('category','')}]\n{x.get('summary','')}\n🎯 {x.get('why_important','')}\n🔗 {x.get('source_url','')}\n"
    msgs.append(text)
    text = "🎭 <b>CULTURE & HERITAGE</b>\n"
    for x in result.get("culture", []): text += f"\n<b>{x.get('topic','')}</b> — {x.get('type','')}\n{x.get('explanation','')}\nOrigin: {x.get('origin','')}\nSignificance: {x.get('significance','')}\n🔗 {x.get('source_url','')}\n"
    text += "\n🕉️ <b>RELIGION & PHILOSOPHY</b>\n"
    for x in result.get("religion", []): text += f"\n<b>{x.get('tradition','')} — {x.get('topic','')}</b>\n{x.get('explanation','')}\nHistorical context: {x.get('historical_context','')}\n🔗 {x.get('source_url','')}\n"
    msgs.append(text)
    text = "🧠 <b>KNOWLEDGE BUILDER</b>\n"
    for s in top:
        for p in s.get("people", [])[:2]: text += f"\n👤 <b>{p.get('name','')}</b> — {p.get('role','')}\n{p.get('background','')}\n"
        for p in s.get("places", [])[:2]: text += f"\n📍 <b>{p.get('name','')}</b> — {p.get('location','')}\n{p.get('background','')}\n"
        for c in s.get("concepts", [])[:1]: text += f"\n💡 <b>{c.get('topic','')}</b>\n{c.get('explanation','')}\nRelated: {c.get('related_topics','')}\n"
    for c in result.get("connect_the_dots", [])[:5]: text += f"\n🔗 <b>{c.get('chain','')}</b>\n{c.get('explanation','')}\n"
    msgs.append(text)
    text = "🔤 <b>VOCABULARY</b>\n"; seen = set()
    for s in top:
        for v in s.get("vocabulary", []):
            word = v.get("word", "").strip().lower()
            if not word or word in seen: continue
            seen.add(word); text += f"\n<b>{v.get('word','')}</b> — {v.get('meaning','')}\nSimple: {v.get('simple_meaning','')}\nHindi: {v.get('hindi','')}\nExample: {v.get('example','')}\n"
    msgs.append(text)
    text = "🔄 <b>REVISION</b>\n"
    for x in result.get("revision", [])[:5]: text += f"\n<b>{x.get('topic','')}</b>\nQ: {x.get('question','')}\nA: {x.get('answer','')}\n"
    msgs.append(text)
    text = "❓ <b>DAILY QUIZ</b>\n"
    for i, q in enumerate(result.get("quiz", [])[:5], 1): text += f"\n<b>Q{i}.</b> {q.get('question','')}\nAnswer: {q.get('answer','')}\n"
    msgs.append(text)
    return msgs


def persist(result: dict, today: str):
    ensure_data(DATA)
    for s in result.get("top_stories", []):
        sources = s.get("sources") or [""]
        append_rows(DATA / "news_history.csv", [{"date":today,"story_id":s.get("story_id"),"headline":s.get("headline"),"source":sources[0],"url":sources[0],"category":s.get("category"),"importance":s.get("importance",0)}], HEADERS["news_history.csv"])
        for e in s.get("timeline", []): append_rows(DATA / "story_timeline.csv", [{"story_id":s.get("story_id"), **e}], HEADERS["story_timeline.csv"])
        for p in s.get("people", []): append_rows(DATA / "people.csv", [{**p,"last_seen":today}], HEADERS["people.csv"])
        for p in s.get("places", []): append_rows(DATA / "places.csv", [{**p,"last_seen":today}], HEADERS["places.csv"])
        for c in s.get("concepts", []): append_rows(DATA / "knowledge_cards.csv", [{"topic_id":c.get('topic','').lower().replace(' ','_'),**c,"first_seen":today,"last_reviewed":today,"review_count":1}], HEADERS["knowledge_cards.csv"])
        for v in s.get("vocabulary", []): append_rows(DATA / "vocabulary.csv", [{**v,"first_seen":today,"review_count":0,"next_review":today}], HEADERS["vocabulary.csv"])
    for x in result.get("current_affairs", []): append_rows(DATA / "current_affairs.csv", [{"date":today,**x}], HEADERS["current_affairs.csv"])
    for x in result.get("culture", []): append_rows(DATA / "culture.csv", [{"date":today,**x}], HEADERS["culture.csv"])
    for x in result.get("religion", []): append_rows(DATA / "religion.csv", [{"date":today,**x}], HEADERS["religion.csv"])
    for x in result.get("quiz", []): append_rows(DATA / "quiz_history.csv", [{"date":today,**x}], HEADERS["quiz_history.csv"])


def main():
    print("=" * 60); print("🧠 NEWS KNOWLEDGE BOT — PIPELINE TEST" if TEST_MODE else "🧠 NEWS KNOWLEDGE BOT — MORNING RUN"); print("=" * 60)
    log("Environment", "PASS", f"Python runtime ready; test_mode={TEST_MODE}")
    log("AI provider", "INFO", f"Local Ollama; model={configured_model()}")
    log("Credentials", "INFO", "No paid AI API key required")
    log("Credentials", "PASS" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "SKIP", "Telegram configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "Telegram secrets missing (delivery will be skipped)")
    ensure_data(DATA); log("CSV storage", "PASS", "Data directory and CSV schemas validated")
    cfg = load_sources(); limits = cfg.get("limits", {})
    try:
        articles = collect(cfg.get("sources", {}), limits.get("max_articles_per_source", 30), limits.get("max_total_articles", 500)); log("News collection", "PASS" if articles else "FAIL", f"Collected {len(articles)} articles")
    except Exception as exc:
        log("News collection", "FAIL", f"{type(exc).__name__}: {exc}");
        if not TEST_MODE: raise
        return
    today = datetime.now(IST).date().isoformat(); previous = history_snapshot(); learning = daily_learning(); log("Learning memory", "PASS", f"Loaded {sum(len(v) for v in previous.values())} historical rows")
    try:
        draft = generate([a.__dict__ for a in articles], previous, today, {"daily_learning": learning}); log("AI draft", "PASS", f"Generated {len(draft.get('top_stories', []))} candidate stories")
        historical = research_stories(draft.get("top_stories", [])[:limits.get("top_stories", 12)]); historical["daily_learning"] = learning; log("Historical research", "PASS", "Research stage completed")
        result = generate([a.__dict__ for a in articles], previous, today, historical); log("AI final briefing", "PASS", f"Selected {len(result.get('top_stories', []))} stories")
        persist(result, today); log("CSV persistence", "PASS", "Knowledge CSVs updated")
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            for message in build_messages(result, today): send_text(message)
            log("Telegram delivery", "PASS", "Morning messages sent")
        else: log("Telegram delivery", "SKIP", "Telegram secrets not configured")
        print(json.dumps({"date":today,"articles":len(articles),"stories":len(result.get('top_stories',[]))}, indent=2))
    except Exception as exc:
        log("Pipeline", "FAIL", f"{type(exc).__name__}: {exc}"); raise

if __name__ == "__main__": main()
