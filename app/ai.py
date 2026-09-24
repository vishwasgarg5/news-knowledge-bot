from __future__ import annotations
import hashlib,json,os,re
from datetime import datetime,timezone

from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

SYSTEM="""You are the final-stage news intelligence editor. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If a detail is not supported by the supplied evidence, leave that field blank rather than writing a generic disclaimer. Keep every answer concise. Think: EVENT -> WHY -> IMPACT -> CHANGE -> NEXT."""

DEFAULT_MODEL="qwen2.5:3b"; DEFAULT_OLLAMA_URL="http://localhost:11434/api/generate"

def _model_name(): return os.getenv("AI_MODEL","").strip() or os.getenv("OLLAMA_MODEL","").strip() or DEFAULT_MODEL
def _ollama_url(): return os.getenv("OLLAMA_URL",DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL

def _call_ollama(prompt,system=SYSTEM,num_predict=None,timeout=None):
    payload={"model":_model_name(),"system":system,"prompt":prompt,"stream":False,"keep_alive":"5m","options":{"temperature":0.1,"num_ctx":int(os.getenv("AI_CONTEXT","2048")),"num_predict":num_predict or int(os.getenv("AI_MAX_OUTPUT","300"))}}
    req=Request(_ollama_url(),data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlopen(req,timeout=timeout or int(os.getenv("AI_TIMEOUT_SECONDS","25"))) as r:data=json.loads(r.read().decode())
    except HTTPError as e: raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except URLError as e: raise RuntimeError(f"Cannot reach Ollama: {e.reason}") from e
    text=data.get("response","").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    return text

def _words(text): return set(re.findall(r"[a-zA-Z]{4,}",str(text).lower()))
def _similar(a,b):
    wa,wb=_words(a),_words(b); return len(wa&wb)/max(1,len(wa|wb))

def _freshness_bonus(article):
    """Reward genuinely recent articles and penalize stale feed entries."""
    raw=str(article.get("published","") or "").strip()
    if not raw:
        return -2.0
    try:
        value=raw.replace("Z","+00:00")
        dt=datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        age_hours=max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600.0)
    except (TypeError,ValueError):
        return -2.0
    if age_hours <= 6: return 12.0
    if age_hours <= 24: return 8.0
    if age_hours <= 48: return 4.0
    if age_hours <= 72: return 1.0
    return -8.0

def _deterministic_score(a):
    title,summary=str(a.get("title","")),str(a.get("summary","")); source,category=str(a.get("source","")).lower(),str(a.get("category","")).lower(); text=f"{title} {summary}".lower(); score=35.0
    if any(x in source for x in ("reuters","bbc","associated press","ap news","the hindu","indian express","times of india","pib","techcrunch","nasa")): score+=12
    if category in {"india","national","politics","world","economy","business","defence","science","technology"}: score+=8
    for term,boost in {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}.items():
        if term in text: score+=boost
    score+=min(10,2*sum(x in text for x in ("million","billion","lakh","crore","dead","killed","injured","arrested","approved","launched","signed"))); score+=min(8,len(_words(title))*.7); score+=_freshness_bonus(a)
    summary=str(a.get("summary",""))
    if len(summary)<80: score-=2
    if any(x in text for x in ("live updates","live blog","photo gallery","horoscope","quiz","opinion:","editorial:","opinion |")): score-=7
    # A hard freshness floor prevents old feed items from entering the final pool.
    raw=str(a.get("published","") or "").strip()
    if raw:
        try:
            value=raw.replace("Z","+00:00"); dt=datetime.fromisoformat(value)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            age=(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600
            if age>120: score-=12
            if age>168: score-=35
        except (TypeError,ValueError): pass
    return min(100.0,score)

def _event_id(title):
    words=sorted(_words(title)); return hashlib.sha1(" ".join(words[:32]).encode()).hexdigest()[:16]

def _event_similarity(a,b):
    """Headline similarity that tolerates paraphrases while requiring meaningful overlap."""
    wa,wb=_words(a),_words(b)
    if not wa or not wb: return 0.0
    common=len(wa&wb); base=common/max(1,len(wa|wb))
    named_a=set(re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(a)))
    named_b=set(re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(b)))
    named=len({x.lower() for x in named_a}&{x.lower() for x in named_b})
    if named>=1 and common>=2: return max(base,0.24)
    if common>=4: return max(base,0.20)
    return base

