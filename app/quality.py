from __future__ import annotations
from collections import Counter,defaultdict

def _f(v, default=0.0):
    try: return float(v)
    except (TypeError,ValueError): return default

def _tokens(text):
    import re
    return set(re.findall(r"[a-z]{4,}", str(text or "").lower()))

def _similar(a,b):
    x,y=_tokens(a),_tokens(b)
    return len(x&y)/max(1,len(x|y))

def prepare_candidates(candidates, history=None):
    """Add novelty, momentum, source diversity and coverage-gap signals."""
    history=list(history or [])
    old_titles=[str(x.get("headline","")) for x in history]
    seen_categories=Counter(str(x.get("category","other")).lower() for x in history[-500:])
    source_counts=Counter(str(x.get("source","unknown")) for x in candidates)
    priority=("india","economy","business","technology","science","defence")
    out=[]
    for c in candidates:
        x=dict(c); title=str(x.get("headline","") or x.get("title","")); cat=str(x.get("category","other")).lower()
        repeated=max((_similar(title,h) for h in old_titles[-1000:]),default=0.0)
        novelty=max(0.0,1.0-repeated)
        momentum=min(100.0,_f(x.get("trend_score"),30)+_f(x.get("breaking_score"))*0.35)
        gap=8.0 if cat in priority and seen_categories[cat] < 3 else 0.0
        diversity=min(6.0,max(0,3-source_counts.get(str(x.get("source","unknown")),1))*2.0)
        quality=max(0.0,min(100.0,_f(x.get("importance"))+gap+diversity+novelty*4.0))
        x.update({"novelty_score":round(novelty*100,1),"event_momentum":round(momentum,1),"coverage_gap_score":round(gap,1),"source_diversity_score":round(diversity,1),"quality_score":round(quality,1)})
        out.append(x)
    return sorted(out,key=lambda x:(-_f(x.get("quality_score")),-_f(x.get("personalized_score")),-_f(x.get("importance"))))

def source_health(candidates):
    grouped=defaultdict(lambda:{"articles":0,"high_value":0})
    for c in candidates:
        key=str(c.get("source","unknown") or "unknown"); grouped[key]["articles"]+=1
        if _f(c.get("importance"))>=75: grouped[key]["high_value"]+=1
    return {k:{"articles":v["articles"],"high_value":v["high_value"],"quality_rate":round(v["high_value"]/max(1,v["articles"]),3)} for k,v in grouped.items()}

def quality_snapshot(stories,research):
    total=len(stories)
    verified=sum(1 for s in stories if research.get(s.get("story_id"),{}).get("verification") in {"multi-source","multi-report","official-source","single-source"})
    strong=sum(1 for s in stories if research.get(s.get("story_id"),{}).get("verification") in {"multi-source","official-source"})
    conflicts=sum(1 for s in stories if research.get(s.get("story_id"),{}).get("contradiction_flag"))
    return {"stories":total,"verified":verified,"strong":strong,"conflicts":conflicts,"verification_rate":round(verified/max(1,total),3),"strong_rate":round(strong/max(1,total),3),"avg_importance":round(sum(_f(s.get("importance")) for s in stories)/max(1,total),1),"avg_quality":round(sum(_f(s.get("quality_score",s.get("importance"))) for s in stories)/max(1,total),1)}

def coverage_gaps(candidates):
    counts=Counter(str(x.get("category","other")).lower() for x in candidates)
    return [c for c in ("india","economy","business","technology","science","defence") if counts[c]==0]
