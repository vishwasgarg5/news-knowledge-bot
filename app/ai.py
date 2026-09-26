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
    raw=str(article.get("published","") or "").strip()
    if not raw: return -2.0
    try:
        value=raw.replace("Z","+00:00"); dt=datetime.fromisoformat(value)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        age_hours=max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600.0)
    except (TypeError,ValueError): return -2.0
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
    if len(summary)<80: score-=2
    if any(x in text for x in ("live updates","live blog","photo gallery","horoscope","quiz","opinion:","editorial:","opinion |")): score-=7
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
    """Conservative same-event score: shared entities plus the concrete event."""
    wa,wb=_words(a),_words(b)
    if not wa or not wb: return 0.0
    common=wa&wb; base=len(common)/max(1,len(wa|wb))
    generic_names={"supreme","court","high","delhi","assembly","government","president","prime","minister","chief","election","commission","police","video","india","indian","american","united","states","white","house","china"}
    named_a={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(a)) if x.lower() not in generic_names}
    named_b={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(b)) if x.lower() not in generic_names}
    named=named_a&named_b
    event_terms={"breach","hack","attack","arrest","ban","blocked","access","symbol","logo","launch","launched","deal","trade","truce","visit","arrives","arrived","glasses","intelligence","super","result","results","election","court","judge","verdict","trial","crash","earthquake","cyclone","hurricane","storm","fire","flood","death","dies","killed","injured","student","strike","protest","approval","approved","agreement","summit","sanctions","dispute","ruling","order","timeline"}
    event_overlap=common&event_terms
    if base>=0.72: return 0.90
    if len(named)>=1 and len(event_overlap)>=1 and len(common)>=2: return max(base,0.76)
    if len(named)>=1 and len(common)>=4: return max(base,0.70)
    if base>=0.50 and len(common)>=4: return max(base,0.64)
    return base
def _same_event(a,b):
    """Conservative final-selection duplicate detector."""
    ta=_content_tokens(a); tb=_content_tokens(b); common=ta&tb
    base=len(common)/max(1,len(ta|tb))
    # Broad lexical overlap was collapsing unrelated stories. Only collapse
    # near-identical headlines here, plus explicit multi-token event families.
    if base>=0.80: return True
    families=[
        {"openai","australia","hack","hacked","breach","breached","infiltrated","portal","cyber"},
        {"muse","agent","wearable","glasses","meta","tamagotchi"},
        {"gyanesh","cec","eci","election","commission","resign","resignation","removal","remove","notice","motion","vote","voter"},
        {"rahul","gandhi","vote","voter","chori","cec","election","commission"},
        {"iit","bombay","student","death","professor","director","azad","maidan"},
        {"polo","hurricane","mexico","hawaii","storm","landfall","nolo"},
        {"xi","jinping","trump","china","white","house","dinner"},
        {"netanyahu","iran","unga","israel","united","nations","gaza"},
        {"cauvery","tamil","karnataka","water","tmc","drought"},
        {"hilsa","bangladesh","fish","importing","exports"},
        {"asian","games","medal","medallist","medallists","shooters","table","tennis"},
        {"obc","creamy","layer","supreme","court","retrospective","verdict"},
    ]
    for family in families:
        shared=common & family
        if len(shared)>=2:
            return True
    return False

def _is_non_news_content(article):
    """Exclude service, promotional and lifestyle content from intelligence selection."""
    title=str(article.get("title","") or "").lower()
    summary=str(article.get("summary","") or "").lower()
    text=f"{title} {summary}"
    hard_patterns=(
        r"\\b(?:discount|deal|offer|save|coupon|promo(?:tion)?|sale|tickets?|pass|expo\\+|early[- ]bird)\\b",
        r"\\b(?:coming to|joins us at|will be at|meet .* at)\\b",
        r"\\b(?:buy|shop|subscribe|register|book now|sign up)\\b",
        r"\\b(?:horoscope|quiz|photo gallery|live updates|live blog)\\b",
        r"\\b(?:weekend|daily)\\s+(?:weather|forecast)\\b",
    )
    if any(re.search(p,text,re.I) for p in hard_patterns):
        return True
    # A plain weather forecast is a service item; an actual storm/flood event remains eligible.
    if re.search(r"\\b(?:forecast|weather outlook)\\b",title,re.I) and not re.search(r"\\b(?:storm|cyclone|hurricane|flood|landfall|evacuat|warning)\\b",title,re.I):
        return True
    return False

