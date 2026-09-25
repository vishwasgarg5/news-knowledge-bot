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
    region_confidence: float = 0.0
    region_evidence: str = ""


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


def _region(category: str, title: str, summary: str) -> tuple[str, float, str]:
    """Classify the geography of the actual event using explicit evidence.

    Feed category is only a weak fallback. Explicit international locations/actors
    override incidental India mentions, and ambiguous items remain World rather than
    being forced into the India quota.
    """
    title_text=str(title or "").lower()
    body_text=f"{title} {summary}".lower()
    india_terms=("india","indian","delhi","mumbai","bengaluru","karnataka","kolkata","wayanad","modi","parliament","rbi","isro","trinamool","tamil nadu","uttar pradesh","west bengal","maharashtra","haryana","supreme court","election commission of india","cec")
    world_terms=("united states","u.s.","america","mexico","hawaii","china","xi jinping","trump","ukraine","russia","europe","britain","australia","ethiopia","poland","gaza","israel","nato","united nations","bangladesh","south africa","thailand","czech","czechia","finland","nokia","canada","iran","japan","korea","taiwan")
    def hits(text, terms):
        return [x for x in terms if re.search(rf"\b{re.escape(x)}\b", text)]
    ti=hits(title_text,india_terms); tw=hits(title_text,world_terms)
    bi=hits(body_text,india_terms); bw=hits(body_text,world_terms)
    # Headline geography is strongest: a concrete foreign place/actor in the
    # headline must not become an India story just because the feed is Indian.
    if tw and not ti:
        return "world", min(1.0, 0.72 + 0.08*len(tw)), "headline: " + ", ".join(tw[:4])
    if ti and not tw:
        return "india", min(1.0, 0.78 + 0.07*len(ti)), "headline: " + ", ".join(ti[:4])
    if tw and ti:
        # A foreign event plus only an incidental India reference is World.
        if len(tw) > len(ti) or any(x in tw for x in ("mexico","hawaii","china","australia","united states","u.s.","israel","iran")):
            return "world", 0.82, "headline mixed; foreign anchor: " + ", ".join(tw[:4])
        return "india", 0.76, "headline mixed; India anchor: " + ", ".join(ti[:4])
    if bw and not bi:
        return "world", min(0.95, 0.60 + 0.07*len(bw)), "body: " + ", ".join(bw[:5])
    if bi and not bw:
        return "india", min(0.94, 0.64 + 0.07*len(bi)), "body: " + ", ".join(bi[:5])
    if bw and bi:
        return ("world", 0.68, "body mixed; foreign anchors: " + ", ".join(bw[:4])) if len(bw) >= len(bi) else ("india", 0.66, "body mixed; India anchors: " + ", ".join(bi[:4]))
    # No geographic evidence: do not manufacture India relevance from the feed.
    # World is the safe bucket for the 15+15 selector; low-confidence items can
    # be inspected in the audit rather than silently filling the India quota.
    return "world", 0.35, "no explicit geographic evidence"



def fetch_feed(url: str, category: str, limit: int = 30) -> tuple[list[Article], bool, str]:
    parsed = feedparser.parse(url)
    entries = getattr(parsed, "entries", [])
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
        region, region_confidence, region_evidence = _region(category, title, summary)
        result.append(Article(title, summary[:1600], link, source, category, _date(e), aid, region, region_confidence, region_evidence))
    return result, bool(result), parse_warning


def _freshness_score(published: str) -> float:
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
