from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser
import requests

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}
TRUST={"reuters":1.0,"associated press":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92,"reserve bank of india":1.0,"supreme court of india":1.0,"prime minister's office":0.98,"pm india":0.98,"ministry of defence":0.98,"isro":0.98,"nasa":0.98,"sebi":0.98,"ndtv":0.86,"indian express":0.90,"india today":0.82,"hindustan times":0.82,"the guardian":0.90,"al jazeera":0.85,"dw":0.85,"npr":0.85,"techcrunch":0.80}
OFFICIAL={"pib","reserve bank of india","rbi","supreme court of india","prime minister's office","pm india","ministry of defence","isro","nasa","sebi"}

def _tokens(text): return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}

# Normalize common inflections only for event matching. This helps independent
# publishers describe the same development with different verb forms without
# weakening the requirement for concrete event overlap.
_EVENT_ALIASES = {
    "announced":"announce", "announces":"announce", "announcing":"announce",
    "launched":"launch", "launches":"launch", "launching":"launch",
    "approved":"approve", "approves":"approve", "approving":"approve",
    "signed":"sign", "signs":"sign", "signing":"sign",
    "arrested":"arrest", "arrests":"arrest", "arresting":"arrest",
    "banned":"ban", "bans":"ban", "banning":"ban",
    "blocked":"block", "blocks":"block", "blocking":"block",
    "attacked":"attack", "attacks":"attack", "attacking":"attack",
    "killed":"kill", "kills":"kill", "killing":"kill",
    "injured":"injure", "injures":"injure", "injuring":"injure",
    "warned":"warn", "warns":"warn", "warning":"warn",
    "withdrawn":"withdraw", "withdraws":"withdraw", "withdrew":"withdraw",
    "reopened":"reopen", "reopens":"reopen", "reopening":"reopen",
    "ordered":"order", "orders":"order", "ordering":"order",
    "filed":"file", "files":"file", "filing":"file",
    "summoned":"summon", "summons":"summon", "summoning":"summon",
    "protested":"protest", "protests":"protest", "protesting":"protest",
    "sanctions":"sanction", "agreements":"agreement", "results":"result",
    "elections":"election", "voters":"voter", "deaths":"death",
}

def _event_tokens(text):
    words = re.findall(r"[a-z]{3,}", str(text or "").lower())
    return {_EVENT_ALIASES.get(word, word) for word in words if word not in STOP}

def _similar(a,b):
    x,y=_tokens(a),_tokens(b)
    if not x or not y: return 0.0
    return len(x&y)/max(1,len(x|y))

def _named_tokens(text):
    words=re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(text))
    generic={"supreme","court","high","delhi","assembly","government","president","prime","minister","chief","election","commission","police","video","india","indian","american","united","states","white","house","china"}
    return {w.lower().strip(".,") for w in words if w.lower() not in STOP and w.lower() not in generic}

def _event_similarity(a,b):
    """Conservative same-event matching; shared names/topics alone are insufficient."""
    ta,tb=_event_tokens(a),_event_tokens(b)
    common=ta&tb
    base=len(common)/max(1,len(ta|tb))
    event_terms={
        "breach","hack","attack","arrest","ban","block","access","launch",
        "deal","trade","truce","visit","arrive","intelligence","result",
        "election","judge","verdict","trial","crash","earthquake","cyclone","fire","flood",
        "death","die","kill","injure","strike","protest","approval","approve","agreement",
        "summit","sanction","dispute","ruling","order","warn","suspend",
        "win","silver","gold","medal","meeting","decision",
        "appoint","summon","file","sign","reopen","withdraw",
        "roll","voter","name","probe"
    }
    event_overlap=common&event_terms
    generic={"supreme","court","government","president","prime","minister","chief","election",
             "commission","india","world","news","today","latest","report","reports","officials","official"}
    distinctive=common-generic
    # Near-identical headlines can match directly. Otherwise require a shared
    # concrete action plus several distinctive shared terms, not just two names
    # (e.g. Trump/Russia/Putin in otherwise unrelated stories).
    if base>=0.72 and len(common)>=5:
        return base
    if event_overlap and len(common)>=4 and len(distinctive)>=3 and base>=0.25:
        return max(base,0.56)
    if len(event_overlap)>=2 and len(common)>=5 and base>=0.30:
        return max(base,0.56)
    return 0.0