def select_stories(articles,top_n=None,excluded_headlines=None):
    excluded=list(excluded_headlines or []); ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
        if _is_non_news_content(a): continue
        if any(_similar(title,old)>=.62 for old in excluded): continue
        # Deduplicate only when the headline itself strongly indicates the same event.
        # Do not use the full summary here: broad summaries can share generic words
        # and incorrectly collapse unrelated stories.
        event_text=title
        if any(_event_similarity(event_text,old)>=.70 for old in seen): continue
        seen.append(event_text); ranked.append((round(_deterministic_score(a),1),a))
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
        selected.append({"story_id":hashlib.sha1(title.lower().encode()).hexdigest()[:16],"event_id":_event_id(title),"rank":len(selected)+1,"headline":title[:240],"importance":score,"category":str(a.get("category","Other")),"region":str(a.get("region","world")).lower(),"region_confidence":round(float(a.get("region_confidence",0) or 0),2),"region_evidence":str(a.get("region_evidence","") or ""),"url":str(a.get("url","")),"source":str(a.get("source","")),"_event_text":event_text,"reason":"Impact, source quality, relevance and novelty."})
        category_counts[category]=category_counts.get(category,0)+1
        if len(selected)>=limit: break
    return selected

def _development_signature(title):
    """Extract concrete action/development words for event-family diversity."""
    tokens=_content_tokens(title)
    actions={
        "arrest","arrested","detained","charged","indicted","killed","dies","death","injured",
        "resign","resigns","resignation","remove","removal","impeach","impeachment","protest","protests",
        "launch","launched","launches","unveils","unveiled","releases","release","deploy","deployed",
        "hack","hacked","breach","breached","infiltrated","attack","attacked","strike","strikes",
        "ban","bans","banned","block","blocked","approve","approved","rule","rules","ruling","verdict",
        "sign","signed","deal","agreement","summit","visit","hosts","hosted","warn","warns","warning",
        "landfall","tracks","strengthens","surge","surges","election","vote","voters","results"
    }
    return tokens & actions

def _event_family_key(title):
    """Return a stable family key for known recurring event clusters."""
    raw=str(title or "").lower()
    t=_content_tokens(title)
    families=[
        ("openai_australia",{"openai","australia","hack","hacked","breach","infiltrated","portal"}),
        ("meta_muse",{"muse","meta","wearable","glasses","tamagotchi"}),
        ("sennheiser_momentum5",{"sennheiser","momentum","wireless","earbuds","headphones"}),
        ("election_commission_sir",{"gyanesh","cec","eci","election","commission","sir","voter","voters","rolls","electoral","poll","polls"}),
        ("election_commission_sir",{"rahul","gandhi","vote","voter","chori","cec","election","commission","sir","rolls"}),
        ("iit_bombay",{"iit","bombay","student","death","professor","director","azad","maidan"}),
        ("hurricane_polo",{"polo","hurricane","mexico","hawaii","storm","landfall","nolo"}),
        ("trump_xi",{"xi","jinping","trump","china","white","house","dinner"}),
        ("netanyahu_un",{"netanyahu","iran","unga","israel","united","nations","gaza","speech","address","delegates","walkout"}),
        ("cauvery",{"cauvery","tamil","karnataka","water","cusecs","reservoir"}),
        ("hilsa",{"hilsa","bangladesh","fish","importing","exports"}),
        ("asian_games",{"asian","games","medal","medallist","medallists","shooters","table","tennis"}),
        ("obc_creamy_layer",{"obc","creamy","layer","supreme","court","retrospective","verdict"}),
        ("ethiopia_tigray",{"ethiopia","tigray","eritrea","fighting","conflict","internet","restricted","army","attacks"}),
    ]
    # High-signal anchors prevent two reports of the same development from occupying separate slots.
    if re.search(r"\btrump\b",raw) and re.search(r"\bxi\b",raw):
        return "trump_xi"
    if re.search(r"\bopenai\b",raw) and re.search(r"\baustralia\b",raw):
        return "openai_australia"
    if re.search(r"\bmeta\b",raw) and re.search(r"\bmuse\b",raw):
        return "meta_muse"
    if (t & {"cec","eci","gyanesh"}) and (t & {"election","commission","sir","voter","voters","electoral","rolls","protest","removal","resign","resignation"}):
        return "election_commission_sir"
    if "sir" in t and (t & {"election","voter","voters","rolls","electoral","commission","cec","eci","protest","barricaded","barricade","jantar","mantar"}):
        return "election_commission_sir"
    for key,family in families:
        if len(t & family)>=2:
            return key
    return ""

