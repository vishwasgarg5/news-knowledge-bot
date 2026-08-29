from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
import requests

API="https://api.gdeltproject.org/api/v2/doc/doc"
STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest"}

def _tokens(text):
    return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}

def _memory_fallback(query:str,memory:list[dict],limit:int=3)->list[dict]:
    q=_tokens(query); scored=[]
    for row in memory or []:
        title=str(row.get("headline","") or row.get("title","")); words=_tokens(title)
        overlap=len(q & words)
        if overlap>=2:
            ratio=overlap/max(1,len(q|words)); scored.append((ratio,overlap,title,row))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[3].get("date","") or x[3].get("published",""))))
    return [{"title":t,"date":r.get("date","") or r.get("published",""),"source":r.get("source","") or "GitHub memory","url":r.get("url","")} for _,_,t,r in scored[:limit]]

def historical_headlines(query:str,days:int=180,limit:int=5)->list[dict]:
    end=datetime.now(timezone.utc); start=end-timedelta(days=days)
    params={"query":query[:100],"mode":"artlist","maxrecords":min(limit,5),"format":"json","startdatetime":start.strftime("%Y%m%d%H%M%S"),"enddatetime":end.strftime("%Y%m%d%H%M%S")}
    try:
        r=requests.get(API,params=params,timeout=5); r.raise_for_status(); data=r.json()
        arts=data.get("articles",[]) if isinstance(data,dict) else []
        return [{"title":a.get("title",""),"date":a.get("seendate",""),"source":a.get("domain",""),"url":a.get("url","")} for a in arts[:limit] if a.get("title")]
    except Exception as exc:
        print(f"[WARN] GDELT historical research unavailable: {type(exc).__name__}",flush=True); return []

def research_stories(stories:list[dict],memory:list[dict]|None=None)->dict:
    output={}; ok=memory_ok=gdelt_ok=failed=0; pending=[]
    # GitHub memory is the primary free historical store. This avoids waiting on GDELT
    # when we already have relevant past headlines.
    for s in stories:
        sid=s.get("story_id",""); query=s.get("headline","")
        if not sid or not query: continue
        result=_memory_fallback(query,memory or [],3)
        if result:
            output[sid]=result; ok+=1; memory_ok+=1
        else:
            pending.append(s)
    # Only unmatched stories use the external fallback. GDELT can be slow/unreachable
    # from hosted runners, so it is never allowed to dominate the morning run.
    for s in pending:
        sid=s.get("story_id",""); result=historical_headlines(s.get("headline","")); output[sid]=result
        if result: ok+=1; gdelt_ok+=1
        else: failed+=1
    total=len(stories); status="PASS" if total and ok==total else ("WARN" if ok else "FAIL")
    output["_stats"]={"ok":ok,"memory_ok":memory_ok,"gdelt_ok":gdelt_ok,"failed":failed,"total":total,"status":status}
    print(f"[INFO] historical research status={status}: {ok}/{total} stories have evidence; GitHub={memory_ok}; GDELT={gdelt_ok}; {failed} unavailable",flush=True)
    return output
