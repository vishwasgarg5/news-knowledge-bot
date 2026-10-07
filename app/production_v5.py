from __future__ import annotations
from collections import Counter
from statistics import mean

def _f(v,d=0.0):
    try:return float(v)
    except:return d

def _label(r): return _f(r.get("outcome_score"))>=0.5

def _feature_rates(rows, field, prior=4.0, global_rate=0.5):
    counts={}
    for r in rows:
        key=str(r.get(field,"unknown") or "unknown").lower()
        hit=1 if _label(r) else 0
        n,total=counts.get(key,(0,0))
        counts[key]=(n+1,total+hit)
    return {k:round((total+prior*global_rate)/(n+prior),4) for k,(n,total) in counts.items()}


def _score_row(r, rates, weights):
    base=max(0,min(100,_f(r.get("initial_score"))))/100.0
    source=rates["source"].get(str(r.get("source","unknown") or "unknown").lower(),rates["global"])
    category=rates["category"].get(str(r.get("category","unknown") or "unknown").lower(),rates["global"])
    return weights[0]*base + weights[1]*source + weights[2]*category


def _best_v5_policy(train):
    positive=sum(_label(r) for r in train)
    global_rate=positive/max(1,len(train))
    rates={"global":global_rate,
           "source":_feature_rates(train,"source",prior=6.0,global_rate=global_rate),
           "category":_feature_rates(train,"category",prior=6.0,global_rate=global_rate)}
    best=None
    # Constrained feature search: score, source reliability and category reliability.
    # The policy is fitted only on the historical training window.
    for base_w in (0.50,0.60,0.70,0.80):
        for source_w in (0.10,0.20,0.30):
            category_w=1.0-base_w-source_w
            if category_w<0.10: continue
            weights=(base_w,source_w,category_w)
            for threshold in [x/100 for x in range(45,81,5)]:
                tp=fp=fn=0
                for r in train:
                    pred=_score_row(r,rates,weights)>=threshold; actual=_label(r)
                    tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
                p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
                f1=2*p*rec/max(1e-9,p+rec)
                candidate=(f1,p,rec,weights,threshold)
                if best is None or candidate[:3]>best[:3]:
                    best=candidate
    return {"rates":rates,"weights":best[3],"threshold":best[4],"train_f1":round(best[0],3),
            "train_precision":round(best[1],3),"train_recall":round(best[2],3)}


def walk_forward_v5(rows,train_min=60,test_window=30):
    """Leakage-safe V5: learn a constrained composite score + threshold on each training window."""
    clean=sorted([r for r in rows or [] if str(r.get("outcome_score","")).strip() not in {"","None"}],
                 key=lambda r:str(r.get("run_date","")))
    folds=[]; i=train_min
    while i<len(clean):
        train=clean[:i]; test=clean[i:i+test_window]
        if not test: break
        policy=_best_v5_policy(train)
        tp=fp=fn=0
        for r in test:
            pred=_score_row(r,policy["rates"],policy["weights"])>=policy["threshold"]; actual=_label(r)
            tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
        p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
        folds.append({"train":len(train),"test":len(test),"threshold":round(policy["threshold"],2),
                      "weights":list(policy["weights"]),"precision":round(p,3),
                      "recall":round(rec,3),"f1":round(2*p*rec/max(1,p+rec),3)})
        i+=test_window
    f1s=[x["f1"] for x in folds]
    return {"samples":len(clean),"folds":folds,"f1":round(mean(f1s),3) if f1s else 0.0,
            "precision":round(mean(x["precision"] for x in folds),3) if folds else 0.0,
            "recall":round(mean(x["recall"] for x in folds),3) if folds else 0.0,
            "thresholds":[x["threshold"] for x in folds],
            "feature_learning":True,"leakage_safe":True}

def _fold_f1(rows,threshold):
    tp=fp=fn=0
    for r in rows:
        pred=_f(r.get("initial_score"))>=threshold; actual=_label(r)
        tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
    p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
    return 2*p*rec/max(1,p+rec)

def _fixed_threshold_eval(rows,threshold=50):
    rows=[r for r in rows if str(r.get("outcome_score"," ")).strip()]
    folds=[]; test_window=30
    for end in range(120,min(len(rows)-test_window+1,120+8*test_window),test_window):
        test=rows[end:end+test_window]
        if not test: break
        tp=fp=fn=0
        for r in test:
            pred=_f(r.get("initial_score"))>=threshold; actual=_label(r)
            tp+=pred and actual; fp+=pred and not actual; fn+=actual and not pred
        p=tp/max(1,tp+fp); rec=tp/max(1,tp+fn)
        folds.append({"train":end,"test":len(test),"threshold":threshold,"precision":round(p,3),"recall":round(rec,3),"f1":round(2*p*rec/max(1,p+rec),3)})
    return {"folds":folds,"f1":round(mean([x["f1"] for x in folds]),3) if folds else 0.0,"leakage_safe":True,"threshold_policy":"fixed_50"}

def shadow_ab_test(v4_rows,v5_rows):
    a=_fixed_threshold_eval(v4_rows,50); b=walk_forward_v5(v5_rows)
    delta=round(b["f1"]-a["f1"],3)
    return {"baseline_v4":a,"candidate_v5":b,"delta_f1":delta,"promote":bool(delta>0 and b["f1"]>=a["f1"] and a.get("leakage_safe") and b.get("leakage_safe"))}

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