def _strong_event_match(headline, primary_summary, article):
    """Evidence-level match requires both shared context and a shared action."""
    other=f"{article.get('title','')} {article.get('summary','')}"
    primary=f"{headline} {primary_summary}"
    na,nb=_named_tokens(primary),_named_tokens(other)
    common=_event_tokens(primary)&_event_tokens(other)
    event_terms={
        "attack","arrest","ban","block","breach","hack","kill","death","injure","crash","fire","flood","storm","cyclone",
        "landfall","protest","rule","verdict","order","approve","announce","launch","sign","summon","file","probe","investigation","withdraw",
        "reopen","election","vote","voter","medal","gold","silver","sanction","trade","agreement","summit","strike","resign"
    }
    events=common & event_terms
    named=na&nb
    generic={"government","president","minister","court","election","commission","india","world",
             "news","today","latest","report","reports","official"}
    distinctive=common-generic
    if named and events and len(distinctive)>=4:
        return True
    if events and len(distinctive)>=5:
        return True
    return False

ALIASES={
    "bbc news":"bbc","bbc":"bbc","reuters":"reuters","the hindu":"the hindu",
    "indian express":"indian express","associated press":"associated press",
    "ap news":"associated press","pib":"pib","press information bureau":"pib",
    "reserve bank of india":"reserve bank of india","rbi":"reserve bank of india",
    "deutsche welle":"dw","dw news":"dw","dw":"dw",
    "the guardian":"the guardian","guardian":"the guardian",
    "al jazeera english":"al jazeera","al jazeera":"al jazeera",
    "npr news":"npr","npr":"npr","cnn news":"cnn","cnn":"cnn",
    "the new york times":"the new york times","new york times":"the new york times",
    "the washington post":"the washington post","washington post":"the washington post",
    "financial times":"financial times","the financial times":"financial times",
    "bloomberg news":"bloomberg","bloomberg":"bloomberg",
    "the associated press":"associated press",
}
def _host_is(host, domain):
    """Match an exact domain or a true subdomain, never a lookalike suffix."""
    return host == domain or host.endswith("." + domain)


def _source_key(source, url=""):
    try:
        host=(urlparse(str(url or "")).hostname or "").lower().rstrip(".")
        if host.startswith("www."): host=host[4:]
        # Google News RSS wraps publisher links. Its source.title is the
        # publisher identity; do not collapse every result into news.google.com.
        if host and not _host_is(host, "news.google.com"):
            if _host_is(host, "bbc.co.uk") or _host_is(host, "bbc.com"): return "bbc"
            if _host_is(host, "reuters.com"): return "reuters"
            if _host_is(host, "thehindu.com"): return "the hindu"
            if _host_is(host, "indianexpress.com"): return "indian express"
            if _host_is(host, "apnews.com"): return "associated press"
            if _host_is(host, "pib.gov.in"): return "pib"
            if _host_is(host, "rbi.org.in"): return "reserve bank of india"
            if _host_is(host, "isro.gov.in"): return "isro"
            if _host_is(host, "nasa.gov"): return "nasa"
            if _host_is(host, "sebi.gov.in"): return "sebi"
            if _host_is(host, "pmindia.gov.in"): return "pm india"
            if _host_is(host, "pmo.gov.in"): return "prime minister's office"
            if _host_is(host, "sci.gov.in"): return "supreme court of india"
            if _host_is(host, "mod.gov.in"): return "ministry of defence"
            if _host_is(host, "ndtv.com"): return "ndtv"
            if _host_is(host, "theguardian.com"): return "the guardian"
            if _host_is(host, "aljazeera.com"): return "al jazeera"
            if _host_is(host, "dw.com"): return "dw"
            if _host_is(host, "npr.org"): return "npr"
            if _host_is(host, "techcrunch.com"): return "techcrunch"
            if _host_is(host, "timesofindia.indiatimes.com") or _host_is(host, "timesofindia.com"): return "times of india"
            if _host_is(host, "indiatoday.in"): return "india today"
            if _host_is(host, "hindustantimes.com"): return "hindustan times"
            return host
    except Exception:
        pass
    raw=str(source or "").lower().strip()
    # Source labels are untrusted metadata: only exact aliases receive canonical trust.
    return ALIASES.get(raw, raw)


