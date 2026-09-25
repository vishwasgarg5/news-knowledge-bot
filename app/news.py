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
        return [x for x in terms if re.search(rf"\\b{re.escape(x)}\\b", text)]
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

