from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import OpenAI

from .settings import DATA, OPENAI_API_KEY, OPENAI_MODEL
from .storage import read_rows
from .telegram import send_text

IST = ZoneInfo("Asia/Kolkata")


def run_review(kind: str):
    if not OPENAI_API_KEY: raise RuntimeError("OPENAI_API_KEY is not configured")
    today = datetime.now(IST).date()
    start = today - timedelta(days=7 if kind == "weekly" else 31)
    payload = {
        "news": read_rows(DATA / "news_history.csv")[-500:],
        "knowledge": read_rows(DATA / "knowledge_cards.csv")[-300:],
        "vocabulary": read_rows(DATA / "vocabulary.csv")[-300:],
        "current_affairs": read_rows(DATA / "current_affairs.csv")[-300:],
        "quiz": read_rows(DATA / "quiz_history.csv")[-100:],
    }
    prompt = f"Create a {kind} knowledge review for the period starting {start} and ending {today}. Return concise Telegram-ready plain text. Include: top stories, important current-affairs facts, concepts learned, people/places, vocabulary revision, 5 quiz questions, and 5 'connect the dots' relationships. Focus on durable knowledge rather than repeating headlines. Data: {json.dumps(payload, ensure_ascii=False)[:80000]}"
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.responses.create(model=OPENAI_MODEL, instructions="You are a factual knowledge teacher. Use only supplied data; do not invent.", input=prompt)
    send_text(("📚 WEEKLY KNOWLEDGE REVIEW\n" if kind == "weekly" else "📚 MONTHLY KNOWLEDGE REVIEW\n") + response.output_text)


if __name__ == "__main__":
    import sys
    run_review(sys.argv[1] if len(sys.argv) > 1 else "weekly")
