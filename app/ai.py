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
    named_a={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(a))}
    named_b={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(b))}
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

def select_stories(articles,top_n=None,excluded_headlines=None):
    excluded=list(excluded_headlines or []); ranked=[]; seen=[]
    for a in articles:
        title=str(a.get("title","")).strip()
        if not title or not a.get("url"): continue
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
    ]
    # High-signal anchors can identify a recurring family even when a
    # headline omits one of the usual terms. This is important for CEC/ECI/SIR
    # coverage where different outlets describe the same controversy differently.
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
        key=_event_family_key(item.get("headline",""))
        if key:
            count=family_counts.get(key,0)
            if count>=max_family:
                continue
            family_counts[key]=count+1
        else:
            same=[x for x in selected if _same_event_family(item,x)]
            if same:
                if len(same)>=max_family or not all(_genuinely_new_development(item,x) for x in same):
                    continue
            selected.append(item)
            continue
        selected.append(item)
    return selected

def rerank_stories(stories,research=None):
    research=research or {}; scored=[]
    for s in stories:
        r=research.get(s.get("story_id"),{}) or {}
        conf=float(r.get("confidence",0) or 0); indep=int(r.get("independent_sources",0) or 0); importance=float(s.get("importance",0) or 0)
        novelty=100.0 if not r.get("historical") else 65.0; verification=r.get("verification","unverified")
        if verification=="unverified": conf=min(conf,50)
        verification_bonus={"multi-source":12,"official-source":9,"single-source":-4}.get(verification,0)
        source_diversity=min(8,indep*2)
        published_importance=importance
        if verification=="single-source": published_importance=min(published_importance,72.0)
        elif verification=="unverified": published_importance=min(published_importance,68.0)
        item=dict(s); item["importance"]=round(published_importance,1)
        final=(0.56*published_importance + 0.24*conf + 0.08*min(100,50+indep*15) + 0.06*novelty + verification_bonus + source_diversity)
        item["ranking_score"]=round(final,1); scored.append((final,item))

    india=[x for x in scored if str(x[1].get("region","")).lower()=="india" and float(x[1].get("region_confidence",0) or 0)>=float(os.getenv("NEWS_INDIA_MIN_REGION_CONFIDENCE","0.60"))]
    world=[x for x in scored if str(x[1].get("region","")).lower()=="world"]
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
    """Require a real event match before importing facts from another article."""
    base=_similar(a,b)
    wa,wb=_content_tokens(a),_content_tokens(b)
    common=wa&wb
    named_a={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(a))}
    named_b={x.lower() for x in re.findall(r"\b[A-Z][A-Za-z.'-]{2,}\b",str(b))}
    named=named_a&named_b
    event_terms={"breach","hack","attack","arrest","ban","blocked","access","symbol","logo","launch","launched","deal","trade","truce","visit","arrives","arrived","glasses","intelligence","result","results","election","court","judge","verdict","trial","crash","earthquake","cyclone","fire","flood","death","dies","killed","injured","strike","protest","approval","approved","agreement","summit","sanctions","dispute","ruling","order"}
    event_overlap=common&event_terms
    if base>=0.52: return base
    if len(named)>=1 and len(event_overlap)>=1 and len(common)>=2: return 0.55
    if len(named)>=2 and len(common)>=2: return 0.55
    return base

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
    if who and not re.search(r"[A-Z][A-Za-z.'-]{2,}",who): who=""
    if who and any(t.lower().strip(".,") in bad_name_tokens for t in who.split()): who=""
    if who and len(who.split())==1 and who.lower() in {"the","meanwhile","monday","june","burnham"}: who=""
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
    named_profiles=[]
    if re.search(r"\b(?:donald\s+)?trump\b",text,re.I): named_profiles.append(_person_context("donald trump",text))
    if re.search(r"\bxi\s+jinping\b|\bxi\b",text,re.I): named_profiles.append(_person_context("xi jinping",text))
    named_profiles=[x for x in named_profiles if x]
    if named_profiles: return " ".join(dict.fromkeys(named_profiles))
    role_patterns=(
        r"\b(?:CEC|Chief Election Commissioner)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})",
        r"\b(?:President|Prime Minister|PM|Chief Minister|CM|Minister|Justice|Judge|Professor|CEO|Founder|Secretary General|president|minister)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,3})",
        r":\s*([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s*$",
    )
    for pattern in role_patterns:
        m=re.search(pattern,headline)
        if m: return m.group(1).strip(" .,")
    role_name_patterns=((r"\b(?:chinese|indian|american|british|japanese|korean)?\s*(?:street\s+)?dancer\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)","dancer"),(r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+)+),\s+(?:the\s+)?(?:art\s+director|director|founder|chief executive officer|ceo|commerciali[sz]ation lead|lead engineer)",""),(r"\b(?:founder|director|ceo|president|minister|prime minister|chief minister|leader of the opposition)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)",""))
    for pattern,fixed_role in role_name_patterns:
        m=re.search(pattern,text)
        if m:
            name=m.group(1).strip(" .,"); return f"{name} — {fixed_role}" if fixed_role else name
    m=re.search(r"\b(?:says|said|asks|asked|warns|warned|according to|by)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\b",text)
    if m: return m.group(1).strip(" .,")
    descriptor_patterns=(r"\b(?:the\s+)?(?:27-year-old|\d{2}-year-old)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)",r"\b(?:native|performer|engineer|artist|actor|actress|dancer)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+)+)")
    for pattern in descriptor_patterns:
        m=re.search(pattern,text)
        if m: return m.group(1).strip(" .,")
    return ""

