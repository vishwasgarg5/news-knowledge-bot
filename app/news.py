from __future__ import annotations

import hashlib
import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
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
    region: str = "world"
    region_confidence: float = 0.0
    region_evidence: str = ""
    summary_selected_field: str | None = None
    summary_field_diagnostics: dict[str, str] = field(default_factory=dict)


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _summary_field_provenance(entry) -> tuple[str | None, dict[str, str]]:
    """Report which original RSS/Atom summary fields were present and usable."""
    keys = (
        "summary", "description", "subtitle",
        "summary_detail", "description_detail", "subtitle_detail",
        "media_description", "itunes_summary", "content",
    )
    diagnostics = {
        key: (
            "missing_key" if key not in entry else
            "present" if _summary_text({key: entry.get(key, "")}) else
            "blank"
        )
        for key in keys
    }
    selected = next((key for key in keys if diagnostics[key] == "present"), None)
    return selected, diagnostics


def _summary_text(entry) -> str:
    """Extract publisher-provided summary text across common RSS/Atom field shapes."""
    def clean_value(value) -> str:
        # feedparser detail fields and namespaced extensions may be mappings,
        # not plain strings. Read only their actual text/value fields.
        if isinstance(value, dict):
            value = value.get("value") or value.get("text") or value.get("summary") or ""
        if isinstance(value, (list, tuple)):
            value = " ".join(
                str(item.get("value") or item.get("text") or "")
                if isinstance(item, dict) else str(item or "")
                for item in value
            )
        cleaned = " ".join(re.sub(r"<[^>]*>", " ", html.unescape(str(value or ""))).split())
        return re.sub(r"\s+([.,;:!?])", r"\1", cleaned)

    # Standard RSS/Atom names come first; detail and namespaced fields are
    # fallbacks when a parser exposes publisher-provided text separately.
    for key in (
        "summary", "description", "subtitle",
        "summary_detail", "description_detail", "subtitle_detail",
        "media_description", "itunes_summary",
    ):
        cleaned = clean_value(entry.get(key, ""))
        if cleaned:
            return cleaned[:1600]

    content = entry.get("content", []) or []
    if isinstance(content, dict):
        content = [content]
    for item in content:
        cleaned = clean_value(item)
        if cleaned:
            return cleaned[:1600]
    return ""

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
    """Classify the geography of the actual event, not the feed it came from."""
    title_text=str(title or "").lower()
    body_text=f"{title} {summary}".lower()
    india_terms=("india","indian","delhi","mumbai","bengaluru","karnataka","kolkata","wayanad","modi","parliament","rbi","isro","trinamool","tamil nadu","uttar pradesh","west bengal","maharashtra","haryana","tamil nadu","t.n.","coimbatore","chennai","bombay","iit bombay","iit-bombay","azad maidan","cbi","mahadev","kashmiri pandits","goa","election commission of india","cec","eci","obc","creamy layer","union government","central government","assembly constituency","lok sabha","rajya sabha","rupee","crore","lakh","asian games","shaili singh","shaili","ancy sojan","pv sindhu","sindhu","tajinderpal","neeraj chopra","avni lekhara","manu bhaker","india team","indian team")
    world_terms=("united states","u.s.","us banks","american banks","america","france","french","paris","germany","german","berlin","spain","spanish","madrid","italy","italian","rome","switzerland","swiss","sweden","swedish","norway","norwegian","denmark","danish","netherlands","dutch","amsterdam","belgium","belgian","portugal","lisbon","ireland","irish","london","british","scotland","wales","turkey","turkish","istanbul","saudi arabia","riyadh","united arab emirates","uae","dubai","qatar","egypt","cairo","nigeria","kenya","brazil","brazilian","argentina","chile","colombia","indonesia","malaysia","singapore","philippines","vietnam","pakistan","islamabad","nepal","sri lanka","myanmar","cambodia","mongolia","european union","european","mexico","hawaii","china","xi jinping","trump","ukraine","russia","europe","britain","australia","ethiopia","poland","gaza","israel","nato","united nations","bangladesh","south africa","thailand","czech","czechia","finland","nokia","canada","canadian","alberta","iran","japan","korea","taiwan","nebraska","new york city","new york","california","texas","florida","washington","washington dc","illinois","pennsylvania","ohio","michigan","massachusetts","virginia","georgia","colorado","arizona","seattle","boston","chicago","los angeles","san francisco","washington state")
    strong_india=("india","indian","delhi","mumbai","bengaluru","karnataka","kolkata","modi","rbi","isro","trinamool","tamil nadu","uttar pradesh","west bengal","maharashtra","haryana","bombay","iit bombay","azad maidan","cbi","mahadev","election commission of india","cec","eci","obc","creamy layer","union government","lok sabha","rajya sabha","t.n.","coimbatore","chennai","shaili singh","ancy sojan","pv sindhu","sindhu","tajinderpal","neeraj chopra","india team","indian team")
    strong_world=("mexico","hawaii","canada","canadian","alberta","france","french","paris","germany","german","berlin","spain","spanish","madrid","italy","italian","rome","switzerland","swiss","sweden","swedish","norway","norwegian","denmark","danish","netherlands","dutch","amsterdam","belgium","belgian","portugal","lisbon","ireland","irish","london","british","scotland","wales","turkey","turkish","istanbul","saudi arabia","riyadh","united arab emirates","uae","dubai","qatar","egypt","cairo","nigeria","kenya","brazil","brazilian","argentina","chile","colombia","indonesia","malaysia","singapore","philippines","vietnam","pakistan","islamabad","nepal","sri lanka","myanmar","cambodia","mongolia","us banks","american banks","european union","european","china","xi jinping","trump","australia","ukraine","russia","gaza","israel","nato","iran","japan","taiwan","united states","u.s.","united nations","nebraska","new york city","california","texas","florida","washington","illinois","pennsylvania","ohio","michigan","massachusetts","virginia","georgia","colorado","arizona","seattle","boston","chicago","los angeles","san francisco")
    def hits(text, terms):
        return [x for x in terms if re.search(rf"\b{re.escape(x)}\b", text)]
    ti=hits(title_text,india_terms); tw=hits(title_text,world_terms)
    bi=hits(body_text,india_terms); bw=hits(body_text,world_terms)
    si=hits(title_text,strong_india); sw=hits(title_text,strong_world)
    if si and not sw:
        return "india",min(1.0,0.86+0.04*len(si)),"headline India anchors: "+", ".join(si[:5])
    if sw and not si:
        return "world",min(1.0,0.86+0.04*len(sw)),"headline World anchors: "+", ".join(sw[:5])
    # A U.S./international Trump story mentioning the U.S. Supreme Court must not be classified as India merely because "Supreme Court" is present.
    if "trump" in title_text and not any(x in title_text for x in ("india","indian","modi","delhi","mumbai")):
        return "world",0.94,"headline World anchor: trump"
    if si and sw:
        if len(sw)>len(si): return "world",0.88,"headline mixed; stronger World anchors: "+", ".join(sw[:5])
        return "india",0.88,"headline mixed; stronger India anchors: "+", ".join(si[:5])
    if ti and not tw:
        return "india",min(0.86,0.76+0.05*len(ti)),"headline India evidence: "+", ".join(ti[:5])
    if tw and not ti:
        return "world",min(0.86,0.76+0.05*len(tw)),"headline World evidence: "+", ".join(tw[:5])
    if bi and not bw:
        return "india",min(0.90,0.70+0.05*len(bi)),"body India evidence: "+", ".join(bi[:6])
    if bw and not bi:
        return "world",min(0.90,0.70+0.05*len(bw)),"body World evidence: "+", ".join(bw[:6])
    if bi and bw:
        india_score=sum(3 if x in strong_india else 1 for x in bi)
        world_score=sum(3 if x in strong_world else 1 for x in bw)
        if world_score >= india_score:
            return "world",0.76,"body mixed; World anchors: "+", ".join(bw[:5])
        return "india",0.76,"body mixed; India anchors: "+", ".join(bi[:5])
    if str(category or "").lower() in {"india","national"}:
        return "india",0.58,"category fallback: "+str(category)
    return "world",0.35,"no explicit geographic evidence"


