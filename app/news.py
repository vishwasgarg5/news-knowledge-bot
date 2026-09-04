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
    if cat in {"india", "national", "india_business", "india_technology", "india_defence"}:
        return "india"
    if cat in {"world", "international"}:
        return "world"
    text = f"{title} {summary}".lower()
    india_terms = ("india", "indian", "delhi", "mumbai", "bengaluru", "karnataka", "modi", "parliament", "rbi", "isro")
    return "india" if any(re.search(rf"\b{re.escape(x)}\b", text) for x in india_terms) else "world"


def fetch_feed(url: str, category: str, limit: int = 30) -> tuple[list[Article], bool, str]:
    parsed = feedparser.parse(url)
    entries = getattr(parsed, "entries", [])
    if getattr(parsed, "bozo", False) and not entries:
        return [], False, str(getattr(parsed, "bozo_exception", "invalid/empty feed"))
    source = parsed.feed.get("title", url)
    result = []
    for e in entries[:limit]:
        title = _clean(e.get("title", ""))
        link = e.get("link", "")
        if not title or not link:
            continue
        summary = _clean(e.get("summary", e.get("description", "")))
        aid = hashlib.sha256((title.lower() + "|" + link).encode()).hexdigest()[:16]
        result.append(Article(title, summary[:1600], link, source, category, _date(e), aid, _region(category, title, summary)))
    return result, bool(result), ""


def _title_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _near_duplicate(a: Article, b: Article) -> bool:
    if a.url == b.url:
        return True
    x, y = _title_tokens(a.title), _title_tokens(b.title)
    return len(x & y) / max(1, len(x | y)) >= 0.62


def collect(sources: dict, per_source: int = 30, max_total: int = 700) -> tuple[list[Article], dict]:
    all_articles: list[Article] = []
    source_status = []
    for category, urls in sources.items():
        for url in urls:
            try:
                items, ok, error = fetch_feed(url, category, per_source)
                all_articles.extend(items)
                source_status.append({"url": url, "category": category, "ok": ok, "count": len(items), "error": error})
            except Exception as exc:
                source_status.append({"url": url, "category": category, "ok": False, "count": 0, "error": str(exc)})
                print(f"feed failed: {url}: {exc}", flush=True)
            time.sleep(0.05)

    unique: list[Article] = []
    seen_ids = set()
    for article in all_articles:
        if article.article_id in seen_ids:
            continue
        if any(_near_duplicate(article, existing) for existing in unique):
            continue
        seen_ids.add(article.article_id)
        unique.append(article)

    return unique[:max_total], {
        "scanned": len(all_articles),
        "unique": len(unique[:max_total]),
        "exact_duplicates": len(all_articles) - len({a.article_id for a in all_articles}),
        "semantic_filtered": max(0, len({a.article_id for a in all_articles}) - len(unique)),
        "source_status": source_status,
        "source_failures": sum(not x["ok"] for x in source_status),
    }
