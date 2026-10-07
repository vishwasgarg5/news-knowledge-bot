from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date
from math import sqrt
import re

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def _tokens(text):
    return set(re.findall(r"[A-Za-z][A-Za-z0-9&.-]{2,}",str(text or "").lower()))

def extract_entities(stories):
    people=set(); companies=set(); places=set(); topics=Counter()
    stop={"the","and","for","with","from","this","that","india","world","news"}
    for s in stories or []:
        text=" ".join(str(s.get(k,"")) for k in ("headline","title","summary"))
        words=[w for w in re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}\b",text)]
        for w in words:
            if w.lower() not in stop: topics[w.lower()]+=1
        for key,target in (("people",people),("companies",companies),("places",places)):
            for v in s.get(key,[]) if isinstance(s.get(key),list) else []: target.add(str(v))
    return {"people":sorted(people),"companies":sorted(companies),"places":sorted(places),
            "topics":dict(topics.most_common(30))}

def classify_impact(story):
    text=" ".join(str(story.get(k,"")) for k in ("headline","summary")).lower()
    high=["war","sanction","rate","election","ban","crisis","merger","acquisition","default","tariff","earthquake","attack"]
    medium=["investment","earnings","policy","launch","approval","deal","growth","inflation","regulation"]
    hits=sum(x in text for x in high)
    mh=sum(x in text for x in medium)
    level="HIGH" if hits>=1 else "MEDIUM" if mh>=1 else "LOW"
    direction="negative" if any(x in text for x in ["loss","fall","decline","ban","crisis","attack","default"]) else "positive" if any(x in text for x in ["growth","gain","investment","approval","deal","launch"]) else "neutral"
    return {"level":level,"direction":direction,"score":min(100,40+hits*18+mh*8),"confidence":round(min(0.95,0.45+0.08*(hits+mh)),2)}

def consequence_graph(story):
    impact=classify_impact(story)
    return {"event":story.get("headline",story.get("title","")),"impact":impact,
            "immediate":["Monitor official confirmation and affected entities"],
            "second_order":["Monitor related sectors, suppliers, competitors and policy response"],
            "watch_next":["New official statements","Independent confirmation","Price/economic data if relevant"]}

def event_momentum(stories):
    out=[]
    for s in stories or []:
        score=min(100,20+10*int(s.get("source_count",s.get("sources_count",1)) or 1)+_f(s.get("breaking_score"))*.35+_f(s.get("trend_score"))*.35)
        x=dict(s); x["momentum_score"]=round(score,1)
        x["early_signal"]=score>=70
        out.append(x)
    return sorted(out,key=lambda x:_f(x.get("momentum_score")),reverse=True)

def lifecycle_v2(story):
    status=str(story.get("lifecycle",story.get("status","NEW"))).upper()
    if status not in {"NEW","EMERGING","BREAKING","DEVELOPING","CONFIRMED","ESCALATING","RESOLVED"}: status="NEW"
    return status

def similar_events(story,history,limit=5):
    target=_tokens(" ".join(str(story.get(k,"")) for k in ("headline","summary")))
    scored=[]
    for r in history or []:
        toks=_tokens(" ".join(str(r.get(k,"")) for k in ("headline","summary","title")))
        if not toks: continue
        sim=len(target&toks)/max(1,len(target|toks))
        if sim>0: scored.append((sim,r))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [{"similarity":round(s,3),"date":r.get("date",r.get("run_date")),"headline":r.get("headline",r.get("title","")),
             "outcome_score":r.get("outcome_score")} for s,r in scored[:limit]]

def source_event_matrix(stories):
    m=defaultdict(lambda:{"stories":0,"high_impact":0,"verified":0})
    for s in stories or []:
        key=str(s.get("source","unknown")).lower()
        m[key]["stories"]+=1
        m[key]["high_impact"]+=int(classify_impact(s)["level"]=="HIGH")
        m[key]["verified"]+=int(str(s.get("verification_level",s.get("verification",""))).lower() in {"multi-source","multi-report","strong"})
    return dict(m)

def intelligence_scorecard(stories,stats):
    total=len(stories or [])
    high=sum(classify_impact(s)["level"]=="HIGH" for s in stories or [])
    verified=sum(str(s.get("verification_level",s.get("verification",""))).lower() in {"multi-source","multi-report","strong"} for s in stories or [])
    return {"stories":total,"high_impact":high,"verified":verified,"verification_rate":round(verified/max(1,total),3),
            "early_signals":sum(event_momentum(stories)[i].get("early_signal",False) for i in range(len(stories or []))),
            "health":stats.get("health","UNKNOWN")}

def cross_event_links(stories):
    links=[]
    for i,a in enumerate(stories or []):
        for b in (stories or [])[i+1:]:
            ta=_tokens(a.get("headline",a.get("title",""))); tb=_tokens(b.get("headline",b.get("title","")))
            overlap=len(ta&tb)
            if overlap>=2: links.append({"a":a.get("headline"),"b":b.get("headline"),"strength":overlap})
    return links[:20]

def autonomous_research_queue(stories):
    return [{"headline":s.get("headline",s.get("title","")),"priority":classify_impact(s)["score"],
             "reason":"high impact or emerging signal"} for s in event_momentum(stories) if classify_impact(s)["level"]=="HIGH" or s.get("early_signal")][:10]

def intelligence_v5(stories,history,stats):
    enriched=[]
    for s in stories or []:
        x=dict(s); x["impact"]=classify_impact(x); x["consequences"]=consequence_graph(x)
        x["lifecycle_v2"]=lifecycle_v2(x); x["similar_events"]=similar_events(x,history)
        enriched.append(x)
    momentum=event_momentum(enriched)
    return {"stories":momentum,"entities":extract_entities(momentum),"source_event_matrix":source_event_matrix(momentum),
            "scorecard":intelligence_scorecard(momentum,stats),"cross_event_links":cross_event_links(momentum),
            "research_queue":autonomous_research_queue(momentum)}
