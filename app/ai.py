from __future__ import annotations
import hashlib,json,os,re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
SYSTEM="""You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If evidence is missing, say 'Not stated in supplied sources'. Produce useful, structured explanations."""
DEFAULT_MODEL="qwen2.5:7b"; DEFAULT_OLLAMA_URL="http://localhost:11434/api/generate"
def _model_name(): return os.getenv("AI_MODEL","").strip() or os.getenv("OLLAMA_MODEL","").strip() or DEFAULT_MODEL
def _ollama_url(): return os.getenv("OLLAMA_URL",DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL
def _call_ollama(prompt,system=SYSTEM,num_predict=None,timeout=None):
    payload={"model":_model_name(),"system":system,"prompt":prompt,"stream":False,"keep_alive":"10m","options":{"temperature":0.1,"num_ctx":int(os.getenv("AI_CONTEXT","3072")),"num_predict":num_predict or int(os.getenv("AI_MAX_OUTPUT","700"))}}
    req=Request(_ollama_url(),data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=timeout or int(os.getenv("AI_TIMEOUT_SECONDS","120"))) as r: data=json.loads(r.read().decode())
    except HTTPError as e: raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except URLError as e: raise RuntimeError(f"Cannot reach Ollama: {e.reason}") from e
    text=data.get("response","").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    return text

def _words(text): return set(re.findall(r"[a-zA-Z]{4,}",text.lower()))
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
        if any(_similar(title,old)>=0.62 for old in excluded): continue
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

def _related(item,articles,limit):
    q=_words(item.get("headline","")+" "+item.get("category","") ); scored=[]
    for a in articles:
        title=str(a.get("title","") or ""); url=str(a.get("url","") or "")
        if not title or url==item.get("url"): continue
        overlap=len(q&_words(title)); ratio=overlap/max(1,len(q|_words(title)))
        if overlap>=2: scored.append((ratio,overlap,a))
    scored.sort(key=lambda x:(-x[0],-x[1],str(x[2].get("published",""))))
    return [{"title":str(a.get("title",""))[:240],"summary":str(a.get("summary","") or "")[:500],"source":a.get("source",""),"url":a.get("url","")} for _,_,a in scored[:limit]]
def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id") or hashlib.sha1(str(s.get("headline","")).lower().encode()).hexdigest()[:16]
        rank=int(s.get("rank",99)); importance=float(s.get("importance",0)); depth=8 if rank<=3 or importance>=85 else (4 if rank<=8 or importance>=65 else 1)
        out.append({"story_id":sid,"headline":s.get("headline",""),"importance":s.get("importance",0),"category":s.get("category",""),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:500],"related_articles":_related(s,articles,depth),"historical":(research or {}).get(sid,[])[:5],"research_depth":depth})
    return out
def _parse_batch(text,items):
    blocks=re.split(r"\n\s*###\s*STORY\s+\d+\s*\n",text,flags=re.I); blocks=[b.strip() for b in blocks if b.strip()]; result=[]; keys={"what","who","when","where","why","why_important","learn","latest","change","perspective","next","background","entities"}
    for i,item in enumerate(items):
        block=blocks[i] if i<len(blocks) else ""; values={}
        for line in block.splitlines():
            if ":" in line:
                k,v=line.split(":",1); k=k.strip().lower().replace(" ","_"); v=v.strip()
                if k in keys and v: values[k]=v
        result.append({"story_id":item["story_id"],"headline":item["headline"],"importance":item["importance"],"category":item["category"],"what":values.get("what",item["summary"]),"who":values.get("who","Not stated in supplied sources"),"when":values.get("when","Not stated in supplied sources"),"where":values.get("where","Not stated in supplied sources"),"why":values.get("why","Not stated in supplied sources"),"why_important":values.get("why_important","Selected by importance score"),"learn":values.get("learn",""),"latest_update":values.get("latest",item["summary"]),"change_since_yesterday":values.get("change",""),"background":values.get("background",""),"perspective":values.get("perspective",""),"next":values.get("next",""),"entities":values.get("entities",""),"timeline":item.get("historical",[]),"related_articles":item.get("related_articles",[]),"sources":[item["url"]]+[x["url"] for x in item.get("related_articles",[]) if x.get("url")],"people":[],"places":[],"concepts":[],"vocabulary":[]})
    return result
def _one(item,today):
    prompt=f"Today {today}. Give a concise but useful briefing for ONE news topic using ONLY supplied evidence. Return exactly these fields: WHAT; WHO; WHEN; WHERE; WHY; WHY IMPORTANT; BACKGROUND; CHANGE; PERSPECTIVE; NEXT; ENTITIES; LEARN; LATEST. Evidence: {json.dumps(item,ensure_ascii=False)}"
    return _parse_batch(_call_ollama(prompt,num_predict=220,timeout=90),[item])[0]
def _batch(items,today,batch_no):
    prompt=f"Today {today}. Explain exactly {len(items)} news topics using ONLY supplied evidence. Related articles are provided. For each output exactly:\n### STORY N\nWHAT: 2 sentences\nWHO: names if stated\nWHEN: date if stated\nWHERE: place if stated\nWHY: 1-2 sentences\nWHY IMPORTANT: 1-2 sentences\nBACKGROUND: context from evidence\nCHANGE: what is new today versus supplied history\nPERSPECTIVE: compare supplied sources; do not invent opinions\nNEXT: explicit indicated next step or Not stated\nENTITIES: key people/organizations/places\nLEARN: 1 sentence\nLATEST: latest development. No unsupported facts. Evidence: {json.dumps(items,ensure_ascii=False)}"
    print(f"[AI] research batch {batch_no}: {len(items)} topics",flush=True); return _parse_batch(_call_ollama(prompt,num_predict=max(300,len(items)*120),timeout=120),items)
def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]
    groups=[evidence[:3],evidence[3:8],evidence[8:12]]
    for batch_no,items in enumerate([g for g in groups if g],1):
        try: stories.extend(_batch(items,today,batch_no))
        except Exception as exc:
            print(f"[WARN] research batch {batch_no} failed: {exc}; using per-topic fallback",flush=True)
            for item in items:
                try: stories.append(_one(item,today))
                except Exception as err: print(f"[WARN] topic fallback failed: {err}",flush=True); stories.append(_parse_batch("",[item])[0])
    return {"top_stories":stories[:12],"learning_text":""}
def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles,12),articles,previous,today,research)
def generate_text(prompt,system="You are a factual knowledge teacher. Use only supplied data; do not invent."): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