def select_stories(articles,top_n=None,excluded_headlines=None):
    excluded=list(excluded_headlines or []); ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
        if any(_similar(title,old)>=.62 for old in excluded): continue
        words=_words(title)
        if any(_event_similarity(title,old)>=.72 for old in seen): continue
        seen.append(words); ranked.append((round(_deterministic_score(a),1),a))
    ranked.sort(key=lambda x:(-x[0],str(x[1].get("published",""))))
    threshold=float(os.getenv("NEWS_MIN_IMPORTANCE","62")); candidate_limit=max(1,int(os.getenv("NEWS_CANDIDATE_LIMIT","700")))
    max_stories=int(os.getenv("NEWS_MAX_STORIES","0")); requested=candidate_limit if top_n is None else max(1,int(top_n))
    if max_stories>0: requested=max_stories if top_n is None else max(1,int(top_n))
    limit=min(requested,candidate_limit); selected=[]; category_counts={}; max_per_category=max(1,int(os.getenv("NEWS_MAX_PER_CATEGORY","8")))
    for score,a in ranked:
        if score < threshold: continue
        category=str(a.get("category","Other")).strip().lower() or "other"
        if max_stories>0 and category_counts.get(category,0)>=max_per_category: continue
        title=str(a.get("title",""))
        selected.append({"story_id":hashlib.sha1(title.lower().encode()).hexdigest()[:16],"event_id":_event_id(title),"rank":len(selected)+1,"headline":title[:240],"importance":score,"category":str(a.get("category","Other")),"region":str(a.get("region","world")).lower(),"url":str(a.get("url","")),"source":str(a.get("source","")),"reason":"Impact, source quality, relevance and novelty."})
        category_counts[category]=category_counts.get(category,0)+1
        if len(selected)>=limit: break
    return selected

def rerank_stories(stories,research=None):
    """Rank by importance, verification, source diversity and novelty; India first, then World."""
    research=research or {}; scored=[]
    for s in stories:
        r=research.get(s.get("story_id"),{}) or {}
        conf=float(r.get("confidence",0) or 0)
        indep=int(r.get("independent_sources",0) or 0)
        importance=float(s.get("importance",0) or 0)
        novelty=100.0 if not r.get("historical") else 65.0
        verification=r.get("verification","unverified")
        if verification=="unverified": conf=min(conf,50)
        verification_bonus={"multi-source":12,"official-source":9,"single-source":4}.get(verification,0)
        source_diversity=min(8,indep*2)
        final=(0.56*importance + 0.24*conf + 0.08*min(100,50+indep*15)
               + 0.06*novelty + verification_bonus + source_diversity)
        item=dict(s); item["ranking_score"]=round(final,1)
        scored.append((final,item))

    india=[x for x in scored if str(x[1].get("region","")).lower()=="india"]
    world=[x for x in scored if str(x[1].get("region","")).lower()!="india"]
    india.sort(key=lambda x:(-x[0],-float(x[1].get("importance",0) or 0)))
    world.sort(key=lambda x:(-x[0],-float(x[1].get("importance",0) or 0)))

    india_limit=max(1,int(os.getenv("NEWS_INDIA_TOP","15")))
    world_limit=max(1,int(os.getenv("NEWS_WORLD_TOP","15")))
    max_stories=int(os.getenv("NEWS_MAX_STORIES","0"))
    if max_stories>0:
        india_limit=min(india_limit,max_stories)
        world_limit=min(world_limit,max(0,max_stories-india_limit))

    selected=[item for _,item in india[:india_limit]] + [item for _,item in world[:world_limit]]
    for rank,item in enumerate(selected,1):
        item["rank"]=rank
    return selected

def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id"); related=[]
        for x in articles:
            if x.get("url")==s.get("url"): continue
            sim=_event_similarity(s.get("headline",""),x.get("title",""))
            if sim>=.20: related.append((sim,x))
        related.sort(key=lambda z:-z[0]); r=(research or {}).get(sid,{})
        out.append({"story_id":sid,"event_id":s.get("event_id",""),"headline":s.get("headline",""),"importance":s.get("importance",0),"ranking_score":s.get("ranking_score",s.get("importance",0)),"category":s.get("category",""),"region":s.get("region","world"),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:900],"related_articles":[{"title":x.get("title",""),"source":x.get("source",""),"url":x.get("url","")} for _,x in related[:5]],"verification":r})
    return out

