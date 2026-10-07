from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import json
from pathlib import Path


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def time_series_backtest(rows, minimum_train=30, test_window=20, minimum_threshold=55, maximum_threshold=85, step=5):
    """Rolling-origin backtest: thresholds are learned only from rows before each test window."""
    clean=[]
    for r in rows or []:
        try:
            score=_f(r.get("initial_score"))
            outcome=_f(r.get("outcome_score") or r.get("learning_value"))
        except Exception:
            continue
        clean.append((str(r.get("run_date","")), score, outcome >= 0.5))
    clean.sort(key=lambda x:x[0])
    if len(clean) < max(1, minimum_train + 1):
        return {"samples":len(clean),"folds":0,"precision":0.0,"recall":0.0,"f1":0.0,"mae":0.0,"stability":0.0,"leakage_safe":True}

    folds=[]
    start=minimum_train
    while start < len(clean):
        train=clean[:start]
        test=clean[start:start+test_window]
        if not test: break
        best_threshold=minimum_threshold
        best_f1=-1.0
        for threshold in range(int(minimum_threshold), int(maximum_threshold)+1, int(step)):
            tp=sum(score>=threshold and actual for _,score,actual in train)
            fp=sum(score>=threshold and not actual for _,score,actual in train)
            fn=sum(score<threshold and actual for _,score,actual in train)
            precision=tp/max(1,tp+fp)
            recall=tp/max(1,tp+fn)
            f1=2*precision*recall/max(1e-9,precision+recall)
            if f1 > best_f1 or (f1 == best_f1 and threshold > best_threshold):
                best_f1=f1; best_threshold=threshold
        predicted=[score>=best_threshold for _,score,_ in test]
        actual=[actual for _,_,actual in test]
        tp=sum(p and a for p,a in zip(predicted,actual))
        fp=sum(p and not a for p,a in zip(predicted,actual))
        fn=sum((not p) and a for p,a in zip(predicted,actual))
        precision=tp/max(1,tp+fp); recall=tp/max(1,tp+fn)
        f1=2*precision*recall/max(1e-9,precision+recall)
        mae=sum(abs((1.0 if a else 0.0)-(s/100.0)) for _,s,a in test)/len(test)
        folds.append({"test_start":test[0][0],"test_end":test[-1][0],"threshold":best_threshold,"precision":precision,"recall":recall,"f1":f1,"mae":mae})
        start += test_window

    if not folds:
        return {"samples":len(clean),"folds":0,"precision":0.0,"recall":0.0,"f1":0.0,"mae":0.0,"stability":0.0,"leakage_safe":True}
    avg=lambda k: sum(_f(x[k]) for x in folds)/len(folds)
    f1s=[_f(x["f1"]) for x in folds]
    stability=max(0.0,1.0-(max(f1s)-min(f1s))) if f1s else 0.0
    return {"samples":len(clean),"folds":len(folds),"precision":round(avg("precision"),3),"recall":round(avg("recall"),3),"f1":round(avg("f1"),3),"mae":round(avg("mae"),3),"stability":round(stability,3),"thresholds":[x["threshold"] for x in folds],"leakage_safe":True}


def feedback_snapshot(root: Path):
    path=Path(root)/"news_feedback.csv"
    if not path.exists():
        return {"samples":0,"useful":0,"not_useful":0,"duplicate":0,"important":0}
    import csv
    with path.open(newline="",encoding="utf-8") as fh:
        rows=list(csv.DictReader(fh))
    counts=Counter(str(r.get("feedback","")).lower() for r in rows)
    return {"samples":len(rows),"useful":counts["useful"],"not_useful":counts["not_useful"],"duplicate":counts["duplicate"],"important":counts["important"]}


def feedback_adjustment(snapshot):
    """Small bounded preference adjustment; user feedback never overrides verification."""
    useful=_f(snapshot.get("useful")); bad=_f(snapshot.get("not_useful"))
    delta=max(-2.0,min(2.0,(useful-bad)*0.25))
    return {"ranking_delta":round(delta,2),"confidence_bonus":round(max(0.0,min(1.5,useful*0.05)),2)}


def source_fallback_order(source_health, preferred=None):
    preferred=list(preferred or [])
    ranked=[]
    for source,metrics in (source_health or {}).items():
        quality=_f(metrics.get("quality_rate"))
        ranked.append((source,quality,_f(metrics.get("high_value"))))
    ranked.sort(key=lambda x:(x[1],x[2]),reverse=True)
    ordered=[]
    for source in preferred + [x[0] for x in ranked]:
        if source not in ordered:
            ordered.append(source)
    return ordered


def lifecycle_summary(rows):
    counts=Counter(str(r.get("event_status","NEW")).upper() for r in rows or [])
    return {k:counts.get(k,0) for k in ("NEW","DEVELOPING","ESCALATING","CONFIRMED","RESOLVED")}


def monitoring_alerts(stats):
    alerts=[]
    if _f(stats.get("source_failures"))>0: alerts.append("SOURCE_FAILURE")
    if _f(stats.get("source_warnings"))>0: alerts.append("SOURCE_WARNING")
    if _f(stats.get("stories"))==0: alerts.append("NO_STORIES")
    if _f(stats.get("world_stories"))<_f(stats.get("world_target",5)): alerts.append("WORLD_COVERAGE_GAP")
    if _f(stats.get("india_stories"))<_f(stats.get("india_target",5)): alerts.append("INDIA_COVERAGE_GAP")
    if _f(stats.get("operational_health",{}).get("status"),0) if isinstance(stats.get("operational_health"),dict) else False: pass
    if str(stats.get("health","")).upper()=="DEGRADED": alerts.append("PIPELINE_DEGRADED")
    return sorted(set(alerts))


def persist_operational_snapshot(root: Path, payload):
    path=Path(root)/"operational_snapshot.json"
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return path
