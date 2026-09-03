from __future__ import annotations

import csv
from pathlib import Path

HEADERS = {
    "news_history.csv": ["date", "story_id", "headline", "source", "url", "category", "importance", "region", "verification", "confidence"],
    "story_timeline.csv": ["story_id", "date", "headline", "event", "importance", "source", "url", "change_type"],
    "current_affairs.csv": ["date", "topic", "category", "summary", "why_important", "source_url", "region", "memory_hook"],
    "knowledge_cards.csv": ["topic_id", "topic", "category", "explanation", "related_topics", "first_seen", "last_reviewed", "review_count", "region", "memory_hook"],
    "vocabulary.csv": ["word", "meaning", "simple_meaning", "hindi", "example", "first_seen", "review_count", "next_review", "last_seen", "mastery"],
    "people.csv": ["name", "role", "background", "why_in_news", "last_seen"],
    "places.csv": ["name", "location", "background", "why_important", "last_seen"],
    "culture.csv": ["date", "topic", "type", "explanation", "origin", "significance", "source_url"],
    "religion.csv": ["date", "tradition", "topic", "explanation", "historical_context", "source_url"],
    "quiz_history.csv": ["date", "question", "answer", "topic", "difficulty", "region", "review_due"],
    "knowledge_graph.csv": ["date", "source_topic", "relation", "target_topic", "region", "confidence"],
    "learning_progress.csv": ["topic_id", "topic", "region", "first_seen", "last_seen", "exposure_count", "review_count", "next_review", "mastery", "priority"],
}


def _write(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ensure_data(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    for name, fields in HEADERS.items():
        path = root / name
        if not path.exists():
            _write(path, [], fields)
            continue
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                old_fields = reader.fieldnames or []
                rows = list(reader)
            if old_fields != fields:
                _write(path, rows, fields)
                print(f"[INFO] migrated {name} to Stage 5 schema", flush=True)
        except Exception as exc:
            print(f"[WARN] could not migrate {name}: {exc}", flush=True)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_rows(path: Path, rows: list[dict], fields: list[str]):
    if not rows:
        return
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)


def replace_rows(path: Path, rows: list[dict], fields: list[str]):
    _write(path, rows, fields)
