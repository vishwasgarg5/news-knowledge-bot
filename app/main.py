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
RUN_SLOT = os.getenv("RUN_SLOT", "morning").lower()


def load_sources():
    with CONFIG.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def sim(a, b):
    x = set(re.findall(r"[a-z]{4,}", str(a).lower()))
    y = set(re.findall(r"[a-z]{4,}", str(b).lower()))
    return len(x & y) / max(1, len(x | y))


def previous_change(stories, timeline, today):
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
    old = [r.get("headline", "") for r in timeline if r.get("date") == yesterday]
    for story in stories:
        story["change_since_yesterday"] = (
            "Continuing" if any(sim(story.get("headline", ""), x) >= 0.48 for x in old) else "New today"
        )
    return stories


def _history_line(story):
    verification = story.get("verification") or {}
    history = verification.get("historical") or []
    if not history:
        return "No close prior story found"
    first = history[0]
    date = first.get("date", "") or "prior"
    source = first.get("source", "") or "memory"
    title = first.get("title", "").strip()
    if len(title) > 150:
        title = title[:147].rstrip() + "..."
    return f"{date}: {title} · {source}"


def persist(stories, today):
    path = DATA / "news_history.csv"
    rows = read_rows(path)
    ids = {r.get("story_id") for r in rows}
    timeline_path = DATA / "story_timeline.csv"
    timeline = read_rows(timeline_path)
    keys = {(r.get("story_id"), r.get("date")) for r in timeline}
    added = 0

    for story in stories:
        sid = story.get("story_id")
        verification = story.get("verification") or {}
        if sid and sid not in ids:
            append_rows(
                path,
                [{
                    "date": today,
                    "story_id": sid,
                    "headline": story.get("headline", ""),
                    "source": story.get("source", ""),
                    "url": story.get("url", ""),
                    "category": story.get("category", ""),
                    "importance": story.get("importance", 0),
                    "region": story.get("region", "world"),
                    "verification": verification.get("verification", ""),
                    "confidence": verification.get("confidence", ""),
                }],
                HEADERS["news_history.csv"],
            )
            ids.add(sid)
            added += 1

        if sid and (sid, today) not in keys:
            append_rows(
                timeline_path,
                [{
                    "story_id": sid,
                    "date": today,
                    "headline": story.get("headline", ""),
                    "event": story.get("what", story.get("headline", "")),
                    "importance": story.get("importance", 0),
                    "source": story.get("source", ""),
                    "url": story.get("url", ""),
                    "change_type": story.get("change_since_yesterday", ""),
                }],
                HEADERS["story_timeline.csv"],
            )
            keys.add((sid, today))

    return added


def _story_block(story, index, total):
    flag = "🇮🇳" if story.get("region") == "india" else "🌍"
    verification = story.get("verification") or {}
    return (
        f"{flag} <b>{index}/{total} · {story.get('headline', '')}</b>\n"
        f"🔴 {story.get('what', '')}\n"
        f"❓ {story.get('why', '')}\n"
        f"💡 {story.get('why_important', '')}\n"
        f"🕰️ {_history_line(story)}\n"
        f"🔄 {story.get('change_since_yesterday', '')}\n"
        f"🔮 {story.get('next', '')}\n"
        f"🧠 {story.get('memory_hook', '')}\n"
        f"🔎 {verification.get('verification', 'unverified')} · {verification.get('confidence', 'n/a')}% · {verification.get('source_count', 0)} src"
    )


def build_messages(result, today, stats):
    stories = result.get("top_stories", [])
    label = "MORNING" if RUN_SLOT == "morning" else "AFTERNOON"
    messages = []

    for region, title in (("india", "🇮🇳 INDIA"), ("world", "🌍 WORLD")):
        group = [s for s in stories if s.get("region") == region]
        if not group:
            continue
        blocks = [
            f"📰 <b>{title} · {label}</b>",
            "EVENT ↓ WHY ↓ IMPACT ↓ HISTORY ↓ CHANGE ↓ NEXT ↓ REMEMBER ↓ VERIFY",
            "",
        ]
        for index, story in enumerate(group, 1):
            blocks.append(_story_block(story, index, len(group)) + "\n")
        messages.append("\n".join(blocks).strip())

    messages.append(
        f"📊 <b>{label} · NEWS STATUS</b>\n"
        f"🇮🇳 {sum(s.get('region') == 'india' for s in stories)}  |  🌍 {sum(s.get('region') == 'world' for s in stories)}\n"
        f"📰 scanned {stats['articles']} · selected {stats['stories']} · verified {stats['verified']}/{stats['total']}\n"
        f"♻️ filtered {stats['filtered']} · {stats['runtime']} · model {configured_model()}"
    )
    return messages


def main():
    started = time.monotonic()
    ensure_data(DATA)
    cfg = load_sources()
    limits = cfg.get("limits", {})

    articles = collect(
        cfg.get("sources", {}),
        limits.get("max_articles_per_source", 40),
        limits.get("max_total_articles", 700),
    )

    today = datetime.now(IST).date().isoformat()
    history = read_rows(DATA / "news_history.csv")
    timeline = read_rows(DATA / "story_timeline.csv")
    # Morning avoids repeating the same delivered stories; afternoon is allowed to
    # revisit them so continuing stories and late-day changes are not lost.
    delivered_today = (
        [r.get("headline", "") for r in history if r.get("date") == today]
        if RUN_SLOT == "morning" else []
    )
    all_articles = [article.__dict__ for article in articles]

    selected = select_stories(
        all_articles,
        top_n=limits.get("top_stories", 12),
        excluded_headlines=delivered_today,
    )
    selected = previous_change(selected, timeline, today)

    # Timeline is the real historical memory: unlike news_history, it records
    # every daily appearance of a continuing story.
    research = research_stories(selected, timeline, all_articles)
    research_stats = research.pop("_stats", {})
    result = generate_briefing(selected, all_articles, timeline, today, research)

    for story in result.get("top_stories", []):
        story["verification"] = research.get(story.get("story_id"), {})
        story["source"] = next(
            (article.get("source", "") for article in all_articles if article.get("url") == story.get("url")),
            "",
        )

    added = persist(result.get("top_stories", []), today)
    runtime = f"{time.monotonic() - started:.1f}s"
    stats = {
        "articles": len(articles),
        "filtered": max(0, len(all_articles) - len(selected)),
        "stories": len(result.get("top_stories", [])),
        "verified": research_stats.get("ok", 0),
        "total": research_stats.get("total", len(selected)),
        "runtime": runtime,
    }

    print(
        f"[PASS] FINAL NEWS INTELLIGENCE | model={configured_model()} | "
        f"stories={stats['stories']} | verified={stats['verified']}/{stats['total']} | new={added}",
        flush=True,
    )

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for message in build_messages(result, today, stats):
            send_text(message)


if __name__ == "__main__":
    main()