def _parse(text,item):
    values={}; aliases={"why_important":"impact","change_since_yesterday":"change"}; allowed={"what","who","who_detail","when","where","why","how","impact","key_data","background","change","next","connection","memory","vocabulary"}
    for line in text.splitlines():
        if ":" not in line: continue
        k,v=line.split(":",1); k=aliases.get(k.strip().lower().replace(" ","_"),k.strip().lower().replace(" ","_")); v=v.strip()
        if k in allowed and v: values[k]=v
    return {**item,"what":values.get("what",item.get("summary",item.get("headline",""))),"who":values.get("who",""),"who_detail":values.get("who_detail",""),"when":values.get("when",""),"where":values.get("where",""),"why":values.get("why",""),"how":values.get("how",""),"why_important":values.get("impact",""),"key_data":values.get("key_data",""),"background":values.get("background",""),"change_since_yesterday":values.get("change",item.get("change_since_yesterday","")),"next":values.get("next",""),"connection":values.get("connection",""),"memory_hook":values.get("memory",""),"vocabulary":values.get("vocabulary","")}

def _person_context(name, text):
    """Add concise, role-focused context for major public figures when their identity is explicit."""
    key=re.sub(r"[^a-z ]","",str(name).lower()).strip()
    profiles={
        "donald trump":"Donald Trump — President of the United States (45th and 47th); head of the U.S. executive branch and commander-in-chief.",
        "trump":"Donald Trump — President of the United States (45th and 47th); head of the U.S. executive branch and commander-in-chief.",
        "xi jinping":"Xi Jinping — President of China, General Secretary of the Communist Party of China and Chairman of the Central Military Commission; China's top political leader.",
        "xi":"Xi Jinping — President of China, General Secretary of the Communist Party of China and Chairman of the Central Military Commission; China's top political leader.",
    }
    return profiles.get(key, "")

def _explicit_who(item):
    """Extract named people/roles and add concise identity context without inventing event facts."""
    headline=str(item.get("headline","") or "")
    summary=str(item.get("summary","") or "")
    text=f"{headline} {summary}".strip()
    lower=text.lower()

    # For major leaders, use a maintained role profile so the Telegram briefing
    # answers "who is this person?" rather than only repeating the name.
    named_profiles=[]
    if re.search(r"\b(?:donald\s+)?trump\b", text, re.I):
        named_profiles.append(_person_context("donald trump",text))
    if re.search(r"\bxi\s+jinping\b|\bxi\b", text, re.I):
        named_profiles.append(_person_context("xi jinping",text))
    named_profiles=[x for x in named_profiles if x]
    if named_profiles:
        return " ".join(dict.fromkeys(named_profiles))

    # Strong, role-linked patterns first. These handle common news wording such as
    # "street dancer Wu Yufei" and "Fang Zhenghua, the art director...".
    role_name_patterns=(
        (r"\b(?:chinese|indian|american|british|japanese|korean)?\s*(?:street\s+)?dancer\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)", "dancer"),
        (r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+),\s+(?:the\s+)?(?:art\s+director|director|founder|chief executive officer|ceo|commerciali[sz]ation lead|lead engineer)", ""),
        (r"\b(?:founder|director|ceo|president|minister|prime minister|chief minister|leader of the opposition)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)", ""),
    )
    for pattern, fixed_role in role_name_patterns:
        m=re.search(pattern,text)
        if m:
            name=m.group(1).strip(" .,")
            return f"{name} — {fixed_role}" if fixed_role else name

    # Existing explicit attribution patterns, expanded to capture full names.
    m=re.search(r"\b(?:says|said|asks|asked|warns|warned|according to|by)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\b",text)
    if m:
        return m.group(1).strip(" .,")

    # Generic person-name fallback only when the surrounding text clearly uses a
    # person descriptor. Avoid treating ordinary title-case words as names.
    descriptor_patterns=(
        r"\b(?:the\s+)?(?:27-year-old|\d{2}-year-old)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)",
        r"\b(?:native|performer|engineer|artist|actor|actress|dancer)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)",
    )
    for pattern in descriptor_patterns:
        m=re.search(pattern,text)
        if m:
            return m.group(1).strip(" .,")

    return ""
