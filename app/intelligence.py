from __future__ import annotations
import re
from collections import Counter
DEFAULT_PREFERENCES={"priority_categories":["india","economy","business","technology","science","defence"],"preferred_regions":["india","world"],"minimum_personal_score":58}
def _tokens(text): return set(re.findall(r"[a-z]{4,}",str(text or "").lower()))
def breaking_score(story):
 t=f"{story.get('headline','')} {story.get('summary','')}".lower(); s=0
 if any(x in t for x in ("breaking","just in","urgent","alert")): s+=30
 if any(x in t for x in ("killed","dead","attack","earthquake","cyclone","war","ceasefire","resigns","resignation","arrested","verdict","ruling","crash")): s+=25
 return min(100,s+5 if story.get("region")=="india" else s)
def enrich_trends(stories,historical=None):
 counts=Counter()
 for r in (historical or []): counts.update(_tokens(r.get("headline","")))
 out=[]
 for s in stories:
  t=_tokens(s.get("headline","")); overlap=sum(counts[x]>=2 for x in t); novelty=sum(counts[x]==0 for x in t)
  x=dict(s); x["trend_score"]=round(min(100,40+overlap*8+novelty*3),1); x["breaking_score"]=breaking_score(s); x["emerging_topic"]=x["trend_score"]>=65 and x["breaking_score"]>=20; out.append(x)
 return out
def personalize(stories,preferences=None):
 p=dict(DEFAULT_PREFERENCES); p.update(preferences or {})
 cats={str(x).lower() for x in p.get("priority_categories",[])}
 regions={str(x).lower() for x in p.get("preferred_regions",[])}
 minimum=float(p.get("minimum_personal_score",58) or 58)
 out=[]
 for s in stories:
  x=dict(s); base=float(x.get("importance",0) or 0); score=base; reasons=[]
  if str(x.get("category","")).lower() in cats: score+=6; reasons.append("priority category")
  if str(x.get("region","")).lower() in regions: score+=2; reasons.append("preferred region")
  if float(x.get("breaking_score",0) or 0)>=50: score+=4; reasons.append("breaking")
  if x.get("emerging_topic"): score+=3; reasons.append("emerging topic")
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
