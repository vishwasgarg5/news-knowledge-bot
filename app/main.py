from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .ai import generate
from .news import collect
from .settings import CONFIG, DATA
from .storage import HEADERS, append_rows, ensure_data, read_rows
from .telegram import send_text


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
        for e in events[:6]:
            timeline += f"• {e.get('date','')} — {e.get('headline','')}\n"
    if len(timeline) > 60: msgs.append(timeline)

    ca = result.get("current_affairs", [])
    text = "📅 <b>CURRENT AFFAIRS</b>\n"
    for x in ca:
        text += f"\n<b>{x.get('topic','')}</b> [{x.get('category','')}]\n{x.get('summary','')}\n🎯 {x.get('why_important','')}\n🔗 {x.get('source_url','')}\n"
    msgs.append(text)

    culture = result.get("culture", [])
    religion = result.get("religion", [])
    text = "🎭 <b>CULTURE & HERITAGE</b>\n"
    for x in culture:
        text += f"\n<b>{x.get('topic','')}</b> — {x.get('type','')}\n{x.get('explanation','')}\nOrigin: {x.get('origin','')}\nSignificance: {x.get('significance','')}\n🔗 {x.get('source_url','')}\n"
    text += "\n🕉️ <b>RELIGION & PHILOSOPHY</b>\n"
    for x in religion:
        text += f"\n<b>{x.get('tradition','')} — {x.get('topic','')}</b>\n{x.get('explanation','')}\nHistorical context: {x.get('historical_context','')}\n🔗 {x.get('source_url','')}\n"
    msgs.append(text)

    text = "🧠 <b>KNOWLEDGE BUILDER</b>\n"
    for s in top:
        for p in s.get("people", [])[:2]: text += f"\n👤 <b>{p.get('name','')}</b> — {p.get('role','')}\n{p.get('background','')}\n"
        for p in s.get("places", [])[:2]: text += f"\n📍 <b>{p.get('name','')}</b> — {p.get('location','')}\n{p.get('background','')}\n"
        for c in s.get("concepts", [])[:1]: text += f"\n💡 <b>{c.get('topic','')}</b>\n{c.get('explanation','')}\nRelated: {c.get('related_topics','')}\n"
    for c in result.get("connect_the_dots", [])[:5]: text += f"\n🔗 <b>{c.get('chain','')}</b>\n{c.get('explanation','')}\n"
    msgs.append(text)

    text = "🔤 <b>VOCABULARY</b>\n"
    seen = set()
    for s in top:
        for v in s.get("vocabulary", []):
            if v.get('word','').lower() in seen: continue
            seen.add(v.get('word','').lower())
            text += f"\n<b>{v.get('word','')}</b> — {v.get('meaning','')}\nSimple: {v.get('simple_meaning','')}\nHindi: {v.get('hindi','')}\nExample: {v.get('example','')}\n"
    msgs.append(text)

    text = "🔄 <b>REVISION</b>\n"
    for x in result.get("revision", [])[:5]: text += f"\n<b>{x.get('topic','')}</b>\nQ: {x.get('question','')}\nA: {x.get('answer','')}\n"
    msgs.append(text)

    text = "❓ <b>DAILY QUIZ</b>\n"
    for i, q in enumerate(result.get("quiz", [])[:5], 1): text += f"\n<b>Q{i}.</b> {q.get('question','')}\nAnswer: ||{q.get('answer','')}||\n"
    msgs.append(text)
    return msgs


def persist(result: dict, today: str):
    ensure_data(DATA)
    for s in result.get("top_stories", []):
        for e in s.get("timeline", []):
            append_rows(DATA / "story_timeline.csv", [{"story_id":s.get("story_id"), **e}], HEADERS["story_timeline.csv"])
        for p in s.get("people", []):
            append_rows(DATA / "people.csv", [{**p, "last_seen":today}], HEADERS["people.csv"])
        for p in s.get("places", []):
            append_rows(DATA / "places.csv", [{**p, "last_seen":today}], HEADERS["places.csv"])
        for c in s.get("concepts", []):
            append_rows(DATA / "knowledge_cards.csv", [{"topic_id":c.get('topic','').lower().replace(' ','_'), **c, "first_seen":today, "last_reviewed":today, "review_count":1}], HEADERS["knowledge_cards.csv"])
        for v in s.get("vocabulary", []):
            append_rows(DATA / "vocabulary.csv", [{**v, "first_seen":today, "review_count":0, "next_review":today}], HEADERS["vocabulary.csv"])
    for x in result.get("current_affairs", []):
        append_rows(DATA / "current_affairs.csv", [{"date":today, **x}], HEADERS["current_affairs.csv"])
    for x in result.get("culture", []):
        append_rows(DATA / "culture.csv", [{"date":today, **x}], HEADERS["culture.csv"])
    for x in result.get("religion", []):
        append_rows(DATA / "religion.csv", [{"date":today, **x}], HEADERS["religion.csv"])
    for x in result.get("quiz", []):
        append_rows(DATA / "quiz_history.csv", [{"date":today, **x}], HEADERS["quiz_history.csv"])


def main():
    ensure_data(DATA)
    cfg = load_sources()
    limits = cfg.get("limits", {})
    articles = collect(cfg.get("sources", {}), limits.get("max_articles_per_source", 30), limits.get("max_total_articles", 500))
    previous = history_snapshot()
    result = generate([a.__dict__ for a in articles], previous, datetime.now(timezone.utc).date().isoformat())
    today = datetime.now(timezone.utc).date().isoformat()
    persist(result, today)
    for message in build_messages(result, today):
        send_text(message)
    print(json.dumps({"articles":len(articles),"stories":len(result.get('top_stories',[]))}, indent=2))

if __name__ == "__main__":
    main()