def _extract_context(item):
    text=f"{item.get('headline','')} {item.get('summary','')}".strip()
    when="Not stated in supplied sources"
    where="Not stated in supplied sources"
    for pattern in (
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?",
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        r"\b(?:today|yesterday|tonight|this morning|this evening)\b",
    ):
        m=re.search(pattern,text,re.I)
        if m:
            when=m.group(0)
            break

    # Prefer explicit location constructions and common news datelines. Avoid
    # broad "in ..." matching, which can incorrectly capture event titles.
    location_patterns=(
        r"\b(?:in|at|from|near)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})(?=\s+(?:on|after|before|where|which|has|have|was|were|is|are|said|according)\b|[.,;:]|$)",
        r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,3}),\s+(?:India|China|Japan|the United States|UK|Britain)\b",
    )
    for pattern in location_patterns:
        m=re.search(pattern,text)
        if m:
            candidate=m.group(1).strip(" .,")
            if candidate and len(candidate.split())<=4:
                where=candidate
                break
    return when,where

def _fallback_how(item):
    text=f"{item.get('headline','')} {item.get('summary','')}".strip()
    m=re.search(r"(?:after|following|when|as|during|by) ([^.]{20,180})[.]", text, re.I)
    return m.group(0).strip() if m else ""

def _fallback_key_data(item):
    text=f"{item.get('headline','')} {item.get('summary','')}".strip()
    vals=re.findall(r"\b(?:₹|\$|€|£)?\d+(?:[.,]\d+)*(?:%|\s*(?:million|billion|crore|lakh|thousand|bn|mn))?\b", text, re.I)
    return ", ".join(dict.fromkeys(vals[:6]))

def _fallback(item):
    summary=item.get("summary") or item.get("headline") or ""
    who=_explicit_who(item)
    text=f"{item.get('headline','')} {item.get('summary','')}".strip()
    headline=str(item.get("headline",summary))
    when,where=_extract_context(item)
    return {**item,"what":summary[:500],"who":who,"who_detail":_person_context(who,text) if who else "", "how":_fallback_how(item), "key_data":_fallback_key_data(item),"when":when,"where":where,"why":f"The report concerns the development described in the headline: {headline[:180]}.","why_important":"Selected because the story met the configured importance threshold.","background":"","change_since_yesterday":item.get("change_since_yesterday",""),"next":"","connection":"","memory_hook":headline[:180],"vocabulary":"","ai_generated":False}
def _one(item,today):
    prompt=f"""Today: {today}
Explain ONE news story using ONLY supplied evidence. Prioritize the newest, concrete facts and distinguish confirmed facts from reported claims. Return EXACTLY 15 short lines:
WHAT: ...
WHO: ...
WHO_DETAIL: ...
WHEN: ...
WHERE: ...
WHY: ...
HOW: ...
IMPACT: ...
KEY_DATA: ...
BACKGROUND: ...
CHANGE: ...
NEXT: ...
CONNECTION: ...
MEMORY: ...
VOCABULARY: NONE
If a person, organisation, date or location is named in the supplied evidence, include the exact name and the relevant role or place. Never replace an identifiable name with "Not stated in supplied sources". Separate reported facts from analysis or interpretation.
WHO_DETAIL should give 1-2 concise sentences for each important named person: current role/position, relevant background, and why they matter to this event. HOW should explain the mechanism or sequence. KEY_DATA should list only important verified numbers, percentages, dates, money or quantities; otherwise write NONE. Use only supplied evidence. No bullets or commentary. Evidence: {json.dumps(item,ensure_ascii=False)}"""
    result=_parse(_call_ollama(prompt,num_predict=220,timeout=int(os.getenv("AI_TIMEOUT_SECONDS","45"))),item)
    explicit=_explicit_who(item)
    current=str(result.get("who","")).strip()
    if explicit and (not current or current.lower().startswith(("not stated","former ","leader ","chief ","the "))): result["who"]=explicit
    if explicit and not str(result.get("who_detail","")).strip(): result["who_detail"]=_person_context(explicit,item.get("headline",""))
    result["ai_generated"]=True
    return result

def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]
    budget=max(0,int(os.getenv("AI_STORY_BUDGET","2")))
    ai_candidates=[x for x in evidence if float(x.get("importance",0))>=float(os.getenv("AI_DEEP_IMPORTANCE","75"))]
    if len(ai_candidates)<budget: ai_candidates=evidence[:budget]
    ai_ids={x.get("story_id") for x in ai_candidates[:budget]}
    for item in evidence:
        if item.get("story_id") not in ai_ids: stories.append(_fallback(item)); continue
        try: stories.append(_one(item,today))
        except Exception as exc:
            print(f"[WARN] story generation failed: {exc}",flush=True); stories.append(_fallback(item))
    return {"top_stories":stories}

def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles),articles,previous,today,research)
def generate_text(prompt,system=SYSTEM): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
