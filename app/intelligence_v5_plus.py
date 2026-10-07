from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math,re

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def tokens(text):
    return set(re.findall(r"[a-z][a-z0-9&.-]{2,}",str(text or "").lower()))

def entity_extract(stories):
    people=set(); companies=set(); places=set(); topics=Counter()
    company_hints={"ltd","limited","inc","corp","bank","steel","motors","energy","industries","group"}
    for s in stories or []:
        text=" ".join(str(s.get(k,"")) for k in ("headline","summary","background"))
        caps=re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,}){0,2}",text)
        for x in caps:
            x=x.strip()
            if x.lower() in {"The","India","World","News"}: continue
            if any(h in x.lower() for h in company_hints): companies.add(x)
            else: topics[x.lower()]+=1
        for k,target in (("people",people),("companies",companies),("places",places)):
            vals=s.get(k,[])
            if isinstance(vals,list):
                target.update(str(v).strip() for v in vals if str(v).strip())
    return {"people":sorted(people)[:100],"companies":sorted(companies)[:100],"places":sorted(places)[:100],"topics":dict(topics.most_common(50))}

def entity_profiles(stories,history):
    current=entity_extract(stories); counts=Counter()
    for r in history or []:
        for e in tokens(r.get("headline",r.get("title",""))): counts[e]+=1
    profiles=[]
    for kind,vals in current.items():
        if kind=="topics":
            vals=list(vals)
        for name in vals:
            n=vals[name] if isinstance(vals,dict) else 1
            profiles.append({"entity":str(name),"type":kind.rstrip("s"),"current_mentions":n,"historical_mentions":counts.get(str(name).lower(),0)})
    return profiles[:200]

def event_key(story):
    return "|".join(sorted(tokens(story.get("headline",story.get("title",""))) )[:12])

def cluster_events(stories,threshold=.28):
    clusters=[]
    for s in stories or []:
        t=tokens(s.get("headline",s.get("title",""))); best=None; bs=0
        for i,c in enumerate(clusters):
            ct=c["_tokens"]; sim=len(t&ct)/max(1,len(t|ct))
            if sim>bs: bs=sim; best=i
        if best is not None and bs>=threshold: clusters[best]["stories"].append(s); clusters[best]["_tokens"]|=t
        else: clusters.append({"stories":[s],"_tokens":set(t)})
    out=[]
    for i,c in enumerate(clusters):
        ss=c["stories"]; head=max(ss,key=lambda x:_f(x.get("importance",0)))
        out.append({"event_id":event_key(head) or f"event-{i}","headline":head.get("headline",head.get("title","")),"story_count":len(ss),"sources":sorted({str(x.get("source","unknown")) for x in ss}),"stories":ss})
    return out

def event_evolution(current,timeline):
    old=list(timeline or [])
    out=[]
    for e in cluster_events(current):
        head=e["headline"]; tt=tokens(head)
        related=[r for r in old if len(tt & tokens(r.get("headline","")))/max(1,len(tt|tokens(r.get("headline",""))))>=.25]
        status="NEW" if not related else ("DEVELOPING" if len(related)>=1 else "NEW")
        if e["story_count"]>=3: status="CONFIRMED" if len(e["sources"])>=2 else "DEVELOPING"
        out.append({k:v for k,v in e.items() if k!="_tokens"} | {"status":status,"history_count":len(related)})
    return out

def impact_outcome_learning(stories,learning_rows):
    labels=[r for r in learning_rows or [] if str(r.get("outcome_score","")).strip()]
    rates={}
    for level in ("HIGH","MEDIUM","LOW"):
        xs=[_f(r.get("outcome_score")) for r in labels if str(r.get("impact_level","")).upper()==level]
        rates[level]=round(sum(x>=.5 for x in xs)/len(xs),3) if xs else None
    return {"samples":len(labels),"positive_rate":round(sum(_f(r.get("outcome_score"))>=.5 for r in labels)/max(1,len(labels)),3),"by_level":rates}

def apply_impact_calibration(stories,learning_rows):
    stats=impact_outcome_learning(stories,learning_rows)
    base={"HIGH":.75,"MEDIUM":.60,"LOW":.45}
    for s in stories or []:
        level=str((s.get("impact") or {}).get("level","LOW"))
        learned=stats["by_level"].get(level)
        if learned is not None:
            s["impact"]["confidence"]=round(.5*float(s["impact"].get("confidence",.5))+.5*learned,3)
            s["impact"]["learned_rate"]=learned
        else:
            s.setdefault("impact", {})
            s["impact"]["learned_rate"]=base[level]
            s["impact"].setdefault("confidence", base[level])
    return stories,stats

