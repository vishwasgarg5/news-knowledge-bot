from __future__ import annotations
from collections import Counter
from statistics import mean, stdev
import math

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


def _fit_rates(rows):
    positive=sum(_label(r) for r in rows)
    global_rate=positive/max(1,len(rows))
    return {"global":global_rate,
            "source":_feature_rates(rows,"source",prior=6.0,global_rate=global_rate),
            "category":_feature_rates(rows,"category",prior=6.0,global_rate=global_rate)}

def _best_v5_policy(train):
    """Select hyperparameters on a trailing validation slice, then refit features on all training data."""
    if len(train)<10: return {"rates":_fit_rates(train),"weights":(0.8,0.1,0.1),"threshold":0.5,"train_f1":0.0,"train_precision":0.0,"train_recall":0.0}
    split=max(5,int(len(train)*0.8)); fit,valid=train[:split],train[split:]
    rates=_fit_rates(fit); best=None
    for base_w in (0.50,0.60,0.70,0.80):
        for source_w in (0.10,0.20,0.30):
            category_w=1.0-base_w-source_w
            if category_w<0.10: continue
            weights=(base_w,source_w,category_w)
            for threshold in [x/100 for x in range(45,81,5)]:
                p,r,f1=_evaluate_rows(valid,lambda row,w=weights,t=threshold:_score_row(row,rates,w)>=t)
                candidate=(f1,p,r,weights,threshold)
                if best is None or candidate[:3]>best[:3]: best=candidate
    full_rates=_fit_rates(train)
    p,r,f1=_evaluate_rows(train,lambda row,w=best[3],t=best[4]:_score_row(row,full_rates,w)>=t)
    return {"rates":full_rates,"weights":best[3],"threshold":best[4],"train_f1":round(f1,3),"train_precision":round(p,3),"train_recall":round(r,3),"validation_f1":round(best[0],3),"validation_precision":round(best[1],3),"validation_recall":round(best[2],3)}

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

def _evaluate_rows(rows, scorer):
    tp=fp=fn=0
    for r in rows:
        pred=bool(scorer(r)); actual=_label(r)
        tp+=int(pred and actual); fp+=int(pred and not actual); fn+=int((not pred) and actual)
    precision=tp/max(1,tp+fp); recall=tp/max(1,tp+fn)
    f1=2*precision*recall/max(1e-9,precision+recall)
    return precision,recall,f1

def _fixed_threshold_eval(rows,threshold=50,train_min=60,test_window=30):
    clean=sorted([r for r in rows or [] if str(r.get("outcome_score","")).strip() not in {"","None"}], key=lambda r:str(r.get("run_date","")))
    folds=[]; i=train_min
    while i<len(clean):
        test=clean[i:i+test_window]
        if not test: break
        p,r,f1=_evaluate_rows(test,lambda x:_f(x.get("initial_score"))>=threshold)
        folds.append({"train":i,"test":len(test),"threshold":threshold,"precision":round(p,3),"recall":round(r,3),"f1":round(f1,3)})
        i+=test_window
    return {"folds":folds,"f1":round(mean([x["f1"] for x in folds]),3) if folds else 0.0,"precision":round(mean([x["precision"] for x in folds]),3) if folds else 0.0,"recall":round(mean([x["recall"] for x in folds]),3) if folds else 0.0,"leakage_safe":True,"threshold_policy":"fixed_50","train_min":train_min,"test_window":test_window}

def _delta_ci(values):
    vals=[float(x) for x in values]
    if len(vals)<2: return {"mean":round(vals[0],3) if vals else 0.0,"lower":None,"upper":None,"significant":False,"n":len(vals)}
    mu=mean(vals); se=stdev(vals)/math.sqrt(len(vals)); margin=1.96*se
    return {"mean":round(mu,3),"lower":round(mu-margin,3),"upper":round(mu+margin,3),"significant":bool(mu>0 and mu-margin>0),"n":len(vals)}

def shadow_ab_test(v4_rows,v5_rows,train_min=60,test_window=30):
    a=_fixed_threshold_eval(v4_rows,50,train_min,test_window); b=walk_forward_v5(v5_rows,train_min,test_window)
    n=min(len(a["folds"]),len(b["folds"])); deltas=[b["folds"][i]["f1"]-a["folds"][i]["f1"] for i in range(n)]
    precision_deltas=[b["folds"][i]["precision"]-a["folds"][i]["precision"] for i in range(n)]
    f1_ci=_delta_ci(deltas); precision_ci=_delta_ci(precision_deltas)
    delta=round(b["f1"]-a["f1"],3)
    promote=bool(delta>0 and b["precision"]>a["precision"] and f1_ci["significant"] and precision_ci["mean"]>0 and a.get("leakage_safe") and b.get("leakage_safe"))
    return {"baseline_v4":a,"candidate_v5":b,"delta_f1":delta,"delta_precision":round(b["precision"]-a["precision"],3),"f1_confidence_interval":f1_ci,"precision_confidence_interval":precision_ci,"paired_folds":n,"promote":promote,"promotion_rule":"V5 must improve both out-of-sample F1 and precision with positive 95% fold CI"}

