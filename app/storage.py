from __future__ import annotations

import csv
from pathlib import Path

HEADERS = {
    "news_history.csv": ["date", "story_id", "headline", "source", "url", "category", "importance"],
    "story_timeline.csv": ["story_id", "date", "headline", "event", "importance", "source", "url"],
    "current_affairs.csv": ["date", "topic", "category", "summary", "why_important", "source_url"],
    "knowledge_cards.csv": ["topic_id", "topic", "category", "explanation", "related_topics", "first_seen", "last_reviewed", "review_count"],
    "vocabulary.csv": ["word", "meaning", "simple_meaning", "hindi", "example", "first_seen", "review_count", "next_review"],
    "people.csv": ["name", "role", "background", "why_in_news", "last_seen"],
    "places.csv": ["name", "location", "background", "why_important", "last_seen"],
    "culture.csv": ["date", "topic", "type", "explanation", "origin", "significance", "source_url"],
    "religion.csv": ["date", "tradition", "topic", "explanation", "historical_context", "source_url"],
    "quiz_history.csv": ["date", "question", "answer", "topic", "difficulty"],
}


def ensure_data(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    for name, fields in HEADERS.items():
        path = root / name
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=fields).writeheader()


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_rows(path: Path, rows: list[dict], fields: list[str]):
    if not rows:
        return
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writerows(rows)


def replace_rows(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