def similar_event_engine(story,history,limit=8):
    target=tokens(story.get("headline",story.get("title","")))
    rows=[]
    for r in history or []:
        rt=tokens(r.get("headline",r.get("title",""))); sim=len(target&rt)/max(1,len(target|rt))
        if sim>=.12: rows.append((sim,r))
    rows.sort(reverse=True,key=lambda x:x[0])
    return [{"similarity":round(x,3),"date":r.get("date",r.get("run_date")),"headline":r.get("headline",r.get("title","")),"outcome_score":r.get("outcome_score")} for x,r in rows[:limit]]

def news_market_correlation(stories,market_rows=None):
    market_rows=market_rows or []
    out=[]
    for s in stories or []:
        event=s.get("event_id",event_key(s)); impact=(s.get("impact") or {}).get("direction","neutral")
        matches=[r for r in market_rows if str(r.get("event_id",""))==str(event)]
        moves=[_f(r.get("return",r.get("change_pct"))) for r in matches]
        out.append({"event_id":event,"direction":impact,"market_samples":len(moves),"avg_move":round(sum(moves)/len(moves),3) if moves else None})
    return out

def source_event_reliability(stories):
    m=defaultdict(lambda:{"n":0,"verified":0,"high_impact":0})
    for s in stories or []:
        src=str(s.get("source","unknown")); x=m[src]; x["n"]+=1
        x["verified"]+=int(str(s.get("verification_level",s.get("verification",""))).lower() in {"multi-source","multi-report","official","strong"})
        x["high_impact"]+=int((s.get("impact") or {}).get("level")=="HIGH")
    for x in m.values(): x["verification_rate"]=round(x["verified"]/max(1,x["n"]),3)
    return dict(m)

def advanced_feedback(feedback_rows):
    c=Counter(str(r.get("feedback","")).lower() for r in feedback_rows or [])
    pos=c["positive"]+c["useful"]+c["good"]; neg=c["negative"]+c["wrong"]+c["bad"]
    return {"positive":pos,"negative":neg,"net":pos-neg,"signal":round((pos-neg)/max(1,pos+neg),3) if pos+neg else 0.0}

def scorecard(stories,diagnostics):
    total=len(stories); impacts=Counter((s.get("impact") or {}).get("level","LOW") for s in stories)
    return {"stories":total,"high_impact":impacts["HIGH"],"medium_impact":impacts["MEDIUM"],"low_impact":impacts["LOW"],"verified":sum(1 for s in stories if str(s.get("verification_level",s.get("verification",""))).lower() in {"multi-source","multi-report","official","strong"}),"early_signals":sum(bool(s.get("early_signal")) for s in stories),"health":diagnostics.get("health","UNKNOWN")}

def personalized_feed(stories,preferences):
    prefs=preferences or {}; terms=set()
    for k in ("topics","categories","watchlist","keywords"):
        v=prefs.get(k,[])
        terms.update(str(x).lower() for x in v if isinstance(v,list))
    out=[]
    for s in stories or []:
        text=(str(s.get("headline",""))+" "+str(s.get("category",""))).lower()
        match=sum(1 for t in terms if t and t in text)
        x=dict(s); x["personalization_score"]=round(_f(s.get("importance",0))+match*8,2); x["preference_matches"]=match; out.append(x)
    return sorted(out,key=lambda x:x["personalization_score"],reverse=True)

def alert_candidates(stories,threshold=78):
    return [s for s in stories or [] if _f((s.get("impact") or {}).get("score"))>=threshold and _f(s.get("confidence",(s.get("impact") or {}).get("confidence",0))*100)>=55]

def trend_report(stories,previous=None):
    previous=previous or []
    cur=Counter(str(s.get("category","unknown")) for s in stories); old=Counter(str(s.get("category","unknown")) for s in previous)
    return [{"category":k,"current":v,"previous":old.get(k,0),"delta":v-old.get(k,0)} for k,v in cur.most_common()]

def answer_news_question(question,stories,history):
    q=tokens(question); scored=[]
    for s in stories or []:
        t=tokens(s.get("headline",s.get("title",""))+" "+s.get("summary",""))
        scored.append((len(q&t)/max(1,len(q)),s))
    scored.sort(reverse=True,key=lambda x:x[0])
    hits=[s for x,s in scored[:3] if x>0]
    if not hits: return {"answer":"No matching story found in the current intelligence memory.","stories":[]}
    lines=[f"{s.get('headline','')} — impact {(s.get('impact') or {}).get('level','UNKNOWN')}, status {s.get('lifecycle_v2',s.get('event_status','UNKNOWN'))}." for s in hits]
    return {"answer":" ".join(lines),"stories":[s.get("headline") for s in hits]}