def _source_trust(source_key):
    """Trust is granted to canonical publisher keys, not substrings in lookalike domains."""
    return float(TRUST.get(str(source_key or "").lower().strip(), 0.65))


TRUSTED_SINGLE_SOURCE = {
    "reuters", "bbc", "associated press", "the hindu", "indian express",
    "times of india", "pib", "nasa", "ndtv", "hindustan times",
    "india today", "the guardian", "al jazeera", "dw", "npr", "techcrunch",
}


def is_trusted_publisher(source, url=""):
    """Check single-source eligibility against the canonical URL publisher."""
    return _source_key(source, url) in TRUSTED_SINGLE_SOURCE

_ROUNDUP_RE=re.compile(
    r"\b(?:evening|morning|daily)\s+news\s+(?:brief|briefing|roundup|round-up)\b|"
    r"\b(?:top|main)\s+(?:stories|news)\b|"
    r"\b(?:news\s+)?(?:roundup|round-up|digest)\b|"
    r"\bnews\s+brief\b",
    re.I,
)

def _is_derivative_report(article):
    """Roundups/briefs may be useful for discovery but never count as independent corroboration."""
    title=str(article.get("title","") or article.get("headline","") or "")
    source=str(article.get("source","") or "")
    return bool(_ROUNDUP_RE.search(title) or _ROUNDUP_RE.search(source))
def _is_official(source): return _source_key(source) in OFFICIAL

def _memory_fallback(query:str,memory:list[dict],limit:int=5)->list[dict]:
    """Link only to a genuinely similar prior event, never to generic topic overlap."""
    generic={"first","time","year","people","says","said","news","latest","today","world","india","government","company","report","reports","according"}
    q=_tokens(query)-generic
    if len(q)<3: return []
    scored=[]
    current_day=datetime.now(timezone.utc).date().isoformat()
    for row in memory or []:
        row_date=str(row.get("date","") or "")[:10]
        if row_date and row_date >= current_day:
            continue
        title=str(row.get("headline","") or row.get("title",""))
        words=_tokens(title)-generic
        overlap=q&words
        ratio=len(overlap)/max(1,len(q|words))
        # Require several distinctive terms and substantial overlap. This keeps
        # unrelated stories about the same broad topic out of HISTORY.
        if len(overlap)>=3 and ratio>=0.34:
            scored.append((ratio,len(overlap),title,row))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[3].get("date","") or x[3].get("published",""))))
    return [{"title":t,"date":r.get("date","") or r.get("published",""),"source":r.get("source","") or "GitHub memory","url":r.get("url","")} for _,_,t,r in scored[:limit]]
def _parse_date(value):
    if not value: return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None

def _published_recent(value, hours=72):
    dt=_parse_date(value)
    if not dt: return False
    age=datetime.now(timezone.utc)-dt
    return timedelta(hours=-6) <= age <= timedelta(hours=hours)

