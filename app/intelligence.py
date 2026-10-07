from __future__ import annotations
import re
from collections import Counter
DEFAULT_PREFERENCES={"priority_categories":["india","economy","business","technology","science","defence"],"preferred_regions":["india","world"],"minimum_personal_score":58}
def _tokens(text): return set(re.findall(r"[a-z]{4,}",str(text or "").lower()))
def breaking_score(story):
 t=f"{story.get('headline','')} {story.get('summary','')}".lower(); score=0
 if any(x in t for x in ("breaking","just in","urgent","alert","developing")): score+=30
 if any(x in t for x in ("killed","dead","attack","earthquake","cyclone","war","ceasefire","resigns","resignation","arrested","verdict","ruling","crash","landfall","explosion","evacuation")): score+=25
 raw=str(story.get("published","") or "").replace("Z","+00:00")
 try:
  from datetime import datetime,timezone
  dt=datetime.fromisoformat(raw); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
  age=max(0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/3600)
  if age<=3: score+=35
  elif age<=6: score+=25
  elif age<=12: score+=15
  elif age<=24: score+=5
 except (TypeError,ValueError): pass
 return min(100,score+5 if story.get("region")=="india" else score)
def enrich_trends(stories,historical=None):
 history=list(historical or [])
 counts=Counter(); recurring=Counter()
 for r in history:
  t=_tokens(r.get("headline",""))
  counts.update(t)
  recurring.update(x for x in t if x)
 out=[]
 for s in stories:
  t=_tokens(s.get("headline",""))
  repeated=sum(1 for x in t if counts[x]>=2)
  strong_repeated=sum(1 for x in t if recurring[x]>=3)
  novel=sum(1 for x in t if counts[x]==0)
  # Trend means repeated concrete topic vocabulary, not simply novelty.
  # Novelty is retained as a small discovery signal but cannot create an
  # emerging-topic label by itself.
  continuity=min(55,repeated*7+strong_repeated*5)
  discovery=min(15,novel*2)
  score=min(100,30+continuity+discovery)
  x=dict(s); x["trend_score"]=round(score,1); x["trend_repeated_terms"]=repeated
  x["trend_strong_terms"]=strong_repeated; x["trend_novel_terms"]=novel
  x["breaking_score"]=breaking_score(s)
  x["emerging_topic"]=bool(repeated>=2 and (strong_repeated>=1 or x["breaking_score"]>=50))
  out.append(x)
 return out
def personalize(stories,preferences=None):
 p=dict(DEFAULT_PREFERENCES); p.update(preferences or {})
 cats={str(x).lower() for x in p.get("priority_categories",[])}
 regions={str(x).lower() for x in p.get("preferred_regions",[])}
 category_weight=float(p.get("category_weight",6) or 6); region_weight=float(p.get("region_weight",2) or 2)
 breaking_weight=float(p.get("breaking_weight",4) or 4); emerging_weight=float(p.get("emerging_weight",3) or 3)
 minimum=float(p.get("minimum_personal_score",58) or 58)
 out=[]
 for s in stories:
  x=dict(s); base=float(x.get("importance",0) or 0); score=base; reasons=[]
  if str(x.get("category","")).lower() in cats: score+=category_weight; reasons.append("priority category")
  if str(x.get("region","")).lower() in regions: score+=region_weight; reasons.append("preferred region")
  if float(x.get("breaking_score",0) or 0)>=50: score+=breaking_weight; reasons.append("breaking")
  if x.get("emerging_topic"): score+=emerging_weight; reasons.append("emerging topic")
  # Learning feedback is already applied to importance; expose it without
  # double-counting it here.
  learning=float(x.get("learning_adjustment",0) or 0)
  if learning>0: reasons.append("historically reliable")
  elif learning<0: reasons.append("historically weaker")
  score=min(100,score)
  x["personalized_score"]=round(score,1)
  x["personalization_relevant"]=bool(score>=minimum)
  x["why_for_you"]=" + ".join(reasons[:2]) if reasons else "high general importance"
  out.append(x)
 return sorted(out,key=lambda x:(-float(x.get("personalized_score",0)),-float(x.get("importance",0))))
def intelligence_summary(stories):
 return {"breaking":sum(float(s.get("breaking_score",0) or 0)>=50 for s in stories),"emerging":sum(bool(s.get("emerging_topic")) for s in stories),"avg_personalized":round(sum(float(s.get("personalized_score",0) or 0) for s in stories)/max(1,len(stories)),1)}