def knowledge_graph(stories):
    nodes={}; edges=[]
    for s in stories or []:
        eid=s.get("event_id") or event_key(s); nodes[eid]={"type":"event","label":s.get("headline","")}
        for e in entity_extract([s])["companies"]+entity_extract([s])["people"]+entity_extract([s])["places"]:
            key=f"entity:{e.lower()}"; nodes[key]={"type":"entity","label":e}; edges.append({"from":eid,"to":key,"type":"mentions"})
    return {"nodes":list(nodes.values()),"edges":edges[:500]}

def contradiction_scan(stories):
    out=[]
    positive_words={"approve","support","rise","gain","growth","increase"}
    negative_words={"ban","reject","fall","loss","decline","crisis"}
    for s in stories or []:
        text=str(s.get("headline","")).lower(); pos=sum(w in text for w in positive_words); neg=sum(w in text for w in negative_words)
        if pos and neg: out.append({"headline":s.get("headline",""),"reason":"mixed directional language"})
        if (s.get("verification") or {}).get("contradiction_flag"): out.append({"headline":s.get("headline",""),"reason":"verification contradiction"})
    return out

def missing_evidence(stories):
    gaps=[]
    for s in stories or []:
        missing=[]
        if not s.get("url"): missing.append("source_url")
        if not s.get("source"): missing.append("source")
        if not s.get("summary"): missing.append("summary")
        if not (s.get("verification") or {}).get("sources") and not s.get("source_count"): missing.append("independent_source_count")
        if missing:gaps.append({"headline":s.get("headline",""),"missing":missing})
    return gaps

def autonomous_research(stories,similarity_history=None):
    queue=[]
    for s in stories or []:
        impact=(s.get("impact") or {})
        priority=impact.get("score",0)+(_f(s.get("momentum_score"))*.25)
        if priority>=65:
            queue.append({"headline":s.get("headline",""),"priority":round(priority,1),"tasks":["verify primary source","find independent confirmation","retrieve historical analogue"]})
    return sorted(queue,key=lambda x:x["priority"],reverse=True)[:15]

def research_report(stories,queue):
    return {"generated_at":datetime.utcnow().isoformat()+"Z","sections":[{"headline":s["headline"],"priority":s["priority"],"finding":"Requires source verification, independent confirmation and historical comparison."} for s in queue]}

def anomaly_detection(stories,history):
    cur=Counter(str(s.get("category","unknown")) for s in stories); old=Counter(str(r.get("category","unknown")) for r in history or [])
    n=max(1,len(history)); out=[]
    for k,v in cur.items():
        baseline=old[k]/n
        if v>=3 and baseline<.08: out.append({"category":k,"current":v,"baseline_rate":round(baseline,3),"anomaly":True})
    return out

def weekly_report(stories,history):
    return {"top_events":[s.get("headline","") for s in sorted(stories,key=lambda x:_f(x.get("importance",0)),reverse=True)[:10]],"history_size":len(history or []),"anomalies":anomaly_detection(stories,history)}

def run_v5_plus(stories,history,learning_rows,feedback_rows,preferences,diagnostics,market_rows=None):
    clusters=cluster_events(stories); enriched=[]
    for s in stories:
        x=dict(s); x["event_id"]=x.get("event_id") or event_key(x)
        x["similar_historical_events"]=similar_event_engine(x,history)
        enriched.append(x)
    enriched,impact_stats=apply_impact_calibration(enriched,learning_rows)
    entities=entity_extract(enriched)
    profiles=entity_profiles(enriched,history)
    evolution=event_evolution(enriched,history)
    graph=knowledge_graph(enriched)
    return {"stories":enriched,"clusters":clusters,"entities":entities,"entity_profiles":profiles,"event_evolution":evolution,"impact_learning":impact_stats,"market_correlation":news_market_correlation(enriched,market_rows),"source_reliability":source_event_reliability(enriched),"feedback":advanced_feedback(feedback_rows),"scorecard":scorecard(enriched,diagnostics),"personalized_feed":personalized_feed(enriched,preferences),"alerts":alert_candidates(enriched),"trend_report":trend_report(enriched,history),"knowledge_graph":graph,"contradictions":contradiction_scan(enriched),"evidence_gaps":missing_evidence(enriched),"research_queue":autonomous_research(enriched),"weekly_report":weekly_report(enriched,history)}