def _relaxed_event_match(headline, primary_summary, article):
    primary=f"{headline} {primary_summary}"; other=f"{article.get('title','')} {article.get('summary','')}"
    na,nb=_named_tokens(primary),_named_tokens(other); common=_event_tokens(primary)&_event_tokens(other)
    events=common & {"attack","arrest","ban","block","breach","hack","kill","death","injure","crash","fire","flood","storm","cyclone","protest","rule","verdict","order","approve","announce","launch","sign","summon","file","probe","investigation","withdraw","reopen","election","vote","medal","gold","agreement","sanction","strike"}
    distinctive=common-{"government","president","minister","court","election","commission","india","world","news","today","latest","report","reports","official"}
    return bool(na & nb and events and len(distinctive)>=2 and len(common)>=4)

def discover_related_articles(stories, existing_articles=None, max_queries=12, per_query=8):
    """Search Google News RSS for fresh independent reports on high-priority events.

    Search results are discovery candidates only: verify_article still requires
    strict event matching, freshness, and distinct publisher identities before
    counting corroboration. Network failures are non-fatal and auditable.
    """
    pool = list(existing_articles or [])
    known_urls = {str(row.get("url", "")).strip() for row in pool if isinstance(row, dict)}
    results = []
    queried = 0
    failed = 0
    seen_headlines = set()
    candidates = sorted(
        [row for row in (stories or []) if isinstance(row, dict) and str(row.get("headline", "")).strip()],
        key=lambda row: float(row.get("importance", row.get("personalized_score", 0)) or 0),
        reverse=True,
    )
    for story in candidates:
        if queried >= max(0, int(max_queries)):
            break
        headline = re.sub(r"\s+", " ", str(story.get("headline", "") or "")).strip()
        key = headline.casefold()
        if not headline or key in seen_headlines:
            continue
        seen_headlines.add(key)
        region = str(story.get("region", "world") or "world").lower()
        gl, ceid = ("IN", "IN:en") if region == "india" else ("US", "US:en")
        url = f"https://news.google.com/rss/search?q={quote(headline)}&hl=en&gl={gl}&ceid={ceid}"
        queried += 1
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "NewsKnowledgeBot/1.0 (+https://github.com/vishwasgarg5/news-knowledge-bot; RSS research)"},
                timeout=(3, 6),
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception:
            failed += 1
            continue
        entries = getattr(parsed, "entries", []) or []
        for entry in entries[:max(0, int(per_query))]:
            publisher_info = entry.get("source", {}) or {}
            publisher = publisher_info.get("title", "") if isinstance(publisher_info, dict) else ""
            title = re.sub(r"\s+", " ", str(entry.get("title", "") or "")).strip()
            if publisher and title.lower().endswith(" - " + str(publisher).lower()):
                title = title[:-(len(str(publisher)) + 3)].strip()
            link = str(entry.get("link", "") or "").strip()
            if not publisher or not title or not link or link in known_urls:
                continue
            published = ""
            parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed_time:
                try:
                    published = datetime(*parsed_time[:6], tzinfo=timezone.utc).isoformat()
                except (TypeError, ValueError):
                    published = ""
            if not published:
                try:
                    dt = parsedate_to_datetime(str(entry.get("published", "") or entry.get("updated", "")))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published = dt.astimezone(timezone.utc).isoformat()
                except (TypeError, ValueError, OverflowError):
                    published = ""
            if not published:
                continue
            known_urls.add(link)
            results.append({
                "title": title,
                "headline": title,
                "summary": re.sub(r"<[^>]+>", " ", str(entry.get("summary", "") or ""))[:1600],
                "url": link,
                "source": str(publisher).strip(),
                "published": published,
                "category": "research",
            })
    metrics = {"queries": queried, "failed_queries": failed, "articles_found": len(results)}
    print(f"[RESEARCH_DISCOVERY] queries={queried} failed={failed} articles={len(results)}", flush=True)
    return results, metrics



_CATEGORY_QUERY_MAP = {
    "economy": (
        "India economy RBI inflation GDP growth jobs",
        "India economy fiscal policy interest rates inflation",
        "India manufacturing exports employment economic data",
        "India budget tax revenue public debt economic policy",
    ),
    "defence": (
        "India defence military procurement Ministry of Defence",
        "India defence border security military technology",
        "India armed forces defence contracts DRDO procurement",
        "India military exercise defence policy border update",
    ),
}

