from __future__ import annotations
import hashlib,json,os,re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

SYSTEM="""You are a rigorous news editor, knowledge teacher and memory coach. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If evidence is missing, say 'Not stated in supplied sources'. Explain news as a compact flow: EVENT -> CAUSE -> IMPACT -> CHANGE -> NEXT -> CONNECTION -> MEMORY. Prefer durable understanding over headline repetition."""
DEFAULT_MODEL="qwen2.5:7b"; DEFAULT_OLLAMA_URL="http://localhost:11434/api/generate"

def _model_name(): return os.getenv("AI_MODEL","").strip() or os.getenv("OLLAMA_MODEL","").strip() or DEFAULT_MODEL
def _ollama_url(): return os.getenv("OLLAMA_URL",DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL

def _call_ollama(prompt,system=SYSTEM,num_predict=None,timeout=None):
    payload={"model":_model_name(),"system":system,"prompt":prompt,"stream":False,"keep_alive":"10m","options":{"temperature":0.1,"num_ctx":int(os.getenv("AI_CONTEXT","4096")),"num_predict":num_predict or int(os.getenv("AI_MAX_OUTPUT","900"))}}
    req=Request(_ollama_url(),data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=timeout or int(os.getenv("AI_TIMEOUT_SECONDS","120"))) as r:data=json.loads(r.read().decode())
    except HTTPError as e: raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except URLError as e: raise RuntimeError(f"Cannot reach Ollama: {e.reason}") from e
    text=data.get("response","").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    return text

def _words(text): return set(re.findall(r"[a-zA-Z]{4,}",str(text).lower()))
def _similar(a,b):
    wa,wb=_words(a),_words(b); return len(wa&wb)/max(1,len(wa|wb))

def _deterministic_score(a):
    title,summary=str(a.get("title","")),str(a.get("summary","")); source,category=str(a.get("source","")).lower(),str(a.get("category","")).lower(); text=f"{title} {summary}".lower(); score=35.0
    if any(x in source for x in ("reuters","bbc","associated press","ap news","the hindu","indian express","times of india","pib")): score+=12
    if category in {"india","national","politics","world","economy","business","defence","science","technology"}: score+=8
    for term,boost in {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}.items():
        if term in text: score+=boost
    score+=min(10,2*sum(x in text for x in ("million","billion","lakh","crore","dead","killed","injured","arrested","approved","launched","signed"))); score+=min(8,len(_words(title))*.7); return min(100.0,score)

def select_stories(articles,top_n=12,excluded_headlines=None):
    excluded=list(excluded_headlines or []); ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
        if any(_similar(title,old)>=.62 for old in excluded): continue
        words=_words(title)
        if any(len(words&old)/max(1,len(words|old))>=.72 for old in seen): continue
        seen.append(words); ranked.append((round(_deterministic_score(a),1),a))
    ranked.sort(key=lambda x:(-x[0],str(x[1].get("published",""))))
    # Strict daily balance: 6 India + 6 World. Fill from the other side only if genuinely unavailable.
    selected=[]; counts={"india":0,"world":0}
    for desired in ("india","world"):
        for score,a in ranked:
            region=str(a.get("region","world")).lower()
            if region!=desired or any(x.get("url")==a.get("url") for x in selected): continue
            if counts[desired]>=top_n//2: break
            selected.append({"story_id":hashlib.sha1(str(a.get("title","")).lower().encode()).hexdigest()[:16],"rank":len(selected)+1,"headline":str(a.get("title",""))[:240],"importance":score,"category":str(a.get("category","Other")),"region":region,"url":str(a.get("url","")),"reason":"Impact/source/relevance score with India-World balance."})
            counts[desired]+=1
    if len(selected)<top_n:
        for score,a in ranked:
            if any(x.get("url")==a.get("url") for x in selected): continue
            region=str(a.get("region","world")).lower(); selected.append({"story_id":hashlib.sha1(str(a.get("title","")).lower().encode()).hexdigest()[:16],"rank":len(selected)+1,"headline":str(a.get("title",""))[:240],"importance":score,"category":str(a.get("category","Other")),"region":region,"url":str(a.get("url","")),"reason":"Fallback because fewer than 6 stories were available for one region."})
            if len(selected)>=top_n: break
    return selected[:top_n]

def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id")
        related=[]
        for x in articles:
            if x.get("url")==s.get("url"): continue
            sim=_similar(s.get("headline",""),x.get("title",""))
            if sim>=.20: related.append((sim,x))
        related.sort(key=lambda z:-z[0])
        r=(research or {}).get(sid,{})
        out.append({"story_id":sid,"headline":s.get("headline",""),"importance":s.get("importance",0),"category":s.get("category",""),"region":s.get("region","world"),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:900],"related_articles":[{"title":x.get("title",""),"source":x.get("source",""),"url":x.get("url","")} for _,x in related[:5]],"verification":r})
    return out

def _parse(text,item):
    values={}
    for line in text.splitlines():
        if ":" in line:
            k,v=line.split(":",1); k=k.strip().lower().replace(" ","_"); v=v.strip()
            if k in {"what","who","when","where","why","why_important","background","change","next","connection","memory","learn","latest","entities","vocabulary"} and v: values[k]=v
    return {**item,"what":values.get("what",item.get("summary","")),"who":values.get("who","Not stated in supplied sources"),"when":values.get("when","Not stated in supplied sources"),"where":values.get("where","Not stated in supplied sources"),"why":values.get("why","Not stated in supplied sources"),"why_important":values.get("why_important","Not stated in supplied sources"),"background":values.get("background",""),"change_since_yesterday":values.get("change",""),"next":values.get("next","Not stated in supplied sources"),"connection":values.get("connection",""),"memory_hook":values.get("memory",""),"learn":values.get("learn",""),"latest_update":values.get("latest",item.get("summary","")),"entities":values.get("entities",""),"vocabulary":values.get("vocabulary","")}

def _one(item,today):
    prompt=f"Today {today}. Explain ONE story using ONLY evidence. Return exactly: WHAT; WHO; WHEN; WHERE; WHY; WHY IMPORTANT; BACKGROUND; CHANGE; NEXT; CONNECTION; MEMORY; LEARN; LATEST; ENTITIES; VOCABULARY. Make it easy to remember as a flowchart: EVENT -> CAUSE -> IMPACT -> NEXT. Evidence: {json.dumps(item,ensure_ascii=False)}"
    return _parse(_call_ollama(prompt,num_predict=300,timeout=100),item)

def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]
    for item in evidence:
        try: stories.append(_one(item,today))
        except Exception as exc:
            print(f"[WARN] story generation failed: {exc}",flush=True); stories.append(_parse("",item))
    return {"top_stories":stories[:12],"learning_text":""}

def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles,12),articles,previous,today,research)
def generate_text(prompt,system="You are a factual knowledge teacher. Use only supplied data; do not invent."): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
