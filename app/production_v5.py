from __future__ import annotations
from collections import Counter
from statistics import mean

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def _label(r): return _f(r.get("outcome_score"))>=0.5

def walk_forward_v5(rows,train_min=120,test_window=30):
    rows=[r for r in rows if str(r.get("outcome_score","")).strip()]
    folds=[]; step=test_window
    for end in range(train_min,min(len(rows)-test_window+1,train_min+8*step),step):
        train=rows[:end]; test=rows[end:end+test_window]
        if not test: break
        threshold=60
        candidates=[x for x in range(40,81,5)]
        best=max(candidates,key=lambda t:_fold_f1(train,t))
        tp=fp=fn=0
        for r in test:
            pred=_f(r.get("initial_score"))>=best; actual=_label(r)
            tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
        p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
        folds.append({"train":len(train),"test":len(test),"threshold":best,"precision":round(p,3),"recall":round(rec,3),"f1":round(2*p*rec/max(1,p+rec),3)})
    return {"folds":folds,"f1":round(mean([x["f1"] for x in folds]),3) if folds else 0.0,"leakage_safe":True}

def _fold_f1(rows,threshold):
    tp=fp=fn=0
    for r in rows:
        pred=_f(r.get("initial_score"))>=threshold; actual=_label(r)
        tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
    p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
    return 2*p*rec/max(1,p+rec)

def shadow_ab_test(v4_rows,v5_rows):
    a=walk_forward_v5(v4_rows); b=walk_forward_v5(v5_rows)
    delta=round(b["f1"]-a["f1"],3)
    return {"baseline_v4":a,"candidate_v5":b,"delta_f1":delta,"promote":bool(delta>0 and b["f1"]>=a["f1"])}

def calibration_monitor(rows,bins=10):
    out=[]
    for i in range(bins):
        lo=i/bins; hi=(i+1)/bins
        xs=[_f(r.get("outcome_score")) for r in rows if str(r.get("outcome_score","")).strip() and lo<=_f(r.get("initial_score"))/100<hi]
        out.append({"bin":f"{lo:.1f}-{hi:.1f}","samples":len(xs),"actual_rate":round(mean([x>=.5 for x in xs]),3) if xs else None})
    return {"bins":out,"samples":sum(x["samples"] for x in out)}

def drift_monitor(current,baseline):
    cur=Counter(str(r.get("category","unknown")) for r in current); base=Counter(str(r.get("category","unknown")) for r in baseline)
    keys=set(cur)|set(base); n=max(1,len(current)); m=max(1,len(baseline))
    drift=mean(abs(cur[k]/n-base[k]/m) for k in keys) if keys else 0.0
    return {"mean_distribution_shift":round(drift,4),"status":"DRIFT" if drift>=0.15 else "STABLE"}

def autonomous_research_agent(queue,history):
    return [{"headline":x.get("headline",""),"priority":x.get("priority",0),"actions":["verify primary source","search independent reports","compare historical events","recheck next run"]} for x in queue or []]

def generate_research_reports(agent_queue):
    return [{"title":"Automated Intelligence Research","headline":x["headline"],"priority":x["priority"],"status":"QUEUED","actions":x["actions"]} for x in agent_queue]

def contradiction_and_evidence(stories):
    contradictions=[]; gaps=[]
    for s in stories or []:
        v=s.get("verification") or {}
        if v.get("contradiction_flag"): contradictions.append({"headline":s.get("headline",""),"reason":"source contradiction"})
        missing=[]
        if not s.get("source"): missing.append("source")
        if not s.get("url"): missing.append("url")
        if not s.get("summary"): missing.append("summary")
        if not s.get("source_count") and not v.get("sources"): missing.append("independent_sources")
        if missing:gaps.append({"headline":s.get("headline",""),"missing":missing})
    return {"contradictions":contradictions,"evidence_gaps":gaps}

def followup_research_plan(stories):
    return [{"headline":s.get("headline",""),"next_check":["official confirmation","independent confirmation","new developments"],"priority":_f((s.get("impact") or {}).get("score"))} for s in stories or []]

def production_evaluation(v4_rows,v5_rows,current,baseline):
    ab=shadow_ab_test(v4_rows,v5_rows)
    cal=calibration_monitor(v5_rows)
    drift=drift_monitor(current,baseline)
    rollback=drift["status"]=="DRIFT" and not ab["promote"]
    return {"ab":ab,"calibration":cal,"drift":drift,"rollback":rollback,
            "production_status":"PROMOTE_V5" if ab["promote"] and drift["status"]=="STABLE" else "HOLD_V4"}

def run_v5_production_gate(learning_rows,stories,history):
    wf=walk_forward_v5(learning_rows)
    evaln=production_evaluation(learning_rows,learning_rows,stories,history)
    evidence=contradiction_and_evidence(stories)
    queue=autonomous_research_agent(evaln.get("ab",{}).get("candidate_v5",{}).get("folds",[]),history)
    return {"walk_forward":wf,"evaluation":evaln,"evidence":evidence,"followups":followup_research_plan(stories)}