def _evidence_articles(item):
    primary={"title":item.get("headline",""),"source":item.get("source",""),"url":item.get("url",""),"published":item.get("published",""),"summary":item.get("summary","")}
    return [primary]+[x for x in (item.get("related_articles") or []) if x.get("summary") or x.get("title")]

def _extract_context(item):
    articles=_evidence_articles(item); primary=articles[:1]; secondary=articles[1:]
    def scan(article_list):
        when=""; where=""
        date_patterns=(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?",r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",r"\b(?:today|yesterday|tonight|this morning|this evening)\b")
        location_patterns=(r"\b(?:at|in|from|near)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,4})(?=\s+(?:on|after|before|where|which|has|have|was|were|is|are|said|according|headquarters|headquartered)\b|[.,;:]|$)",r"\b(?:headquarters|headquartered)\s+(?:in|at)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,4})",r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,4}),\s+(?:India|China|Japan|the United States|UK|Britain|California|New York)\b")
        texts=[str(x.get("title","") or "")+" "+str(x.get("summary","") or "") for x in article_list]
        for article_text in texts:
            for pattern in date_patterns:
                m=re.search(pattern,article_text,re.I)
                if m: when=m.group(0); break
            if when: break
        candidates=[]
        for article_text in texts:
            for pattern in location_patterns: candidates += [m.group(1).strip(" .,") for m in re.finditer(pattern,article_text)]
        candidates=[x for x in candidates if x and len(x.split())<=5 and x.lower() not in {"the social media giant","the company"}]
        if candidates:
            counts={x:candidates.count(x) for x in set(candidates)}; where=max(candidates,key=lambda x:(counts[x],-len(x.split())))
        return when,where
    # Related stories may corroborate the event but can describe a different
    # action, place, or scheduled date. Keep WHEN/WHERE tied to the primary item.
    when,where=scan(primary)
    return when,where

