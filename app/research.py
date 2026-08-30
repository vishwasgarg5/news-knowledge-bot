from __future__ import annotations
import re

STOP={"gets","says","this","that","with","from","into","after","about","will","have","been","their","they","what","when","where","which","today","latest","india","news"}

def _tokens(text):
    return {x for x in re.findall(r"[a-zA-Z]{4,}",str(text).lower()) if x not in STOP}

def _memory_fallback(query:str,memory:list[dict],limit:int=5)->list[dict]:
    q=_tokens(query); scored=[]
    for row in memory or []:
        title=str(row.get("headline","") or row.get("title","")); words=_tokens(title)
        overlap=len(q & words)
        if overlap>=2:
            ratio=overlap/max(1,len(q|words)); scored.append((ratio,overlap,title,row))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[3].get("date","") or x[3].get("published",""))))
    return [{"title":t,"date":r.get("date","") or r.get("published",""),"source":r.get("source","") or "GitHub memory","url":r.get("url","")} for _,_,t,r in scored[:limit]]

def research_stories(stories:list[dict],memory:list[dict]|None=None)->dict:
    """GitHub-only historical research. No external API/network dependency."""
    output={}; ok=memory_ok=failed=0
    for s in stories:
        sid=s.get("story_id",""); query=s.get("headline","")
        if not sid or not query: continue
        result=_memory_fallback(query,memory or [],5)
        if result:
            output[sid]=result; ok+=1; memory_ok+=1
        else:
            output[sid]=[]; failed+=1
    total=len(stories); status="PASS" if total and ok==total else ("WARN" if ok else "FAIL")
    output["_stats"]={"ok":ok,"memory_ok":memory_ok,"gdelt_ok":0,"failed":failed,"total":total,"status":status}
    print(f"[INFO] historical research status={status}: {ok}/{total} stories have GitHub historical evidence; {failed} are new/unmatched topics",flush=True)
    return output
