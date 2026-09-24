from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}
TRUST={"reuters":1.0,"associated press":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92,"reserve bank of india":1.0,"supreme court of india":1.0,"isro":0.98,"sebi":0.98}
OFFICIAL={"pib","reserve bank of india","rbi","supreme court of india","prime minister's office","pm india","ministry of defence","isro","sebi"}

def _tokens(text): return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}
def _similar(a,b):
    x,y=_tokens(a),_tokens(b)
    if not x or not y: return 0.0
    return len(x&y)/max(1,len(x|y))

def _named_tokens(text):
    words=re.findall(r"\\b[A-Z][A-Za-z.'-]{2,}\\b",str(text))
    return {w.lower().strip(".,") for w in words if w.lower() not in STOP}

def _event_similarity(a,b):
    """More tolerant corroboration: handles headline paraphrases while requiring meaningful overlap."""
    base=_similar(a,b)
    na,nb=_named_tokens(a),_named_tokens(b)
    named_overlap=len(na&nb)
    ta,tb=_tokens(a),_tokens(b)
    common=len(ta&tb)
    if named_overlap>=1 and common>=2:
        return max(base,0.22)
    if common>=3:
        return max(base,0.18)
    return base
ALIASES={"bbc news":"bbc","bbc":"bbc","reuters":"reuters","the hindu":"the hindu","indian express":"indian express","associated press":"associated press","ap news":"associated press","pib":"pib","press information bureau":"pib","reserve bank of india":"reserve bank of india","rbi":"reserve bank of india"}
def _source_key(source):
    raw=str(source or "").lower().strip()
    for alias,key in ALIASES.items():
        if alias in raw:return key
    return raw
def _is_official(source): return any(x in _source_key(source) for x in OFFICIAL)

def _memory_fallback(query:str,memory:list[dict],limit:int=5)->list[dict]:
    q=_tokens(query); scored=[]
    for row in memory or []:
        title=str(row.get("headline","") or row.get("title","")); words=_tokens(title); overlap=len(q&words)
        if overlap>=2: scored.append((overlap/max(1,len(q|words)),overlap,title,row))
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
    headline=story.get("headline",""); primary_source=str(story.get("source","") or ""); primary_key=_source_key(primary_source)
    matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        if not _published_recent(a.get("published",""),72): continue
        sim=_event_similarity(headline,a.get("title",""))
        if sim>=0.12:
            source=_source_key(a.get("source","")); trust=max((v for k,v in TRUST.items() if k in source),default=0.65)
            matches.append((sim*0.7+trust*0.3,a))
    matches.sort(key=lambda x:-x[0])
    corroborating=[]; source_names=[]; seen_sources=set()
    for score,a in matches:
        sim=_event_similarity(headline,a.get("title",""))
        if sim < 0.16: continue
        key=_source_key(a.get("source",""))
        if not key or key==primary_key or key in seen_sources: continue
        seen_sources.add(key); source_names.append(a.get("source","")); corroborating.append(a)
        if len(corroborating)>=8: break
    independent=len(source_names)
    official=_is_official(primary_source)
    if official:
        verification="official-source"
        confidence=96 if independent else 92
    elif independent>=1:
        verification="multi-source"
        confidence=min(99,78+5*min(independent-1,4))
    else:
        verification="unverified"
        confidence=35
    return {
        "evidence":[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url","")} for a in corroborating[:5]],
        "historical":_memory_fallback(headline,memory or [],5),
        "verification":verification,
        "confidence":confidence,
        "source_count":independent+(1 if primary_source else 0),
        "independent_sources":independent,
        "fresh_sources":source_names[:5],
        "current_sources":independent+(1 if primary_source else 0),
        "official_source":official,
    }

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; strong=current=historical=0; pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory); output[sid]=r
        if r["verification"] in {"multi-source","official-source"}: strong+=1
        if r["verification"] in {"multi-source","official-source","single-source"}: current+=1
        if r["historical"]: historical+=1
    total=len(stories)
    output["_stats"]={
        "strong":strong,
        "current":current,
        "historical":historical,
        "failed":sum(1 for x in output.values() if isinstance(x,dict) and x.get("verification")=="unverified"),
        "total":total,
        "coverage":current/total if total else 0,
        "strong_coverage":strong/total if total else 0,
        "status":"PASS" if total and current>=max(1,int(total*.50)) else ("WARN" if current else "FAIL"),
    }
    print(f"[INFO] verification current={current}/{total}; strong={strong}/{total}; historical-only={historical}; coverage={current/max(1,total):.0%}",flush=True)
    return output