def _same_event_family(a,b):
    """Detect the same underlying event family deterministically."""
    if str(a.get("event_id","")) and str(a.get("event_id",""))==str(b.get("event_id","")):
        return True
    ka=_event_family_key(a.get("headline",""))
    kb=_event_family_key(b.get("headline",""))
    if ka and kb and ka==kb:
        return True
    # Known families are intentionally broad: one regional slot should
    # represent one distinct development, not several reports on it.
    if ka or kb:
        return False
    return _same_event(a.get("headline",""),b.get("headline","")) or _event_similarity(a.get("headline",""),b.get("headline",""))>=0.76

def _genuinely_new_development(a,b):
    """Allow a second story only when the headline describes a concrete new action."""
    aa=_development_signature(a.get("headline","")); bb=_development_signature(b.get("headline",""))
    if not aa or not bb: return False
    # Same action words normally describe the same development.
    if aa == bb or len(aa & bb) >= 2: return False
    # Require a meaningful action change and materially different headlines.
    return len(aa ^ bb) >= 2 and _similar(a.get("headline",""),b.get("headline","")) < 0.58

def _select_diverse(pool,limit,family_counts=None):
    selected=[]; family_counts=family_counts if family_counts is not None else {}
    max_family=max(1,int(os.getenv("NEWS_MAX_EVENT_FAMILY","1")))
    for score,item in pool:
        if len(selected)>=limit: break
        # Always run the pairwise event-family check, even when the candidate
        # has a family key. This catches variants whose token pattern produces
        # different keys but still describes the same development.
        same=[x for x in selected if _same_event_family(item,x)]
        if same:
            if len(same)>=max_family or not all(_genuinely_new_development(item,x) for x in same):
                continue
        key=_event_family_key(item.get("headline",""))
        if key:
            count=family_counts.get(key,0)
            if count>=max_family:
                continue
            family_counts[key]=count+1
        selected.append(item)
    return selected

