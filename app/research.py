from __future__ import annotations
import re

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}
TRUST={"reuters":1.0,"associated press":1.0,"ap news":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92}
OFFICIAL={"pib","reserve bank of india","rbi","supreme court of india","prime minister's office","pm india","ministry of defence","isro","sebi"}

def _tokens(text): return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}
def _similar(a,b):
    x,y=_tokens(a),_tokens(b); return len(x&y)/max(1,len(x|y))
def _source_key(source): return str(source or "").lower().strip()
def _is_official(source): return any(x in _source_key(source) for x in OFFICIAL)
def _memory_fallback(query:str,memory:list[dict],limit:int=5)->list[dict]:
    q=_tokens(query); scored=[]
    for row in memory or []:
        title=str(row.get("headline","") or row.get("title","")); words=_tokens(title); overlap=len(q&words)
        if overlap>=2: scored.append((overlap/max(1,len(q|words)),overlap,title,row))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[3].get("date","") or x[3].get("published",""))))
    return [{"title":t,"date":r.get("date","") or r.get("published",""),"source":r.get("source","") or "GitHub memory","url":r.get("url","")} for _,_,t,r in scored[:limit]]

def verify_article(story, articles, memory=None):
    headline=story.get("headline",""); matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        sim=_similar(headline,a.get("title",""))
        if sim>=0.18:
            source=_source_key(a.get("source","")); trust=max((v for k,v in TRUST.items() if k in source),default=0.65)
            matches.append((sim*0.7+trust*0.3,a))
    matches.sort(key=lambda x:-x[0])
    corroborating=[a for score,a in matches[:8] if _similar(headline,a.get("title",""))>=0.28]
    source_names=[]; seen_sources=set()
    for a in corroborating:
        key=_source_key(a.get("source",""))
        if key and key not in seen_sources: seen_sources.add(key); source_names.append(a.get("source",""))
    primary_source=str(story.get("source","") or ""); independent=len(source_names)
    if _is_official(primary_source): verification="official-source"; confidence=96 if independent else 92
    elif independent>=2: verification="multi-source"; confidence=min(99,82+5*min(independent-2,3))
    elif independent==1: verification="single-source"; confidence=68
    else: verification="unverified"; confidence=35
    return {"evidence":[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url","")} for a in corroborating[:5]],"historical":_memory_fallback(headline,memory or [],5),"verification":verification,"confidence":confidence,"source_count":independent+(1 if primary_source else 0),"independent_sources":independent}

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; strong=memory_ok=failed=0; pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory); output[sid]=r
        if r["verification"] in {"multi-source","official-source"}: strong+=1
        if r["historical"]: memory_ok+=1
        if r["verification"]=="unverified": failed+=1
    total=len(stories); status="PASS" if total and strong>=max(1,int(total*.75)) else ("WARN" if strong else "FAIL")
    output["_stats"]={"ok":strong,"memory_ok":memory_ok,"failed":failed,"total":total,"status":status}
    print(f"[INFO] verification status={status}: {strong}/{total} strongly verified; {memory_ok} historical matches",flush=True)
    return output
