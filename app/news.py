from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            dt = datetime(*parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(raw)


def _region(category: str, title: str, summary: str) -> str:
    """Classify the geography of the actual event, not merely the feed category."""
    text=f"{title} {summary}".lower()
    india_terms=("india","indian","delhi","mumbai","bengaluru","karnataka","kolkata","wayanad","modi","parliament","rbi","isro","trinamool","tamil nadu","uttar pradesh","west bengal")
    world_terms=("united states","u.s.","america","china","xi jinping","trump","ukraine","russia","europe","britain","australia","ethiopia","poland","gaza","israel","nato","united nations")
    india_hits=sum(bool(re.search(rf"\b{re.escape(x)}\b",text)) for x in india_terms)
    world_hits=sum(bool(re.search(rf"\b{re.escape(x)}\b",text)) for x in world_terms)
    # A clear international actor/event in the headline takes precedence over
    # incidental India references in the summary.
    title_text=str(title).lower()
    title_world=sum(bool(re.search(rf"\b{re.escape(x)}\b",title_text)) for x in world_terms)
    title_india=sum(bool(re.search(rf"\b{re.escape(x)}\b",title_text)) for x in india_terms)
    if title_world and title_world >= title_india: return "world"
    if title_india and title_india > title_world: return "india"
    if world_hits > india_hits: return "world"
    if india_hits > world_hits: return "india"
    cat=str(category).lower()
    return "india" if cat in {"india","national","india_business","india_technology","india_defence"} else "world"

def fetch_feed(url: str, category: str, limit: int = 30) -> tuple[list[Article], bool, str]:
    parsed = feedparser.parse(url)
    entries = getattr(parsed, "entries", [])
    # feedparser can recover usable entries from some imperfect RSS/XML feeds.
    # Do not discard an entire source merely because its XML has a recoverable
    # parsing warning. Keep the warning visible in source_status so reliability
    # is still measurable, while preserving the usable articles.
    if not entries:
        return [], False, "empty feed"
    parse_warning = ""
    if getattr(parsed, "bozo", False):
        parse_warning = str(getattr(parsed, "bozo_exception", "malformed feed"))
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
    return result, bool(result), parse_warning


def _freshness_score(published: str) -> float:
    """Prefer genuinely current news; do not let stale feed entries dominate."""
    try:
        dt=datetime.fromisoformat(str(published).replace("Z","+00:00"))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        age=max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600)
        if age<=6: return 12.0
        if age<=24: return 8.0
        if age<=48: return 4.0
        if age<=72: return 1.0
        return -8.0
    except Exception:
        return -2.0

def _quality_penalty(article: Article) -> float:
    title=article.title.lower()
    summary=article.summary.lower()
    # Avoid feed noise: galleries, live blogs, opinion-only and very thin entries.
    penalty=0.0
    if len(article.title)<25: penalty+=3
    if len(summary)<80: penalty+=2
    if any(x in title for x in ("live updates","live:","photos","photo gallery","quiz","horoscope")): penalty+=5
    return penalty

def _title_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _near_duplicate(a: Article, b: Article) -> bool:
    if a.url == b.url:
        return True
    if str(a.source).strip().lower() != str(b.source).strip().lower():
        return False
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
                source_status.append({"url": url, "category": category, "ok": ok, "count": len(items), "error": error, "warning": bool(ok and error)})
            except Exception as exc:
                source_status.append({"url": url, "category": category, "ok": False, "count": 0, "error": str(exc), "warning": False})
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
        "source_warnings": sum(bool(x.get("warning")) for x in source_status),
    }