def rerank_stories(stories,research=None):
    research=research or {}; scored=[]
    for s in stories:
        r=research.get(s.get("story_id"),{}) or {}
        conf=float(r.get("confidence",0) or 0); indep=int(r.get("independent_sources",0) or 0); importance=float(s.get("importance",0) or 0)
        novelty=100.0 if not r.get("historical") else 65.0; verification=r.get("verification","unverified")
        if verification=="unverified": conf=min(conf,50)
        verification_bonus={"multi-source":12,"official-source":9,"multi-report":2,"single-source":-4}.get(verification,0)
        source_diversity=min(8,indep*2)
        published_importance=importance
        if verification=="single-source": published_importance=min(published_importance,72.0)
        elif verification=="unverified": published_importance=min(published_importance,68.0)
        quality_penalty=10 if r.get("primary_derivative") else 0
        item=dict(s); item["importance"]=round(published_importance,1)
        final=(0.56*published_importance + 0.24*conf + 0.08*min(100,50+indep*15) + 0.06*novelty + verification_bonus + source_diversity - quality_penalty)
        item["ranking_score"]=round(final,1); scored.append((final,item))

    min_single_importance=float(os.getenv("NEWS_SINGLE_SOURCE_MIN_IMPORTANCE","85"))
    def eligible(pair):
        score,item=pair
        r=research.get(item.get("story_id"),{}) or {}
        v=r.get("verification","unverified")
        if r.get("primary_derivative"): return False
        if v=="single-source": return float(item.get("importance",0) or 0) >= min_single_importance
        if v=="unverified": return False
        return True
    quality_scored=[x for x in scored if eligible(x)]
    india=[x for x in quality_scored if str(x[1].get("region","")).lower()=="india" and float(x[1].get("region_confidence",0) or 0)>=float(os.getenv("NEWS_INDIA_MIN_REGION_CONFIDENCE","0.60"))]
    world=[x for x in quality_scored if str(x[1].get("region","")).lower()=="world"]
    india.sort(key=lambda x:(-x[0],-float(x[1].get("importance",0) or 0)))
    world.sort(key=lambda x:(-x[0],-float(x[1].get("importance",0) or 0)))

    india_limit=max(1,int(os.getenv("NEWS_INDIA_TOP","15"))); world_limit=max(1,int(os.getenv("NEWS_WORLD_TOP","15")))
    max_stories=int(os.getenv("NEWS_MAX_STORIES","0"))
    if max_stories>0:
        india_limit=min(india_limit,max_stories); world_limit=min(world_limit,max(0,max_stories-india_limit))

    # One shared family ledger prevents the same development from occupying
    # both an India slot and a World slot.
    family_counts={}
    india_selected=_select_diverse(india,india_limit,family_counts)
    world_selected=_select_diverse(world,world_limit,family_counts)

    # Backfill only from candidates that pass the same geographic and event-family
    # rules. Never fill an India slot with an item whose geography is uncertain.
    selected=india_selected[:india_limit] + world_selected[:world_limit]
    for rank,item in enumerate(selected,1):
        item["rank"]=rank
        if not item.get("selection_reason"):
            item["selection_reason"]="Highest verified ranking within the regional and event-family diversity constraints."
    return selected

def _corroboration_score(a,b):
    """Conservative event match; related evidence must describe the same concrete development."""
    base=_similar(a,b)
    wa,wb=_content_tokens(a),_content_tokens(b)
    common=wa&wb
    generic={"supreme","court","government","president","prime","minister","chief","election","commission","india","world","news","today","latest","report"}
    named_a={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(a)) if x.lower() not in generic}
    named_b={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(b)) if x.lower() not in generic}
    named=named_a&named_b
    event_terms={"breach","hack","attack","arrest","ban","blocked","access","symbol","logo","launch","launched","deal","trade","truce","visit","arrives","arrived","glasses","intelligence","result","results","election","judge","verdict","trial","crash","earthquake","cyclone","hurricane","storm","fire","flood","death","dies","killed","injured","strike","protest","approval","approved","agreement","summit","sanctions","dispute","ruling","order","renamed","rename","bars","barred","opens","reopens","offer","appoint","appointed"}
    event_overlap=common&event_terms
    if base>=0.58 and len(common)>=5: return base
    if len(named)>=1 and len(event_overlap)>=1 and len(common)>=4: return max(base,0.56)
    if len(named)>=2 and len(common)>=4: return max(base,0.56)
    return 0.0