def discover_category_articles(categories, max_queries=4, per_query=8, existing_articles=None, pass_index=0):
    """Find fresh category-specific candidates when source feeds leave coverage gaps.

    Results are discovery candidates, not proof: they still pass deterministic
    scoring, event deduplication, freshness, verification and production gates.
    """
    allowed = ("economy", "defence")
    requested = list(dict.fromkeys(str(c).strip().lower() for c in (categories or [])))
    pass_index = max(0, min(1, int(pass_index)))
    # Each pass gets different query variants, so remaining gaps are not just
    # searched again with the same terms. The total budget remains caller-capped.
    queries = [(_category, query) for _category in allowed if _category in requested
               for query in _CATEGORY_QUERY_MAP[_category][pass_index * 2:(pass_index + 1) * 2]]
    queries = queries[:max(0, int(max_queries))]
    known_urls = {str(row.get("url", "")).strip() for row in (existing_articles or [])
                  if isinstance(row, dict) and str(row.get("url", "")).strip()}
    results, failed, queried = [], 0, 0
    seen_titles = set()
    for category, query in queries:
        gl, ceid = ("IN", "IN:en")
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl={gl}&ceid={ceid}"
        queried += 1
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "NewsKnowledgeBot/1.0 (+https://github.com/vishwasgarg5/news-knowledge-bot; category research)"},
                timeout=(3, 6),
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception:
            failed += 1
            continue
        for entry in (getattr(parsed, "entries", []) or [])[:max(0, int(per_query))]:
            source_info = entry.get("source", {}) or {}
            publisher = source_info.get("title", "") if isinstance(source_info, dict) else ""
            title = re.sub(r"\s+", " ", str(entry.get("title", "") or "")).strip()
            if publisher and title.lower().endswith(" - " + str(publisher).lower()):
                title = title[:-(len(str(publisher)) + 3)].strip()
            link = str(entry.get("link", "") or "").strip()
            title_key = title.casefold()
            if not publisher or not title or not link or link in known_urls or title_key in seen_titles:
                continue
            published = ""
            parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed_time:
                try:
                    published = datetime(*parsed_time[:6], tzinfo=timezone.utc).isoformat()
                except (TypeError, ValueError, OverflowError):
                    published = ""
            if not published:
                raw_date = str(entry.get("published", "") or entry.get("updated", "") or "")
                published = _parse_date(raw_date)
                if not published and raw_date:
                    try:
                        published = parsedate_to_datetime(raw_date)
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=timezone.utc)
                        published = published.astimezone(timezone.utc)
                    except (TypeError, ValueError, OverflowError):
                        published = None
                published = published.isoformat() if published else ""
            if not _published_recent(published, 72):
                continue
            summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary", "") or ""))
            known_urls.add(link)
            seen_titles.add(title_key)
            results.append({
                "title": title, "headline": title, "summary": summary[:1600],
                "url": link, "source": str(publisher).strip(), "published": published,
                "category": category, "region": "india", "region_confidence": 0.75,
                "region_evidence": f"targeted category search: {category}",
            })
    metrics = {
        "categories": [category for category in allowed if category in requested],
        "queries": queried, "failed_queries": failed, "articles_found": len(results),
    }
    print(f"[CATEGORY_RESEARCH] categories={','.join(metrics['categories']) or 'none'} queries={queried} failed={failed} articles={len(results)}", flush=True)
    return results, metrics

