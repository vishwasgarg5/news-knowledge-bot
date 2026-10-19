from __future__ import annotations
from collections import Counter
from urllib.parse import urlparse
from .storage import outcome_is_mature

def _f(v, default=0.0):
    try: return float(v)
    except (TypeError,ValueError): return default

def adaptive_threshold(calibration, fallback=62.0):
    value=_f((calibration or {}).get("threshold"), fallback)
    return max(55.0,min(75.0,value))

def apply_adaptive_threshold(calibration, minimum=62.0):
    threshold=adaptive_threshold(calibration,minimum)
    # Never let historical noise lower the production gate below the safety floor.
    return max(float(minimum),threshold)

def diversify_stories(stories, max_total=10, india_target=5, world_target=5, max_per_source=2):
    rows=sorted(list(stories or []),key=lambda x:(-_f(x.get("ranking_score",x.get("importance",0))),-_f(x.get("importance",0))))
    selected=[]; used_events=set(); source_counts=Counter(); region_counts=Counter()
    def add(row):
        sid=str(row.get("story_id",""))
        event=str(row.get("event_id","") or sid)
        source=str(row.get("source","unknown")).strip().lower()
        host=urlparse(str(row.get("url","") or "")).netloc.lower().split(":")[0]
        if host.startswith("www."): host=host[4:]
        if host:
            aliases=(("bbc.co.uk","bbc"),("bbc.com","bbc"),("reuters.com","reuters"),("thehindu.com","the hindu"),("indianexpress.com","indian express"),("apnews.com","associated press"),("pib.gov.in","pib"),("rbi.org.in","reserve bank of india"))
            source=next((canonical for suffix,canonical in aliases if host==suffix or host.endswith("."+suffix)),host)
        if sid in {str(x.get("story_id","")) for x in selected} or event in used_events: return False
        if source_counts[source]>=max_per_source: return False
        selected.append(row); used_events.add(event); source_counts[source]+=1
        region_counts[str(row.get("region","world")).lower()]+=1
        return True
    # Reserve regional slots first, then fill remaining capacity by score.
    for region,target in (("india",int(india_target)),("world",int(world_target))):
        for row in rows:
            if len(selected)>=int(max_total) or region_counts[region]>=target: break
            if str(row.get("region","world")).lower()==region: add(row)
    for row in rows:
        if len(selected)>=int(max_total): break
        add(row)
    for i,row in enumerate(selected,1): row["final_rank"]=i
    return selected

def consolidate_event_families(stories):
    rows=list(stories or [])
    out=[]; families=set()
    for row in rows:
        family=str(row.get("event_family","") or row.get("event_id","") or row.get("story_id",""))
        if family and family in families: continue
        if family: families.add(family)
        out.append(row)
    return out

def learning_v3_snapshot(learning_rows):
    rows=list(learning_rows or [])
    labeled=[r for r in rows if outcome_is_mature(r) and str(r.get("outcome_score","")).strip() not in {"","None"}]
    if not labeled: return {"samples":0,"selected":0,"hit_rate":0.0,"false_positive_rate":0.0,"avg_outcome":0.0}
    selected=[r for r in labeled if str(r.get("selected","")).lower()=="true"]
    hits=[r for r in selected if _f(r.get("outcome_score"))>=0.5]
    fps=[r for r in selected if str(r.get("false_positive","")).lower()=="true"]
    return {"samples":len(labeled),"selected":len(selected),"hit_rate":round(len(hits)/max(1,len(selected)),3),"false_positive_rate":round(len(fps)/max(1,len(selected)),3),"avg_outcome":round(sum(_f(r.get("outcome_score")) for r in labeled)/len(labeled),3)}

def source_fallback_plan(source_health, minimum_quality=0.15):
    weak=[name for name,info in (source_health or {}).items() if _f(info.get("quality_rate"))<minimum_quality]
    return {"weak_sources":weak,"fallback_required":bool(weak),"healthy_sources":max(0,len(source_health or {})-len(weak))}

def breaking_fast_lane(stories, limit=2):
    rows=sorted(list(stories or []),key=lambda x:_f(x.get("breaking_score")),reverse=True)
    return [x for x in rows if _f(x.get("breaking_score"))>=50][:int(limit)]

def calibrate_confidence(story, research):
    """Apply conservative evidence-tier caps; never inflate a publisher's raw confidence.

    Verification already incorporates independent-source counts. Adding another
    source-count bonus here double-counted the same evidence and routinely
    saturated unrelated stories at 100%.
    """
    v=(research or {}).get(story.get("story_id"),{})
    raw=max(0.0,min(100.0,_f(v.get("confidence"),50)))
    verification=str(v.get("verification","unverified"))
    caps={
        "official-source":98.0,
        "multi-source":95.0,
        "multi-report":75.0,
        "single-source":60.0,
        "unverified":40.0,
    }
    cap=caps.get(verification,50.0)
    if not v.get("primary_fresh",True):
        cap=min(cap,60.0)
    if v.get("contradiction_flag"):
        cap=min(cap,50.0)
    return round(min(raw,cap),1)

def adaptive_personalization(preferences, learning_snapshot):
    prefs=dict(preferences or {})
    rate=_f((learning_snapshot or {}).get("hit_rate"))
    # Small bounded adjustment: successful historical selections strengthen
    # existing category/region preferences without inventing new preferences.
    if rate>=0.65: prefs["category_weight"]=min(12,int(prefs.get("category_weight",6))+1)
    elif rate<0.35: prefs["category_weight"]=max(4,int(prefs.get("category_weight",6))-1)
    return prefs
