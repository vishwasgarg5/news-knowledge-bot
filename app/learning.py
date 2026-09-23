from __future__ import annotations
import csv
from collections import defaultdict
import re
from datetime import date
from pathlib import Path
from .storage import HEADERS, append_rows, read_rows

def _f(v,default=0.0):
    try:return float(v)
    except:return default

def _d(v):
    try:return date.fromisoformat(str(v)[:10])
    except:return None

def _event_tokens(text):
    return set(re.findall(r"[a-zA-Z]{4,}",str(text).lower()))
def _event_sim(a,b):
    x,y=_event_tokens(a),_event_tokens(b)
    return len(x&y)/max(1,len(x|y))
def _same_event(event_id,headline,current):
    if event_id and event_id in current: return True
    return any(_event_sim(headline,h)>=0.55 for h in current.values())

def _profile(rows):
    by_source=defaultdict(lambda:[0,0.0]); by_cat=defaultdict(lambda:[0,0.0])
    for r in rows:
        if str(r.get("selected","")).lower()!="true": continue
        val=_f(r.get("learning_value"),0)
        by_source[r.get("source","unknown") or "unknown"][0]+=1; by_source[r.get("source","unknown") or "unknown"][1]+=val
        by_cat[r.get("category","other") or "other"][0]+=1; by_cat[r.get("category","other") or "other"][1]+=val
    def norm(d):
        return {k:max(-1,min(1,v[1]/max(1,v[0]))) for k,v in d.items()}
    return {"source":norm(by_source),"category":norm(by_cat)}

def evaluate_and_learn(root:Path,candidates:list[dict],today:str,selected_ids=None,record_current=False):
    path=root/"news_learning.csv"; rows=read_rows(path); should_record=record_current or selected_ids is not None; selected_ids=set(selected_ids or [])
    current={str(x.get("event_id","")):str(x.get("headline","")) for x in candidates if x.get("event_id")}
    today_d=_d(today) or date.today(); evaluated=selected_evaluated=misses=false_positive=0
    for r in rows:
        d=_d(r.get("run_date")); ev=r.get("event_id")
        if not d or not ev: continue
        age=(today_d-d).days
        if age<1: continue
        seen=_same_event(ev,r.get("headline",""),current)
        for horizon,field in ((1,"seen_again_24h"),(2,"seen_again_48h"),(7,"seen_again_7d")):
            if age>=horizon and not r.get(field): r[field]="1" if seen else "0"
        if age>=2 and not r.get("learning_value"):
            was_selected=str(r.get("selected","")).lower()=="true"
            value=(0.45 if r.get("seen_again_24h")=="1" else 0)+(0.35 if r.get("seen_again_48h")=="1" else 0)+(0.20 if r.get("seen_again_7d")=="1" else 0)
            r["learning_value"]=f"{value:.2f}"
            if was_selected and value==0:r["false_positive"]="1";false_positive+=1
            evaluated+=1
            if was_selected:selected_evaluated+=1
        if str(r.get("selected","")).lower()!="true" and seen and age>=2 and not r.get("missed"):
            r["missed"]="1";misses+=1
    if rows:
        with path.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=HEADERS["news_learning.csv"],extrasaction="ignore");w.writeheader();w.writerows(rows)
    if not should_record: return {"evaluated":evaluated,"selected_evaluated":selected_evaluated,"misses":misses,"false_positives":false_positive,"profile":_profile(rows)}
    existing={(r.get("run_date"),r.get("event_id")) for r in rows}; new=[]
    for c in candidates:
        ev=c.get("event_id","")
        if not ev or (today,ev) in existing: continue
        new.append({"run_date":today,"event_id":ev,"story_id":c.get("story_id",""),"headline":c.get("headline",""),"source":c.get("source",""),"category":c.get("category",""),"initial_score":c.get("importance",0),"selected":"true" if c.get("story_id") in selected_ids else "false","seen_again_24h":"","seen_again_48h":"","seen_again_7d":"","missed":"","false_positive":"","learning_value":""})
    append_rows(path,new,HEADERS["news_learning.csv"])
    return {"evaluated":evaluated,"selected_evaluated":selected_evaluated,"misses":misses,"false_positives":false_positive,"profile":_profile(read_rows(path))}

def apply_learning(candidates,profile):
    source=profile.get("source",{}); category=profile.get("category",{}); out=[]
    for c in candidates:
        s=source.get(c.get("source",""),0); cat=category.get(c.get("category",""),0)
        bonus=max(-5,min(5,2.5*s+2.5*cat))
        x=dict(c); x["learning_adjustment"]=round(bonus,1); x["importance"]=round(max(0,min(100,float(x.get("importance",0))+bonus)),1); out.append(x)
    return out


def learning_metrics(rows):
    labeled=[r for r in rows if r.get("learning_value")]
    selected=[r for r in labeled if str(r.get("selected","")).lower()=="true"]
    misses=[r for r in rows if str(r.get("missed",""))=="1"]
    fp=[r for r in rows if str(r.get("false_positive",""))=="1"]
    def rate(n,d): return round(n/d,3) if d else 0.0
    return {"evaluated":len(labeled),"selected_evaluated":len(selected),"success_rate":rate(sum(_f(r.get("learning_value"))>=.45 for r in selected),len(selected)),"false_positive_rate":rate(len(fp),len(selected)),"miss_rate":rate(len(misses),max(1,len(rows)-len(selected)))}