def verify_article(story, articles, memory=None):
    """Build an auditable, freshness-aware verification record for one event.
    Only current, independent publishers can raise the verification tier."""
    headline=story.get("headline","")
    primary_summary=str(story.get("summary","") or "")
    primary_source=str(story.get("source","") or "")
    primary_key=_source_key(primary_source, story.get("url",""))
    primary_fresh=_published_recent(story.get("published",""),72)
    primary_trust=_source_trust(primary_key)
    primary_official=_is_official(primary_key)
    matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        if _is_derivative_report(a): continue
        if not _published_recent(a.get("published",""),72): continue
        # Corroboration must match the actual headline, not just a broad or
        # contaminated primary summary. Summaries from unrelated stories can
        # share names/topics and falsely inflate independent-source counts.
        title_sim=_event_similarity(headline,a.get("title",""))
        strong_match=_strong_event_match(headline,"",a)
        relaxed_match=_relaxed_event_match(headline,"",a)
        sim=title_sim
        if title_sim>=0.55 or strong_match or relaxed_match:
            source=_source_key(a.get("source",""), a.get("url","")); trust=_source_trust(source)
            match_score=max(sim,0.58 if strong_match else sim)
            matches.append((match_score*0.7+trust*0.3,a,title_sim,0.0))
    matches.sort(key=lambda x:-x[0])
    corroborating=[]; source_names=[]; seen_sources=set()
    for score,a,title_sim,context_sim in matches:
        headline_tokens=_tokens(headline); primary_tokens=_tokens(primary_summary)
        article_tokens=_tokens(a.get("title","")); article_summary_tokens=_tokens(a.get("summary",""))
        distinctive_title=len((headline_tokens & article_tokens) - {"supreme","court","government","president","commission","election","india","world"})
        distinctive_context=len(((headline_tokens|primary_tokens) & (article_tokens|article_summary_tokens)) - {"supreme","court","government","president","commission","election","india","world","news","report","today","latest"})
        # Only count a report when the story headline itself is matched.
        # Do not let primary-summary overlap rescue an unrelated headline.
        strong_match=_strong_event_match(headline,"",a)
        relaxed_match=_relaxed_event_match(headline,"",a)
        if not strong_match and not relaxed_match and title_sim < 0.55: continue
        if not (strong_match or relaxed_match) and title_sim < 0.55: continue
        key=_source_key(a.get("source",""), a.get("url",""))
        if not key or key==primary_key or key in seen_sources: continue
        seen_sources.add(key); source_names.append(a.get("source","")); corroborating.append(a)
        if len(corroborating)>=8: break
    independent=len(source_names)
    official=primary_official
    primary_derivative=_is_derivative_report({"title":headline,"source":primary_source})

    # Detect explicit disagreement language without trying to decide which
    # publisher is correct. The flag is surfaced to ranking/audit so the bot
    # can prefer attributed, corroborated stories over unresolved conflicts.
    conflict_markers=("denied","denies","disputed","disputes","rejects","rejected","contradicts","contradicted","not true","false claim","refuted")
    evidence_text=" ".join(str(a.get("title",""))+" "+str(a.get("summary","")) for a in corroborating).lower()
    primary_text=(headline+" "+primary_summary).lower()
    contradiction_matches=[a for a in corroborating if any(m in (str(a.get("title",""))+" "+str(a.get("summary",""))).lower() for m in conflict_markers)]
    contradiction_flag=bool(contradiction_matches and not any(m in primary_text for m in conflict_markers))
    contradiction_evidence=[{"source":a.get("source",""),"title":a.get("title",""),"markers":[m for m in conflict_markers if m in (str(a.get("title",""))+" "+str(a.get("summary",""))).lower()]} for a in contradiction_matches[:4]]
    if official:
        verification="official-source"
        confidence=96 if independent else 92
    elif independent>=2:
        verification="multi-source"
        confidence=min(99,78+5*min(independent-1,4))
    elif independent==1:
        verification="multi-report"
        confidence=70
    elif primary_source:
        verification="single-source"
        confidence=55
    else:
        verification="unverified"
        confidence=35
    evidence_rows=[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url",""),"published":a.get("published",""),"summary":a.get("summary","")} for a in corroborating[:8]]
    evidence_strength=100 if official else (85 if independent>=2 else (65 if independent==1 else 35))
    verification_reason=("official primary source" if official else ("two or more independent current publishers" if independent>=2 else ("one independent current publisher" if independent==1 else "no independent current corroboration")))
    return {
        "evidence":evidence_rows,
        "historical":_memory_fallback(headline,memory or [],5),
        "verification":verification,
        "confidence":confidence,
        "evidence_strength":evidence_strength,
        "verification_reason":verification_reason,
        "source_count":independent+(1 if primary_source else 0),
        "independent_sources":independent,
        "fresh_sources":source_names[:5],
        "current_sources":independent+(1 if primary_source else 0),
        "official_source":official,
        "primary_derivative":primary_derivative,
        "primary_fresh":primary_fresh,
        "primary_trust":round(primary_trust,2),
        "contradiction_flag":contradiction_flag,
        "contradiction_evidence":contradiction_evidence,
        "freshness_hours":round(max(0.0,(datetime.now(timezone.utc)-(_parse_date(story.get("published","")) or datetime.now(timezone.utc))).total_seconds()/3600),1) if _parse_date(story.get("published","")) else None,
    }

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; strong=current=historical=historical_only=0; pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory); output[sid]=r
        # Current evidence means a fresh independent report, or a fresh primary
        # source when no independent report exists. A stale single-source story
        # must not inflate research coverage merely because it has a publisher.
        has_fresh_independent=int(r.get("independent_sources",0) or 0)>0
        is_current=has_fresh_independent or (
            r.get("primary_fresh",False)
            and r.get("verification") in {"official-source","single-source"}
        )
        if r["verification"] in {"multi-source","official-source"}: strong+=1
        if is_current: current+=1
        if r["historical"]: historical+=1
        if r["historical"] and not is_current: historical_only+=1
    total=len(stories)
    tier_counts={
        tier:sum(1 for x in output.values() if isinstance(x,dict) and x.get("verification")==tier)
        for tier in ("multi-source","multi-report","official-source","single-source","unverified")
    }
    contradiction_count=sum(1 for x in output.values() if isinstance(x,dict) and x.get("contradiction_flag"))
    independent_total=sum(max(0,int(x.get("independent_sources",0) or 0)) for x in output.values() if isinstance(x,dict))
    independent_stories=sum(1 for x in output.values() if isinstance(x,dict) and int(x.get("independent_sources",0) or 0)>0)
    stale_primary=sum(1 for x in output.values() if isinstance(x,dict) and not x.get("primary_fresh",False))
    output["_stats"]={
        "strong":strong,
        "current":current,
        "historical":historical,
        "historical_only":historical_only,
        "failed":tier_counts["unverified"],
        "total":total,
        "coverage":round(current/total,3) if total else 0,
        "strong_coverage":round(strong/total,3) if total else 0,
        "single_source":tier_counts["single-source"],
        "multi_report":tier_counts["multi-report"],
        "official":tier_counts["official-source"],
        "unverified":tier_counts["unverified"],
        "independent_source_stories":independent_stories,
        "independent_sources_total":independent_total,
        "independent_source_coverage":round(independent_stories/total,3) if total else 0,
        "mean_independent_sources":round(independent_total/total,2) if total else 0,
        "single_source_rate":round(tier_counts["single-source"]/total,3) if total else 0,
        "contradictions":contradiction_count,
        "contradiction_rate":round(contradiction_count/total,3) if total else 0,
        "stale_primary":stale_primary,
        "status":"PASS" if total and current>=max(1,int(total*.50)) else ("WARN" if current else "FAIL"),
    }
    print(
        f"[INFO] verification current={current}/{total}; strong={strong}/{total}; "
        f"independent_source_coverage={independent_stories/max(1,total):.0%}; "
        f"single_source={tier_counts['single-source']}; contradictions={contradiction_count}; "
        f"historical_matches={historical}; historical_only={historical_only}",
        flush=True,
    )
    return output