def fetch_feed(url: str, category: str, limit: int = 30) -> tuple[list[Article], bool, str]:
    # Fetch explicitly instead of relying on feedparser's implicit HTTP client:
    # this gives every publisher a consistent User-Agent, bounded timeouts and
    # auditable HTTP status/error messages when feeds are blocked or unavailable.
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "NewsKnowledgeBot/1.0 (+https://github.com/vishwasgarg5/news-knowledge-bot; RSS reader)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
            timeout=(5, 15),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f"HTTP {status}: {exc}" if status else f"request failed: {exc}"
        return [], False, detail

    parsed = feedparser.parse(response.content)
    entries = getattr(parsed, "entries", [])
    if not entries:
        status = getattr(response, "status_code", "unknown")
        content_type = str(getattr(response, "headers", {}).get("Content-Type", "unknown"))[:80]
        parser_error = str(getattr(parsed, "bozo_exception", "") or "").strip()
        detail = f"empty feed (HTTP {status}, content-type={content_type})"
        if parser_error:
            detail += f"; parser={parser_error[:180]}"
        return [], False, detail
    parse_warning = ""
    if getattr(parsed, "bozo", False):
        parse_warning = str(getattr(parsed, "bozo_exception", "malformed feed"))
    source = parsed.feed.get("title", url)
    result = []
    missing_summary_diagnostics = 0
    summary_fields = (
        "summary", "description", "subtitle", "summary_detail",
        "description_detail", "subtitle_detail", "media_description",
        "itunes_summary", "content",
    )
    for e in entries[:limit]:
        title = _clean(e.get("title", ""))
        link = e.get("link", "")
        if not title or not link:
            continue
        summary = _summary_text(e)
        summary_selected_field, summary_field_diagnostics = _summary_field_provenance(e)
        if not summary and missing_summary_diagnostics < 3:
            present_fields = [
                key for key in summary_fields
                if _summary_text({key: e.get(key, "")})
            ]
            field_shapes = []
            for key in summary_fields:
                if key not in e or e.get(key) is None:
                    continue
                value = e.get(key)
                if isinstance(value, str):
                    shape = f"string(len={len(value)})"
                elif isinstance(value, dict):
                    nested = [
                        f"{nested_key}:len={len(str(nested_value or ''))}"
                        for nested_key, nested_value in value.items()
                        if nested_key in ("value", "text", "summary")
                    ]
                    shape = "mapping(" + ",".join(nested[:3]) + ")"
                elif isinstance(value, (list, tuple)):
                    shape = f"{type(value).__name__}(items={len(value)})"
                else:
                    shape = type(value).__name__
                field_shapes.append(f"{key}={shape}")
            print(
                "[SUMMARY FIELD GAP] "
                f"source={source} title={title[:160]} "
                f"publisher_summary_fields_present={present_fields or 'none'} "
                f"publisher_summary_field_shapes={field_shapes or 'none'} "
                f"entry_keys={sorted(str(key) for key in e.keys())[:30]}",
                flush=True,
            )
            missing_summary_diagnostics += 1
        aid = hashlib.sha256((title.lower() + "|" + link).encode()).hexdigest()[:16]
        region, region_confidence, region_evidence = _region(category, title, summary)
        result.append(Article(
            title, summary[:1600], link, source, category, _date(e), aid,
            region, region_confidence, region_evidence,
            summary_selected_field=summary_selected_field,
            summary_field_diagnostics=summary_field_diagnostics,
        ))
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
                missing_summaries = [article for article in items if not _clean(article.summary)]
                source_status.append({
                    "url": url,
                    "category": category,
                    "ok": ok,
                    "count": len(items),
                    "error": error,
                    "warning": bool(ok and error),
                    "summary_missing_count": len(missing_summaries),
                    "missing_summary_examples": [
                        {"title": article.title, "url": article.url}
                        for article in missing_summaries[:3]
                    ],
                })
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
