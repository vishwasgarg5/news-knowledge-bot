from __future__ import annotations
from collections import Counter
from statistics import mean, stdev
import math
from .storage import outcome_is_mature
from .guardrails import production_readiness_gate, evidence_audit

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
                beta2=2.25
                f_beta=(1+beta2)*p*r/max(1e-9,beta2*p+r)
                candidate=(f_beta,f1,p,r,weights,threshold)
                if best is None or candidate[:4]>best[:4]: best=candidate
    full_rates=_fit_rates(train)
    p,r,f1=_evaluate_rows(train,lambda row,w=best[4],t=best[5]:_score_row(row,full_rates,w)>=t)
    return {"rates":full_rates,"weights":best[4],"threshold":best[5],"train_f1":round(f1,3),"train_precision":round(p,3),"train_recall":round(r,3),"validation_f_beta_1_5":round(best[0],3),"validation_f1":round(best[1],3),"validation_precision":round(best[2],3),"validation_recall":round(best[3],3)}

def walk_forward_v5(rows,train_min=60,test_window=30):
    """Leakage-safe V5: learn a constrained composite score + threshold on each training window."""
    clean=sorted([r for r in rows or [] if outcome_is_mature(r) and str(r.get("outcome_score","")).strip() not in {"","None"}],
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
    clean=sorted([r for r in rows or [] if outcome_is_mature(r) and str(r.get("outcome_score","")).strip() not in {"","None"}], key=lambda r:str(r.get("run_date","")))
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
    if len(vals)<5: return {"mean":round(mean(vals),3) if vals else 0.0,"lower":None,"upper":None,"significant":False,"n":len(vals)}
    mu=mean(vals); se=stdev(vals)/math.sqrt(len(vals)); critical={5:2.776,6:2.571,7:2.447,8:2.365,9:2.306,10:2.262,11:2.228,12:2.201}.get(len(vals),1.96 if len(vals)>=30 else 2.10); margin=critical*se
    return {"mean":round(mu,3),"lower":round(mu-margin,3),"upper":round(mu+margin,3),"significant":bool(mu>0 and mu-margin>0),"n":len(vals)}
def shadow_ab_test(v4_rows,v5_rows,train_min=60,test_window=30):
    a=_fixed_threshold_eval(v4_rows,50,train_min,test_window); b=walk_forward_v5(v5_rows,train_min,test_window)
    n=min(len(a["folds"]),len(b["folds"])); deltas=[b["folds"][i]["f1"]-a["folds"][i]["f1"] for i in range(n)]
    precision_deltas=[b["folds"][i]["precision"]-a["folds"][i]["precision"] for i in range(n)]
    f1_ci=_delta_ci(deltas); precision_ci=_delta_ci(precision_deltas)
    delta=round(b["f1"]-a["f1"],3)
    promote=bool(delta>0 and b["precision"]>a["precision"] and f1_ci["significant"] and precision_ci["mean"]>0 and a.get("leakage_safe") and b.get("leakage_safe"))
    return {"baseline_v4":a,"candidate_v5":b,"delta_f1":delta,"delta_precision":round(b["precision"]-a["precision"],3),"f1_confidence_interval":f1_ci,"precision_confidence_interval":precision_ci,"paired_folds":n,"promote":promote,"promotion_rule":"V5 must improve both out-of-sample F1 and precision with positive 95% fold CI"}

def calibrate_confidence(initial_score, rows, bins=10):
    """Map a raw 0-100 score to an empirical outcome probability with shrinkage."""
    score=max(0,min(100,_f(initial_score))); idx=min(bins-1,int(score/100*bins)); lo=idx/bins; hi=(idx+1)/bins
    mature=[r for r in rows or [] if outcome_is_mature(r) and str(r.get("outcome_score","")).strip() not in {"","None"}]
    bucket=[r for r in mature if (lo<=max(0,min(100,_f(r.get("initial_score"))))/100<hi or (idx==bins-1 and max(0,min(100,_f(r.get("initial_score"))))/100==hi))]
    global_rate=sum(_label(r) for r in mature)/max(1,len(mature))
    rate=(sum(_label(r) for r in bucket)+4*global_rate)/(len(bucket)+4)
    return round(rate*100,1)
def calibration_monitor(rows,bins=10):
    """Fit score-to-outcome calibration on earlier rows and evaluate later rows only."""
    clean=sorted([dict(r) for r in (rows or []) if outcome_is_mature(r) and str(r.get("outcome_score","")).strip() not in {"","None"}],key=lambda r:str(r.get("run_date","")))
    n=len(clean)
    if n<60: return {"bins":[],"samples":n,"train_samples":n,"holdout_samples":0,"ece":None,"brier":None,"status":"INSUFFICIENT_DATA","method":"chronological_holdout","leakage_safe":True}
    split=max(40,int(n*0.70))
    if n-split<20: split=n-20
    train,holdout=clean[:split],clean[split:]
    def score_bin(row): return min(bins-1,int(max(0,min(100,_f(row.get("initial_score"))))/100*bins))
    global_rate=sum(_label(r) for r in train)/max(1,len(train)); counts=Counter(); hits=Counter()
    for row in train:
        key=score_bin(row); counts[key]+=1; hits[key]+=int(_label(row))
    rates={i:(hits[i]+8*global_rate)/(counts[i]+8) for i in range(bins)}
    scored=[]
    for row in holdout:
        raw=max(0,min(1,_f(row.get("initial_score"))/100)); pred=max(0,min(1,rates[score_bin(row)])); scored.append((raw,pred,1.0 if _label(row) else 0.0))
    ece=0.0; raw_ece=0.0; bucket_rows=[]
    for i in range(bins):
        lo=i/bins; hi=(i+1)/bins
        bucket=[x for x in scored if lo<=x[1]<hi or (i==bins-1 and x[1]==hi)]
        raw_bucket=[x for x in scored if lo<=x[0]<hi or (i==bins-1 and x[0]==hi)]
        if bucket:
            mp=mean(x[1] for x in bucket); ar=mean(x[2] for x in bucket); ece+=abs(mp-ar)*len(bucket)/max(1,len(scored))
            bucket_rows.append({"bin":f"{lo:.1f}-{hi:.1f}","samples":len(bucket),"mean_predicted":round(mp,3),"actual_rate":round(ar,3),"gap":round(abs(mp-ar),3)})
        if raw_bucket: raw_ece+=abs(mean(x[0] for x in raw_bucket)-mean(x[2] for x in raw_bucket))*len(raw_bucket)/max(1,len(scored))
    brier=sum((pred-y)**2 for _,pred,y in scored)/max(1,len(scored)); mean_pred=mean(x[1] for x in scored); observed=mean(x[2] for x in scored)
    status="CALIBRATED" if ece<=0.10 else ("OVER_CONFIDENT" if mean_pred>observed else "UNDER_CONFIDENT")
    return {"bins":bucket_rows,"samples":len(scored),"train_samples":len(train),"holdout_samples":len(holdout),"ece":round(ece,3),"raw_ece":round(raw_ece,3),"brier":round(brier,3),"status":status,"method":"chronological_holdout_smoothed_score_bins","holdout_start":str(holdout[0].get("run_date",""))[:10],"holdout_end":str(holdout[-1].get("run_date",""))[:10],"leakage_safe":True}
def drift_monitor(current,baseline):
    """Compare category distributions on distinct reference/current windows."""
    current=[r for r in (current or []) if isinstance(r,dict)]; baseline=[r for r in (baseline or []) if isinstance(r,dict)]
    if len(current)<20 or len(baseline)<20: return {"mean_distribution_shift":None,"status":"UNKNOWN","current_samples":len(current),"baseline_samples":len(baseline),"method":"total_variation"}
    cur=Counter(str(r.get("category","unknown") or "unknown").lower() for r in current); base=Counter(str(r.get("category","unknown") or "unknown").lower() for r in baseline)
    keys=set(cur)|set(base); n=len(current); m=len(baseline); drift=0.5*sum(abs(cur[k]/n-base[k]/m) for k in keys)
    return {"mean_distribution_shift":round(drift,4),"status":"DRIFT" if drift>=0.20 else "STABLE","current_samples":n,"baseline_samples":m,"current_categories":dict(cur),"baseline_categories":dict(base),"method":"total_variation","threshold":0.20}
def contradiction_and_evidence(stories):
    return evidence_audit(stories)
def followup_research_plan(stories):
    return [{"headline":s.get("headline",""),"next_check":["official confirmation","independent confirmation","new developments"],"priority":_f((s.get("impact") or {}).get("score"))} for s in stories or []]

def production_quality_gate(ab,cal,drift,evidence,coverage=None):
    return production_readiness_gate(ab,cal,drift,evidence,coverage)

def production_evaluation(v4_rows,v5_rows,current,baseline,drift_current=None,drift_baseline=None,coverage=None):
    ab=shadow_ab_test(v4_rows,v5_rows); cal=calibration_monitor(v5_rows)
    drift=drift_monitor(drift_current if drift_current is not None else current,drift_baseline if drift_baseline is not None else baseline)
    evidence=contradiction_and_evidence(current); gate=production_quality_gate(ab,cal,drift,evidence,coverage)
    rollback=drift.get("status") in {"DRIFT","UNKNOWN"} and not ab["promote"]
    status="PROMOTE_V5" if ab["promote"] and gate["status"]=="PASS" and drift["status"]=="STABLE" else "HOLD_V4"
    return {"ab":ab,"calibration":cal,"drift":drift,"rollback":rollback,"evidence":evidence,"quality_gate":gate,"production_status":status}