def calibration_monitor(rows,bins=10):
    clean=[r for r in rows or [] if str(r.get("outcome_score","")).strip() not in {"","None"}]
    out=[]; total_abs=0.0; brier=0.0
    for i in range(bins):
        lo=i/bins; hi=(i+1)/bins
        bucket=[r for r in clean if lo<=max(0,min(100,_f(r.get("initial_score"))))/100<hi or (i==bins-1 and max(0,min(100,_f(r.get("initial_score"))))/100==hi)]
        predicted=[max(0,min(1,_f(r.get("initial_score"))/100)) for r in bucket]
        actual=[1.0 if _label(r) else 0.0 for r in bucket]
        mean_pred=mean(predicted) if predicted else None; actual_rate=mean(actual) if actual else None
        gap=abs(mean_pred-actual_rate) if bucket else 0.0; total_abs+=gap*len(bucket)
        brier+=sum((p-y)**2 for p,y in zip(predicted,actual))
        out.append({"bin":f"{lo:.1f}-{hi:.1f}","samples":len(bucket),"mean_predicted":round(mean_pred,3) if mean_pred is not None else None,"actual_rate":round(actual_rate,3) if actual_rate is not None else None,"gap":round(gap,3) if bucket else None})
    n=len(clean)
    ece=total_abs/max(1,n)
    return {"bins":out,"samples":n,"ece":round(ece,3),"brier":round(brier/max(1,n),3),"status":"CALIBRATED" if ece<=0.08 else ("OVER_CONFIDENT" if sum(1 for x in out if x["gap"] is not None and x["mean_predicted"]>x["actual_rate"] and x["gap"]>.10)>len([x for x in out if x["gap"] is not None])/2 else "UNDER_CONFIDENT")}

def calibrate_confidence(initial_score, rows, bins=10):
    """Map a raw 0-100 score to an empirical outcome probability with shrinkage."""
    score=max(0,min(100,_f(initial_score))); idx=min(bins-1,int(score/100*bins)); lo=idx/bins; hi=(idx+1)/bins
    bucket=[r for r in rows or [] if str(r.get("outcome_score","")).strip() not in {"","None"} and (lo<=max(0,min(100,_f(r.get("initial_score"))))/100<hi or (idx==bins-1 and max(0,min(100,_f(r.get("initial_score"))))/100==hi))]
    global_rate=sum(_label(r) for r in rows or [])/max(1,len(rows or []))
    rate=(sum(_label(r) for r in bucket)+4*global_rate)/(len(bucket)+4)
    return round(rate*100,1)
def drift_monitor(current,baseline):
    cur=Counter(str(r.get("category","unknown")) for r in current); base=Counter(str(r.get("category","unknown")) for r in baseline)
    keys=set(cur)|set(base); n=max(1,len(current)); m=max(1,len(baseline))
    drift=mean(abs(cur[k]/n-base[k]/m) for k in keys) if keys else 0.0
    return {"mean_distribution_shift":round(drift,4),"status":"DRIFT" if drift>=0.15 else "STABLE"}

def autonomous_research_agent(queue,history):
    return [{"headline":x.get("headline",""),"priority":x.get("priority",0),"actions":["verify primary source","search independent reports","compare historical events","recheck next run"],"retrieved_evidence":x.get("retrieved_evidence",[]),"evidence_count":x.get("evidence_count",0),"research_status":x.get("research_status","RESEARCH_REQUIRED")} for x in queue or []]

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

def production_quality_gate(ab,cal,drift,evidence):
    blockers=[]
    if ab.get("paired_folds",0)<2: blockers.append("insufficient_paired_folds")
    if cal.get("samples",0)>0 and cal.get("ece",0)>0.20: blockers.append("poor_calibration")
    if drift.get("status")=="DRIFT": blockers.append("distribution_drift")
    if len(evidence.get("contradictions",[]))>max(3,int(evidence.get("evidence_gaps",[]).__len__()*0.5)): blockers.append("high_contradiction_load")
    return {"status":"PASS" if not blockers else "HOLD","blockers":blockers}

def production_evaluation(v4_rows,v5_rows,current,baseline):
    ab=shadow_ab_test(v4_rows,v5_rows)
    cal=calibration_monitor(v5_rows)
    drift=drift_monitor(current,baseline)
    rollback=drift["status"]=="DRIFT" and not ab["promote"]
    gate=production_quality_gate(ab,cal,drift,{"contradictions":[],"evidence_gaps":[]})
    status="PROMOTE_V5" if ab["promote"] and gate["status"]=="PASS" and drift["status"]=="STABLE" else "HOLD_V4"
    return {"ab":ab,"calibration":cal,"drift":drift,"rollback":rollback,"quality_gate":gate,
            "production_status":status}

def run_v5_production_gate(learning_rows,stories,history):
    wf=walk_forward_v5(learning_rows)
    evaln=production_evaluation(learning_rows,learning_rows,stories,history)
    evidence=contradiction_and_evidence(stories)
    queue=autonomous_research_agent(evaln.get("ab",{}).get("candidate_v5",{}).get("folds",[]),history)
    return {"walk_forward":wf,"evaluation":evaln,"evidence":evidence,"followups":followup_research_plan(stories)}
