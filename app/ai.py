from __future__ import annotations
import hashlib,json,os,re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
SYSTEM="""You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If evidence is missing, say 'Not stated in supplied sources'. Be concise."""
DEFAULT_MODEL="qwen2.5:7b"; DEFAULT_OLLAMA_URL="http://localhost:11434/api/generate"
def _model_name(): return os.getenv("AI_MODEL","").strip() or os.getenv("OLLAMA_MODEL","").strip() or DEFAULT_MODEL
def _ollama_url(): return os.getenv("OLLAMA_URL",DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL
def _call_ollama(prompt,system=SYSTEM,num_predict=None):
    payload={"model":_model_name(),"system":system,"prompt":prompt,"stream":False,"keep_alive":"10m","options":{"temperature":0.1,"num_ctx":int(os.getenv("AI_CONTEXT","2048")),"num_predict":num_predict or int(os.getenv("AI_MAX_OUTPUT","500"))}}
    req=Request(_ollama_url(),data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=int(os.getenv("AI_TIMEOUT_SECONDS","120"))) as r: data=json.loads(r.read().decode())
    except HTTPError as e: raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except URLError as e: raise RuntimeError(f"Cannot reach Ollama: {e.reason}") from e
    text=data.get("response","").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    return text

def _words(text): return set(re.findall(r"[a-zA-Z]{4,}",text.lower()))
def _deterministic_score(a):
    title,summary=str(a.get("title","")),str(a.get("summary","")); source,category=str(a.get("source","")).lower(),str(a.get("category","")).lower(); text=f"{title} {summary}".lower(); score=35.0
    if any(x in source for x in ("reuters","bbc","associated press","ap news","the hindu","indian express","times of india","pib")): score+=12
    if category in {"india","national","politics","world","economy","business","defence","science","technology"}: score+=8
    for term,boost in {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}.items():
        if term in text: score+=boost
    score+=min(10,2*sum(x in text for x in ("million","billion","lakh","crore","dead","killed","injured","arrested","approved","launched","signed"))); score+=min(8,len(_words(title))*.7); return min(100.0,score)
def select_stories(articles,top_n=12):
    ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
        words=_words(title)
        if any(len(words&old)/max(1,len(words|old))>=.72 for old in seen): continue
        seen.append(words); ranked.append((round(_deterministic_score(a),1),a))
    ranked.sort(key=lambda x:(-x[0],str(x[1].get("published","")))); selected=[];cats={}
    for score,a in ranked:
        cat=str(a.get("category","Other"))
        if cats.get(cat,0)>=max(3,top_n//3): continue
        cats[cat]=cats.get(cat,0)+1; headline=str(a.get("title",""))[:240]; sid=hashlib.sha1(headline.lower().encode()).hexdigest()[:16]
        selected.append({"story_id":sid,"rank":len(selected)+1,"headline":headline,"importance":score,"category":cat,"url":str(a.get("url","")),"reason":"Deterministic impact/source/relevance score."})
        if len(selected)>=top_n: break
    return selected

def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id") or hashlib.sha1(str(s.get("headline","")).lower().encode()).hexdigest()[:16]
        out.append({"story_id":sid,"headline":s.get("headline",""),"importance":s.get("importance",0),"category":s.get("category",""),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:350],"historical":(research or {}).get(sid,[])[:3]})
    return out

def _parse_batch(text,items):
    blocks=re.split(r"\n\s*###\s*STORY\s+\d+\s*\n",text,flags=re.I); blocks=[b.strip() for b in blocks if b.strip()]
    result=[]
    for i,item in enumerate(items):
        block=blocks[i] if i<len(blocks) else ""; values={}
        for line in block.splitlines():
            if ":" in line:
                k,v=line.split(":",1); k=k.strip().lower().replace(" ","_"); v=v.strip()
                if k in {"what","who","when","where","why","why_important","learn","latest"} and v: values[k]=v
        result.append({"story_id":item["story_id"],"headline":item["headline"],"importance":item["importance"],"category":item["category"],"what":values.get("what",item["summary"]),"who":values.get("who","Not stated in supplied sources"),"when":values.get("when","Not stated in supplied sources"),"where":values.get("where","Not stated in supplied sources"),"why":values.get("why","Not stated in supplied sources"),"why_important":values.get("why_important","Selected by importance score"),"learn":values.get("learn",""),"latest_update":values.get("latest",item["summary"]),"timeline":item.get("historical",[]),"sources":[item["url"]],"people":[],"places":[],"concepts":[],"vocabulary":[]})
    return result

def _one(item,today):
    prompt=f"Today {today}. Explain ONE news story using ONLY evidence. Return exactly these lines: WHAT:; WHO:; WHEN:; WHERE:; WHY:; WHY IMPORTANT:; LEARN:. Evidence: {json.dumps(item,ensure_ascii=False)}"
    return _parse_batch(_call_ollama(prompt,num_predict=150),[item])[0]

def _extras(evidence,today):
    compact=[{"headline":x["headline"],"summary":x["summary"]} for x in evidence]
    p=f"Today {today}. Based ONLY on supplied evidence, write plain text sections: CURRENT AFFAIRS (2 points); CULTURE (only if evidence supports it); RELIGION (only if evidence supports it); VOCABULARY (3 word - meaning pairs); REVISION (2 questions); QUIZ (2 questions with answers). Do not invent. Evidence: {json.dumps(compact,ensure_ascii=False)}"
    return _call_ollama(p,num_predict=260)

def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]
    # One batched Qwen request is much faster on CPU than 12 sequential requests.
    prompt=f"Today {today}. Explain all {len(evidence)} stories using ONLY supplied evidence. For each story output exactly:\n### STORY N\nWHAT: one short sentence\nWHO: names if stated\nWHEN: date/time if stated\nWHERE: place if stated\nWHY: one short sentence\nWHY IMPORTANT: one short sentence\nLEARN: one useful context sentence\nLATEST: one short sentence. No JSON. Evidence: {json.dumps(evidence,ensure_ascii=False)}"
    try:
        print(f"[AI] batch 1/{len(evidence)}",flush=True); stories=_parse_batch(_call_ollama(prompt,num_predict=min(1600,max(900,len(evidence)*110))),evidence)
        if len(stories)!=len(evidence): raise RuntimeError("batch parser returned wrong story count")
    except Exception as exc:
        print(f"[WARN] batch AI failed: {exc}; using per-story fallback",flush=True)
        for i,item in enumerate(evidence,1):
            print(f"[AI] fallback story {i}/{len(evidence)}",flush=True)
            try: stories.append(_one(item,today))
            except Exception as err: print(f"[WARN] story {i} AI failed: {err}",flush=True); stories.append(_parse_batch("",[item])[0])
    try: extra=_extras(evidence,today)
    except Exception as exc: print(f"[WARN] learning extras failed: {exc}",flush=True); extra=""
    return {"top_stories":stories[:12],"learning_text":extra}

def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles,12),articles,previous,today,research)
def generate_text(prompt,system="You are a factual knowledge teacher. Use only supplied data; do not invent."): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