def _evidence(selected,articles,research):
    by_url={str(a.get("url","")):a for a in articles}; out=[]
    for s in selected:
        a=by_url.get(str(s.get("url","")),{}); sid=s.get("story_id"); related=[]
        for x in articles:
            if x.get("url")==s.get("url"): continue
            sim=_corroboration_score(s.get("headline",""),x.get("title",""))
            if sim>=.55: related.append((sim,x))
        related.sort(key=lambda z:-z[0]); r=(research or {}).get(sid,{})
        merged=[]; seen=set()
        for x in [x for x in (r.get("evidence") or []) if _corroboration_score(s.get("headline",""),x.get("title",""))>=.55] + [x for _,x in related[:6]]:
            key=str(x.get("url","") or x.get("title","")).strip()
            if not key or key in seen: continue
            seen.add(key); merged.append(x)
        out.append({"story_id":sid,"event_id":s.get("event_id",""),"headline":s.get("headline",""),"importance":s.get("importance",0),"ranking_score":s.get("ranking_score",s.get("importance",0)),"category":s.get("category",""),"region":s.get("region","world"),"source":a.get("source",""),"url":s.get("url",""),"summary":str(a.get("summary","") or "")[:900],"related_articles":[{"title":x.get("title",""),"source":x.get("source",""),"url":x.get("url",""),"published":x.get("published",""),"summary":str(x.get("summary","") or "")[:900]} for x in merged[:8]],"verification":r})
    return out

def _evidence_text(item):
    parts=[str(item.get("headline","") or ""),str(item.get("summary","") or "")]
    for x in item.get("related_articles") or []:
        parts.extend([str(x.get("title","") or ""),str(x.get("summary","") or "")])
    return " ".join(parts)

def _content_tokens(text):
    # Keep meaningful short acronyms/names such as CEC, RBI, ECI and IIT.
    return set(re.findall(r"[a-zA-Z]{3,}",str(text).lower()))

def _field_supported(value,evidence,min_overlap=2):
    v=_content_tokens(value); e=_content_tokens(evidence)
    return bool(v and e and len(v&e)>=min_overlap)

def _number_supported(value,evidence):
    nums=re.findall(r"(?:₹|\$|€|£)?\s*\d+(?:[.,]\d+)*(?:\s*(?:million|billion|crore|lakh|thousand|bn|mn|hours?|minutes?|g|kg|GB|TB|%))?",str(value),re.I)
    if not nums: return True
    normalized=re.sub(r"\s+","",str(evidence).lower())
    return all(re.sub(r"\s+","",n.lower()) in normalized for n in nums)

