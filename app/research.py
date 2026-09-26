from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}
TRUST={"reuters":1.0,"associated press":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92,"reserve bank of india":1.0,"supreme court of india":1.0,"isro":0.98,"nasa":0.98,"sebi":0.98,"ndtv":0.86,"indian express":0.90}
OFFICIAL={"pib","reserve bank of india","rbi","supreme court of india","prime minister's office","pm india","ministry of defence","isro","nasa","sebi"}

def _tokens(text): return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}
def _similar(a,b):
    x,y=_tokens(a),_tokens(b)
    if not x or not y: return 0.0
    return len(x&y)/max(1,len(x|y))

def _named_tokens(text):
    words=re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(text))
    generic={"supreme","court","high","delhi","assembly","government","president","prime","minister","chief","election","commission","police","video","india","indian","american","united","states","white","house","china"}
    return {w.lower().strip(".,") for w in words if w.lower() not in STOP and w.lower() not in generic}

def _event_similarity(a,b):
    """Conservative event match for corroboration; avoid same-topic false matches."""
    base=_similar(a,b)
    na,nb=_named_tokens(a),_named_tokens(b)
    named_overlap=len(na&nb)
    ta,tb=_tokens(a),_tokens(b)
    common=ta&tb
    event_terms={"breach","hack","attack","arrest","ban","blocked","access","symbol","logo","launch","launched","deal","trade","truce","visit","arrives","arrived","glasses","intelligence","result","results","election","court","judge","verdict","trial","crash","earthquake","cyclone","fire","flood","death","dies","killed","injured","strike","protest","approval","approved","agreement","summit","sanctions","dispute","ruling","order"}
    event_overlap=len(common & event_terms)
    if base>=0.62 and len(common)>=5: return base
    if named_overlap>=1 and event_overlap>=1 and len(common)>=4: return max(base,0.55)
    if named_overlap>=2 and len(common)>=4: return max(base,0.55)
    return 0.0
ALIASES={"bbc news":"bbc","bbc":"bbc","reuters":"reuters","the hindu":"the hindu","indian express":"indian express","associated press":"associated press","ap news":"associated press","pib":"pib","press information bureau":"pib","reserve bank of india":"reserve bank of india","rbi":"reserve bank of india"}
def _source_key(source, url=""):
    try:
        host=urlparse(str(url or "")).netloc.lower().split(":")[0]
        if host.startswith("www."): host=host[4:]
        if host:
            if host.endswith("bbc.co.uk") or host.endswith("bbc.com"): return "bbc"
            if host.endswith("reuters.com"): return "reuters"
            if host.endswith("thehindu.com"): return "the hindu"
            if host.endswith("indianexpress.com"): return "indian express"
            if host.endswith("apnews.com"): return "associated press"
            if host.endswith("pib.gov.in"): return "pib"
            if host.endswith("rbi.org.in"): return "reserve bank of india"
            if host.endswith("isro.gov.in"): return "isro"
            if host.endswith("nasa.gov"): return "nasa"
            if host.endswith("sebi.gov.in"): return "sebi"
            return host
    except Exception:
        pass
    raw=str(source or "").lower().strip()
    for alias,key in ALIASES.items():
        if alias in raw:return key
    return raw

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
def _is_official(source): return any(x in _source_key(source) for x in OFFICIAL)

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

def verify_article(story, articles, memory=None):
    headline=story.get("headline",""); primary_source=str(story.get("source","") or ""); primary_key=_source_key(primary_source, story.get("url",""))
    matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        if _is_derivative_report(a): continue
        if not _published_recent(a.get("published",""),72): continue
        sim=_event_similarity(headline,a.get("title",""))
        if sim>=0.55:
            source=_source_key(a.get("source",""), a.get("url","")); trust=max((v for k,v in TRUST.items() if k in source),default=0.65)
            matches.append((sim*0.7+trust*0.3,a))
    matches.sort(key=lambda x:-x[0])
    corroborating=[]; source_names=[]; seen_sources=set()
    for score,a in matches:
        sim=_event_similarity(headline,a.get("title",""))
        if sim < 0.55: continue
        headline_tokens=_tokens(headline)
        article_tokens=_tokens(a.get("title",""))
        distinctive=len((headline_tokens & article_tokens) - {"supreme","court","government","president","commission","election","india","world"})
        if distinctive < 2: continue
        key=_source_key(a.get("source",""))
        if not key or key==primary_key or key in seen_sources: continue
        seen_sources.add(key); source_names.append(a.get("source","")); corroborating.append(a)
        if len(corroborating)>=8: break
    independent=len(source_names)
    official=_is_official(primary_source)
    primary_derivative=_is_derivative_report({"title":headline,"source":primary_source})
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
    return {
        "evidence":[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url",""),"published":a.get("published",""),"summary":a.get("summary","")} for a in corroborating[:8]],
        "historical":_memory_fallback(headline,memory or [],5),
        "verification":verification,
        "confidence":confidence,
        "source_count":independent+(1 if primary_source else 0),
        "independent_sources":independent,
        "fresh_sources":source_names[:5],
        "current_sources":independent+(1 if primary_source else 0),
        "official_source":official,
        "primary_derivative":primary_derivative,
    }

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; strong=current=historical=historical_only=0; pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory); output[sid]=r
        is_current=r["verification"] in {"multi-source","official-source","single-source"}
        if r["verification"] in {"multi-source","official-source"}: strong+=1
        if is_current: current+=1
        if r["historical"]: historical+=1
        if r["historical"] and not is_current: historical_only+=1
    total=len(stories)
    output["_stats"]={
        "strong":strong,
        "current":current,
        "historical":historical,
        "historical_only":historical_only,
        "failed":sum(1 for x in output.values() if isinstance(x,dict) and x.get("verification")=="unverified"),
        "total":total,
        "coverage":current/total if total else 0,
        "strong_coverage":strong/total if total else 0,
        "status":"PASS" if total and current>=max(1,int(total*.50)) else ("WARN" if current else "FAIL"),
    }
    print(f"[INFO] verification current={current}/{total}; strong={strong}/{total}; historical_matches={historical}; historical_only={historical_only}; coverage={current/max(1,total):.0%}",flush=True)
    return output
