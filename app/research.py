from __future__ import annotations
import re
from collections import defaultdict

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}

TRUST={"reuters":1.0,"associated press":1.0,"ap news":1.0,"bbc":0.95,"the hindu":0.92,"indian express":0.90,"times of india":0.82,"pib":0.92}

def _tokens(text):
    return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}

def _similar(a,b):
    x,y=_tokens(a),_tokens(b)
    return len(x&y)/max(1,len(x|y))

def _memory_fallback(query:str,memory:list[dict],limit:int=5)->list[dict]:
    q=_tokens(query); scored=[]
    for row in memory or []:
        title=str(row.get("headline","") or row.get("title","")); words=_tokens(title); overlap=len(q&words)
        if overlap>=2: scored.append((overlap/max(1,len(q|words)),overlap,title,row))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[3].get("date","") or x[3].get("published",""))))
    return [{"title":t,"date":r.get("date","") or r.get("published",""),"source":r.get("source","") or "GitHub memory","url":r.get("url","")} for _,_,t,r in scored[:limit]]

def verify_article(story, articles, memory=None):
    headline=story.get("headline","")
    matches=[]
    for a in articles:
        if str(a.get("url",""))==str(story.get("url","")): continue
        sim=_similar(headline,a.get("title","") )
        if sim>=0.18:
            source=str(a.get("source","")).lower(); trust=max((v for k,v in TRUST.items() if k in source),default=0.65)
            matches.append((sim*0.7+trust*0.3,a))
    matches.sort(key=lambda x:-x[0])
    corroborating=[a for score,a in matches[:6] if _similar(headline,a.get("title","") )>=0.28]
    sources={str(a.get("source","")).lower() for a in corroborating}
    confidence=min(99,int(55+15*min(len(sources),3)+10*min(len(corroborating),3)))
    verification="multi-source" if len(sources)>=2 else ("single-source" if corroborating else "unverified")
    return {
        "evidence":[{"title":a.get("title",""),"source":a.get("source",""),"url":a.get("url","")} for a in corroborating[:5]],
        "historical":_memory_fallback(headline,memory or [],5),
        "verification":verification,
        "confidence":confidence,
        "source_count":len(sources),
    }

def research_stories(stories:list[dict],memory:list[dict]|None=None,articles:list[dict]|None=None)->dict:
    output={}; ok=memory_ok=failed=0
    pool=articles or []
    for s in stories:
        sid=s.get("story_id","")
        if not sid: continue
        r=verify_article(s,pool,memory)
        output[sid]=r
        if r["verification"]!="unverified": ok+=1
        if r["historical"]: memory_ok+=1
        if r["verification"]=="unverified": failed+=1
    total=len(stories); status="PASS" if total and ok>=max(1,int(total*.75)) else ("WARN" if ok else "FAIL")
    output["_stats"]={"ok":ok,"memory_ok":memory_ok,"failed":failed,"total":total,"status":status}
    print(f"[INFO] verification status={status}: {ok}/{total} stories corroborated; {memory_ok} have historical matches",flush=True)
    return output
