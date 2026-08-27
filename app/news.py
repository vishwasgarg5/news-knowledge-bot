from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime

import feedparser
import requests

@dataclass
class Article:
    title: str
    summary: str
    url: str
    source: str
    category: str
    published: str
    article_id: str


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _date(entry) -> str:
    raw = entry.get("published") or entry.get("updated") or ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def fetch_feed(url: str, category: str, limit: int = 30) -> list[Article]:
    parsed = feedparser.parse(url)
    source = parsed.feed.get("title", url)
    result = []
    for e in parsed.entries[:limit]:
        title = _clean(e.get("title", ""))
        link = e.get("link", "")
        if not title or not link:
            continue
        summary = _clean(e.get("summary", e.get("description", "")))
        aid = hashlib.sha256((title.lower() + "|" + link).encode()).hexdigest()[:16]
        result.append(Article(title, summary[:1200], link, source, category, _date(e), aid))
    return result


def collect(sources: dict, per_source: int = 30, max_total: int = 500) -> list[Article]:
    all_articles: list[Article] = []
    for category, urls in sources.items():
        for url in urls:
            try:
                all_articles.extend(fetch_feed(url, category, per_source))
            except Exception as exc:
                print(f"feed failed: {url}: {exc}")
            time.sleep(0.1)
    unique = {}
    for a in all_articles:
        unique.setdefault(a.article_id, a)
    return list(unique.values())[:max_total]