def _sentence_list(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+",str(text or "")) if x.strip()]

def _fallback_how(item):
    text=str(item.get("summary","") or "").strip()
    # HOW must describe a mechanism, not merely chronology.
    patterns=(r"\b(?:by|through|using|via)\s+([^.;]{20,220})",r"\b(?:under|as part of)\s+(?:a|an|the)\s+([^.;]{20,220})")
    for pattern in patterns:
        m=re.search(pattern,text,re.I)
        if m:
            value=m.group(1).strip(" .,:;")
            if not re.match(r"^(?:after|following|during|before|when|while)\b",value,re.I) and len(value.split())>=4 and _similar(value,text)<0.60:
                return value[:400]
    return ""

def _fallback_key_data(item):
    primary_text=str(item.get("summary","") or "")
    text=primary_text
    patterns=(r"(?:up to|starting at|weighs?|weight|battery(?: life)?|ships?|shipping|price|cost|capacity|range|duration|hours?|minutes?|percent|%|frames?|models?|combinations?)\s*(?:of\s*)?(?:₹|\$|€|£)?\d+(?:[.,]\d+)*(?:\s*(?:million|billion|crore|lakh|thousand|bn|mn|hours?|minutes?|g|kg|GB|TB|%))?",r"(?:₹|\$|€|£)\s*\d+(?:[.,]\d+)*(?:\s*(?:million|billion))?",r"\b\d+(?:[.,]\d+)*\s*(?:million|billion|crore|lakh|thousand|hours?|minutes?|g|kg|GB|TB|%)\b")
    values=[]
    for pattern in patterns:
        for m in re.finditer(pattern,text,re.I):
            value=" ".join(m.group(0).split())
            if value not in values: values.append(value)
    return "; ".join(values[:8])

def _fallback_why(item):
    text=str(item.get("summary","") or "").strip()
    for pattern in (r"(?:because|due to|in response to|to address|to reduce|to improve|to prevent) ([^.]{25,240})[.]", r"(?:the move|decision|action) (?:came|comes) (?:after|amid) ([^.]{25,240})[.]"):
        m=re.search(pattern,text,re.I)
        if m:
            value=m.group(1).strip().rstrip(".")
            if len(value.split())>=3: return value[:400]
    return ""

def _fallback_background(item):
    primary=str(item.get("summary","") or "").strip()
    if not primary: return ""
    sentences=_sentence_list(primary)
    if len(sentences)<2: return ""
    first=sentences[0]
    context=re.compile(r"\b(?:previously|earlier|historically|history|since|in \d{4}|last year|months earlier|had been|has been|was first|founded|launched in|for years|longstanding)\b",re.I)
    for sentence in sentences[1:]:
        if len(sentence)>=35 and _similar(sentence,first)<0.70 and context.search(sentence):
            return sentence[:500]
    return ""

def _fallback_impact(item):
    text=str(item.get("summary","") or "").strip()
    for pattern in (r"\b(?:could|may|will|would|is expected to|are expected to)\s+([^.;]{25,260})",
                    r"\b(?:impact|impacts|affect|affects|risk|risks|consequence|consequences)\s+(?:of|for|on)?\s*([^.;]{25,260})"):
        m=re.search(pattern,text,re.I)
        if m:
            value=m.group(1).strip(" .,:;")
            if len(value.split())>=5 and _similar(value,text)<0.65:
                return value[:450]
    return ""

def _fallback_next(item):
    text=str(item.get("summary","") or "").strip()
    for pattern in (r"\b(?:next|will now|plans to|plan to|is expected to|are expected to|will be)\s+([^.;]{20,240})",
                    r"\b(?:on|by)\s+([^.;]{10,80})\s+(?:the company|officials|government|court|police)\b"):
        m=re.search(pattern,text,re.I)
        if m:
            value=m.group(0).strip(" .,:;")
            if len(value.split())>=4: return value[:400]
    return ""

def _fallback_connection(item):
    related=item.get("related_articles") or []
    if not related: return ""
    primary_tokens=_content_tokens(item.get("headline",""))
    for r in related:
        title=str(r.get("title","") or "").strip()
        if title and _similar(title,item.get("headline",""))<0.72:
            return "Related development: "+title[:260]
    return ""

def _fallback_memory(item):
    historical=(item.get("verification") or {}).get("historical") or []
    if historical:
        h=historical[0]
        title=str(h.get("title","") or "").strip()
        if title: return f"Prior: {h.get('date','prior')} — {title}"[:300]
    return ""

def _fallback(item):
    summary=item.get("summary") or item.get("headline") or ""; who=_explicit_who(item); text=f"{item.get('headline','')} {item.get('summary','')}".strip(); headline=str(item.get("headline",summary)); when,where=_extract_context(item)
    item=dict(item); item.pop("_event_text",None)
    memory_hook=_fallback_memory(item)
    return {**item,"what":summary[:500],"who":who,"who_detail":_person_context(who,text) if who else "","how":_fallback_how(item),"key_data":_fallback_key_data(item),"when":when,"where":where,"why":_fallback_why(item),"why_important":_fallback_impact(item),"background":_fallback_background(item),"change_since_yesterday":item.get("change_since_yesterday",""),"next":_fallback_next(item),"connection":_fallback_connection(item),"memory_hook":memory_hook,"vocabulary":"","ai_generated":False}

def _one(item,today):
    prompt=f"""Today: {today}
Use ONLY the supplied evidence to enrich ONE news story. Core facts are already extracted deterministically.
Return EXACTLY 6 short lines:
WHO_DETAIL: ...
IMPACT: ...
BACKGROUND: ...
CHANGE: ...
CONNECTION: ...
NEXT: ...
WHO_DETAIL: for each important named person, give current role/position, relevant background and why they matter here.
IMPACT: concrete significance or consequences supported by the evidence.
BACKGROUND: only useful prior context supported by the supplied evidence or related articles.
CHANGE: what is newly different versus the prior timeline/evidence.
CONNECTION: a concrete link to another verified development in the supplied evidence.
NEXT: the most relevant expected/announced next step, or leave blank if unsupported.
Use corroborating related articles when the primary article does not contain enough detail. Prefer facts repeated or supported across multiple sources. Attribute conflicting claims instead of merging them. If a field remains unsupported after checking all supplied sources, leave it blank. Never write "Not stated in supplied sources". Never invent facts. No bullets or commentary.
Evidence: {json.dumps({
    "headline": item.get("headline",""),
    "source": item.get("source",""),
    "summary": str(item.get("summary","") or "")[:650],
    "related_articles": [
        {"title": x.get("title",""), "source": x.get("source",""), "summary": str(x.get("summary","") or "")[:500]}
        for x in (item.get("related_articles") or [])[:4]
    ],
    "verification": {
        "verification": (item.get("verification") or {}).get("verification",""),
        "independent_sources": (item.get("verification") or {}).get("independent_sources",0)
    }
},ensure_ascii=False)}"""
    result=_parse(_call_ollama(prompt,num_predict=int(os.getenv("AI_ENRICH_OUTPUT","120")),timeout=int(os.getenv("AI_TIMEOUT_SECONDS","25"))),item)
    explicit=_explicit_who(item); current=str(result.get("who","")).strip()
    if explicit and not current: result["who"]=explicit
    if explicit and not str(result.get("who_detail","")).strip(): result["who_detail"]=_person_context(explicit,item.get("headline",""))
    result.pop("_event_text",None)
    result["ai_generated"]=True; return result

def generate_briefing(selected,articles,previous,today,research=None):
    evidence=_evidence(selected,articles,research); stories=[]; budget=max(0,int(os.getenv("AI_STORY_BUDGET","8")))
    ai_candidates=[x for x in evidence if float(x.get("importance",0))>=float(os.getenv("AI_DEEP_IMPORTANCE","70"))]
    if len(ai_candidates)<budget: ai_candidates=evidence[:budget]
    ai_ids={x.get("story_id") for x in ai_candidates[:budget]}
    for item in evidence:
        if item.get("story_id") not in ai_ids: stories.append(_fallback(item)); continue
        try: stories.append(_one(item,today))
        except Exception as exc: print(f"[WARN] story generation failed: {exc}",flush=True); stories.append(_fallback(item))
    return {"top_stories":stories}

def generate(articles,previous,today,research=None): return generate_briefing(select_stories(articles),articles,previous,today,research)
def generate_text(prompt,system=SYSTEM): return _call_ollama(prompt,system=system)
def configured_model(): return _model_name()
