from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import feedparser

@dataclass
class Article:
    title: str
    summary: str
    url: str
    source: str
    category: str
    published: str
    article_id: str
    region: str = "world"


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _date(entry) -> str:
    raw = entry.get("published") or entry.get("updated") or ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def _region(category: str, title: str, summary: str) -> str:
    cat = str(category).lower()
    text = f"{title} {summary}".lower()
    if cat in {"india", "national", "india_business", "india_technology", "india_defence"}:
        return "india"
    india_terms = ("india", "indian", "delhi", "mumbai", "bengaluru", "karnataka", "modi", "parliament", "rbi", "isro", "supreme court")
    return "india" if any(re.search(rf"\b{re.escape(x)}\b", text) for x in india_terms) else "world"


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
        result.append(Article(title, summary[:1600], link, source, category, _date(e), aid, _region(category, title, summary)))
    return result


def collect(sources: dict, per_source: int = 30, max_total: int = 700) -> list[Article]:
    all_articles: list[Article] = []
    for category, urls in sources.items():
        for url in urls:
            try:
                all_articles.extend(fetch_feed(url, category, per_source))
            except Exception as exc:
                print(f"feed failed: {url}: {exc}", flush=True)
            time.sleep(0.05)
    unique = {}
    for a in all_articles:
        unique.setdefault(a.article_id, a)
    return list(unique.values())[:max_total]
