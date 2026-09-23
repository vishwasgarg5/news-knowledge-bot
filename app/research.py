from __future__ import annotations
import re

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}
TRUST={"reuters":1.0,"associated press":1.0,"ap news":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92,"reserve bank of india":1.0,"supreme court of india":1.0,"isro":0.98,"sebi":0.98}
OFFICIAL={"pib","reserve bank of india","rbi","supreme court of india","prime minister's office","pm india","ministry of defence","isro","sebi"}

def _tokens(text): return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}
def _similar(a,b):
    x,y=_tokens(a),_tokens(b); return len(x&y)/max(1,len(x|y))
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

def verify_article(story, articles, memory=None):
    headline=story.get("headline",""); primary_source=str(story.get("source","") or ""); primary_key=_source_key(primary_source); matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        sim=_similar(headline,a.get("title",""))
        if sim>=0.16:
            source=_source_key(a.get("source","")); trust=max((v for k,v in TRUST.items() if k in source),default=0.65)
            matches.append((sim*0.7+trust*0.3,a))
    matches.sort(key=lambda x:-x[0])
    # Only count fresh corroboration from distinct publishers. Similar stories
    # from the same publisher are not independent evidence.
    corroborating=[]; source_names=[]; seen_sources=set()
    for score,a in matches:
        sim=_similar(headline,a.get("title",""))
        if sim < 0.24:
            continue
        key=_source_key(a.get("source",""))
        if not key or key==primary_key or key in seen_sources:
            continue
        seen_sources.add(key)
        source_names.append(a.get("source",""))
        corroborating.append(a)
        if len(corroborating)>=8:
            break
    independent=len(source_names)
    official=_is_official(primary_source)
    if official:
        verification="official-source"; confidence=96 if independent else 92
    elif independent>=2:
        verification="multi-source"; confidence=min(99,82+5*min(independent-2,3))
    elif independent==1:
        verification="single-source"; confidence=68
    else:
        verification="unverified"; confidence=35
    return {"evidence":[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url","")} for a in corroborating[:5]],"historical":_memory_fallback(headline,memory or [],5),"verification":verification,"confidence":confidence,"source_count":independent+(1 if primary_source else 0),"independent_sources":independent,"fresh_sources":source_names[:5],"official_source":official}

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; strong=memory_ok=failed=0; pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory); output[sid]=r
        if r["verification"] in {"multi-source","official-source"}: strong+=1
        if r["historical"]: memory_ok+=1
        if r["verification"]=="unverified": failed+=1
    total=len(stories); status="PASS" if total and strong>=max(1,int(total*.50)) else ("WARN" if strong else "FAIL")
    output["_stats"]={"ok":strong,"memory_ok":memory_ok,"failed":failed,"total":total,"coverage":(strong/total if total else 0),"status":status}
    print(f"[INFO] verification status={status}: {strong}/{total} strongly verified; {memory_ok} historical matches; coverage={strong/max(1,total):.0%}",flush=True)
    return output
