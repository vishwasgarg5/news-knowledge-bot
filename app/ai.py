from __future__ import annotations
import hashlib,json,os,re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

SYSTEM="""You are the final-stage news intelligence editor. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If evidence is missing, say 'Not stated in supplied sources'. Keep every answer concise, factual and memorable. Think in this order: EVENT -> WHY -> IMPACT -> CHANGE -> NEXT. Do not create separate learning, quiz, culture, religion, vocabulary or people/places content. Vocabulary is allowed only when a genuinely difficult or important news term needs explanation."""
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
    title,summary=str(a.get("title","")),str(a.get("summary","")); source,category=str(a.get("source","" )).lower(),str(a.get("category","" )).lower(); text=f"{title} {summary}".lower(); score=35.0
    if any(x in source for x in ("reuters","bbc","associated press","ap news","the hindu","indian express","times of india","pib")): score+=12
    if category in {"india","national","politics","world","economy","business","defence","science","technology"}: score+=8
    for term,boost in {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}.items():
        if term in text: score+=boost
    score+=min(10,2*sum(x in text for x in ("million","billion","lakh","crore","dead","killed","injured","arrested","approved","launched","signed"))); score+=min(8,len(_words(title))*.7); return min(100.0,score)

def select_stories(articles,top_n=None,excluded_headlines=None):
    excluded=list(excluded_headlines or []); ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
        if any(_similar(title,old)>=.62 for old in excluded): continue
        words=_words(title)
        if any(len(words&old)/max(1,len(words|old))>=.72 for old in seen): continue
        seen.append(words); ranked.append((round(_deterministic_score(a),1),a))
    ranked.sort(key=lambda x:(-x[0],str(x[1].get("published",""))))
    threshold=float(os.getenv("NEWS_MIN_IMPORTANCE","62"))
    selected=[]
    for score,a in ranked:
        if score < threshold: continue
        selected.append({"story_id":hashlib.sha1(str(a.get("title","")).lower().encode()).hexdigest()[:16],"rank":len(selected)+1,"headline":str(a.get("title","")[:240]),"importance":score,"category":str(a.get("category","Other")),"region":str(a.get("region","world")).lower(),"url":str(a.get("url","")),"reason":"Impact, source quality, relevance and ranking score."})
    return selected

def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id"); related=[]
        for x in articles:
            if x.get("url")==s.get("url"): continue
            sim=_similar(s.get("headline",""),x.get("title",""))
            if sim>=0.20: related.append((sim,x))
        related.sort(key=lambda z:-z[0]); r=(research or {}).get(sid,{})
        out.append({"story_id":sid,"headline":s.get("headline",""),"importance":s.get("importance",0),"category":s.get("category",""),"region":s.get("region","world"),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:900],"related_articles":[{"title":x.get("title",""),"source":x.get("source",""),"url":x.get("url","")} for _,x in related[:5]],"verification":r})
    return out

def _parse(text,item):
    values={}; aliases={"why_important":"impact","change_since_yesterday":"change"}; allowed={"what","who","when","where","why","impact","background","change","next","connection","memory","vocabulary"}
    for line in text.splitlines():
        if ":" not in line: continue
        k,v=line.split(":",1); k=aliases.get(k.strip().lower().replace(" ","_"),k.strip().lower().replace(" ","_")); v=v.strip()
        if k in allowed and v: values[k]=v
    return {**item,"what":values.get("what",item.get("summary",item.get("headline",""))),"who":values.get("who","Not stated in supplied sources"),"when":values.get("when","Not stated in supplied sources"),"where":values.get("where","Not stated in supplied sources"),"why":values.get("why","Not stated in supplied sources"),"why_important":values.get("impact","Not stated in supplied sources"),"background":values.get("background",""),"change_since_yesterday":values.get("change",item.get("change_since_yesterday","")),"next":values.get("next","Not stated in supplied sources"),"connection":values.get("connection","Not stated in supplied sources"),"memory_hook":values.get("memory","Not stated in supplied sources"),"vocabulary":values.get("vocabulary","")}

def _fallback(item):
    summary=item.get("summary") or item.get("headline") or "Not stated in supplied sources"
    return {**item,"what":summary[:500],"who":"Not stated in supplied sources","when":"Not stated in supplied sources","where":"Not stated in supplied sources","why":"The available report identifies this as a significant current development.","why_important":"Selected because of its relevance, impact and source quality.","background":"Not stated in supplied sources","change_since_yesterday":item.get("change_since_yesterday",""),"next":"Watch for further official or independent updates.","connection":"Not stated in supplied sources","memory_hook":str(item.get("headline",summary))[:180],"vocabulary":""}

def _one(item,today):
    prompt=f"Today: {today}\nExplain ONE news story using ONLY supplied evidence. Keep every field short. Return EXACTLY 12 separate lines, one field per line:\nWHAT: ...\nWHO: ...\nWHEN: ...\nWHERE: ...\nWHY: ...\nIMPACT: ...\nBACKGROUND: ...\nCHANGE: ...\nNEXT: ...\nCONNECTION: ...\nMEMORY: ...\nVOCABULARY: NONE OR up to 3 genuinely difficult/important terms, formatted as term = simple meaning | news context.\nUse VOCABULARY: NONE when ordinary language is sufficient. Do not add headings, bullets, extra fields or commentary. Evidence: {json.dumps(item,ensure_ascii=False)}"
    return _parse(_call_ollama(prompt,num_predict=340,timeout=100),item)

def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]
    budget=max(0,int(os.getenv("AI_STORY_BUDGET","30")))
    ai_candidates=[x for x in evidence if float(x.get("importance",0))>=float(os.getenv("AI_DEEP_IMPORTANCE","75"))]
    if len(ai_candidates)<budget: ai_candidates=evidence[:budget]
    ai_ids={x.get("story_id") for x in ai_candidates[:budget]}
    for item in evidence:
        if item.get("story_id") not in ai_ids:
            stories.append(_fallback(item)); continue
        try: stories.append(_one(item,today))
        except Exception as exc: print(f"[WARN] story generation failed: {exc}",flush=True); stories.append(_fallback(item))
    return {"top_stories":stories}

def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles),articles,previous,today,research)
def generate_text(prompt,system=SYSTEM): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