def _parse(text,item):
    values={}; aliases={"why_important":"impact","change_since_yesterday":"change"}; allowed={"what","who","who_detail","when","where","why","how","impact","key_data","background","change","next","connection","memory","vocabulary"}; bad={"...","…","n/a","na","none","not stated","not specified","unknown"}
    for line in text.splitlines():
        if ":" not in line: continue
        k,v=line.split(":",1); k=aliases.get(k.strip().lower().replace(" ","_"),k.strip().lower().replace(" ","_")); v=v.strip()
        if k in allowed and v and v.lower().strip(" .") not in bad: values[k]=v
    fallback_who=_explicit_who(item); who=values.get("who","").strip().strip(" .,-")
    bad_name_tokens={"monday","tuesday","wednesday","thursday","friday","saturday","sunday","meanwhile","the","burnham","yesterday","today","tomorrow","however","also","then","after","before"}
    invalid_who_words=r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|meanwhile|yesterday|today|tomorrow|however|also|then|after|before)\b"
    if who and (len(who)>180 or re.search(invalid_who_words,who,re.I) or len(who.split())>16): who=""
    org_words={"court","commission","government","house","parliament","board","agency","company","games","organization","organisation","nasa","isro","cbse"}
    if who and not re.search(r"[A-Z][A-Za-z.'-]{2,}",who): who=""
    if who and any(t.lower().strip(".,") in bad_name_tokens for t in who.split()): who=""
    if who and any(t.lower().strip(".,") in org_words for t in who.split()): who=""
    if who and len(who.split())==1 and who.lower() in {"the","meanwhile","monday","june","burnham","supreme"}: who=""
    if not who and fallback_who: who=fallback_who
    where_value=values.get("where","").strip(" .,-")
    month_words={"january","february","march","april","may","june","july","august","september","october","november","december","jan","feb","mar","apr","jun","jul","aug","sep","sept","oct","nov","dec"}
    bad_where_words=month_words|{"today","yesterday","tomorrow","tonight","monday","tuesday","wednesday","thursday","friday","saturday","sunday","meanwhile","however","then","after","before"}
    where_lower=where_value.lower()
    if (where_lower in bad_where_words or re.search(r"\b(?:19|20)\d{2}\b",where_value) or re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?",where_value,re.I) or re.search(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",where_value,re.I)): where_value=""
    if not where_value:
        _,det_where=_extract_context(item); where_value=det_where or ""
    # Re-validate deterministic location recovery too; dates/months must never
    # reach Telegram as a location.
    where_lower=where_value.lower().strip(" .,")
    if (where_lower in bad_where_words or re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?",where_lower) or re.search(r"\b(?:19|20)\d{2}\b",where_value)):
        where_value=""
    evidence=_evidence_text(item)
    for field in ("why","how","impact","background","change","next","connection","vocabulary"):
        if values.get(field) and not _field_supported(values[field],evidence,2): values[field]=""
    if values.get("memory") and _similar(str(values["memory"]),str(item.get("headline","")) or str(item.get("summary","")))>0.70:
        values["memory"]=""
    # Reject semantically wrong enrichment even when its words happen to occur
    # in the evidence. WHY needs a causal cue; HOW needs a mechanism, not a
    # chronology fragment; BACKGROUND must add context rather than restating WHAT.
    what_text=str(item.get("summary","") or item.get("headline",""))
    causal=re.compile(r"\b(?:because|due to|amid|after|following|in response to|to address|to prevent|to reduce|to improve|as a result|over|in the wake of)\b",re.I)
    mechanism=re.compile(r"\b(?:by|through|using|via|with|under|under a|as part of)\b",re.I)
    chronology_start=re.compile(r"^(?:after|following|during|before|when|while|as)\b",re.I)
    for field in ("why","impact","background","change"):
        value=str(values.get(field,"") or "").strip()
        if value and _similar(value,what_text)>=0.72:
            values[field]=""
    if values.get("why") and not causal.search(str(values["why"])):
        values["why"]=""
    if values.get("how") and (chronology_start.search(str(values["how"])) or not mechanism.search(str(values["how"]))):
        values["how"]=""
    if values.get("background"):
        bg=str(values["background"]).strip()
        if chronology_start.search(bg) or re.search(r"^(?:the|this) (?:move|decision|action|announcement)\b",bg,re.I):
            values["background"]=""
    if values.get("connection") and _similar(str(values["connection"]),what_text)>=0.72:
        values["connection"]=""
    # WHO_DETAIL must be tied to evidence as well.
    if values.get("who_detail"):
        who_detail=str(values["who_detail"]).strip()
        if not _field_supported(who_detail,evidence,2):
            values["who_detail"]=""
    if values.get("key_data") and not _number_supported(values["key_data"],evidence): values["key_data"]=""
    if values.get("who"):
        who_tokens=_content_tokens(values["who"])
        named_evidence={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",evidence)}
        if not (who_tokens & named_evidence): values["who"]=""
    if where_value and not _field_supported(where_value,evidence,1): where_value=""
    return {**item,"what":values.get("what",item.get("summary",item.get("headline",""))),"who":who,"who_detail":values.get("who_detail","") if who else "","when":values.get("when",""),"where":where_value,"why":values.get("why",""),"how":values.get("how",""),"why_important":values.get("impact",""),"key_data":values.get("key_data",""),"background":values.get("background",""),"change_since_yesterday":values.get("change",item.get("change_since_yesterday","")),"next":values.get("next",""),"connection":values.get("connection",""),"memory_hook":values.get("memory",""),"vocabulary":values.get("vocabulary","")}

def _person_context(name,text):
    key=re.sub(r"[^a-z ]","",str(name).lower()).strip()
    profiles={"donald trump":"Donald Trump — President of the United States (45th and 47th); head of the U.S. executive branch and commander-in-chief.","trump":"Donald Trump — President of the United States (45th and 47th); head of the U.S. executive branch and commander-in-chief.","xi jinping":"Xi Jinping — President of China, General Secretary of the Communist Party of China and Chairman of the Central Military Commission; China's top political leader.","xi":"Xi Jinping — President of China, General Secretary of the Communist Party of China and Chairman of the Central Military Commission; China's top political leader."}
    return profiles.get(key,"")

def _explicit_who(item):
    headline=str(item.get("headline","") or ""); summary=str(item.get("summary","") or ""); text=f"{headline} {summary}".strip()
    # Known organizations/institutions must never be emitted as a person.
    org_phrases={
        "supreme court","high court","supreme court of india","election commission",
        "election commission of india","white house","parliament","government",
        "bigg boss","asian games","techcrunch","bbc","cnn","openai","meta",
        "nasa","isro","cbse","united nations","world health organization"
    }
    def valid_name(name):
        n=re.sub(r"\\s+"," ",name.strip(" .,;:-"))
        if not n or len(n.split())<2: return False
        low=n.lower()
        if any(p==low or p in low for p in org_phrases): return False
        if any(w in low.split() for w in {"court","commission","government","house","parliament","agency","board","games","company","ministerial"}): return False
        return bool(re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\\s+[A-Z][A-Za-z.'-]+){1,3}",n))
    if re.search(r"\\b(?:donald\\s+)?trump\\b",text,re.I): return _person_context("donald trump",text)
    if re.search(r"\\bxi\\s+jinping\\b|\\bxi\\b",text,re.I): return _person_context("xi jinping",text)
    if re.search(r"\\b(?:PM|Prime Minister)\\s+Modi\\b",text,re.I): return "Narendra Modi — Prime Minister of India"
    role_patterns=(
        r"\\b(?:CEC|Chief Election Commissioner)\\s+([A-Z][A-Za-z.'-]+(?:\\s+[A-Z][A-Za-z.'-]+){1,3})",
        r"\\b(?:IAS|IPS|IFS)\\s+officer\\s+([A-Z][A-Za-z.'-]+(?:\\s+[A-Za-z.'-]+){1,3})",
        r"\\b(?:President|Prime Minister|PM|Chief Minister|CM|Minister|Justice|Judge|Professor|CEO|Founder|Secretary General)\\s+([A-Z][A-Za-z.'-]+(?:\\s+[A-Za-z.'-]+){0,3})",
    )
    for pattern in role_patterns:
        m=re.search(pattern,headline)
        if m and valid_name(m.group(1)): return m.group(1).strip(" .,")
    # Prefer explicit named people in the headline, avoiding title/org phrases.
    for m in re.finditer(r"\\b[A-Z][A-Za-z.'-]+(?:\\s+[A-Z][A-Za-z.'-]+){1,3}\\b",headline):
        name=m.group(0)
        if valid_name(name):
            return name.strip(" .,")
    for pattern in (
        r"\\b(?:says|said|asks|asked|warns|warned|according to|by)\\s+([A-Z][A-Za-z.'-]+(?:\\s+[A-Za-z.'-]+){1,3})\\b",
        r"\\b(?:the\\s+)?(?:27-year-old|\\d{2}-year-old)\\s+([A-Z][A-Za-z.'-]+(?:\\s+[A-Za-z.'-]+)+)"
    ):
        m=re.search(pattern,text)
        if m and valid_name(m.group(1)): return m.group(1).strip(" .,")
    return ""

