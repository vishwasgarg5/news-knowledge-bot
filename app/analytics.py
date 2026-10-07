from __future__ import annotations
from collections import Counter,defaultdict
import json
from datetime import date, timedelta
from .storage import read_rows

def build_report(data_path):
    learning=read_rows(data_path/"news_learning.csv")
    daily=read_rows(data_path/"news_learning_daily.csv")
    history=read_rows(data_path/"news_history.csv")
    def f(x):
        try:return float(x)
        except:return 0.0
    selected=[r for r in learning if str(r.get("selected","")).lower() in {"true","1","yes"}]
    outcomes=[f(r.get("outcome_score") or r.get("learning_value")) for r in learning]
    source=defaultdict(list); category=defaultdict(list)
    for r,v in zip(learning,outcomes):
        source[r.get("source","unknown")].append(v); category[r.get("category","unknown")].append(v)
    def averages(d):
        return {k:round(sum(v)/len(v),3) for k,v in sorted(d.items(),key=lambda z:-len(z[1])) if v}
    topics=Counter(str(r.get("category","unknown")).lower() for r in history)
    def coverage(field):
        return sum(1 for r in learning if str(r.get(field,"")).strip() in {"0","1"})
    horizon_coverage={
        "24h":coverage("seen_again_24h"),
        "48h":coverage("seen_again_48h"),
        "7d":coverage("seen_again_7d"),
    }
    return {
        "learning_samples":len(learning),"selected_samples":len(selected),
        "avg_outcome":round(sum(outcomes)/len(outcomes),3) if outcomes else 0,
        "daily_runs":len(daily),"history_stories":len(history),
        "source_reliability":averages(source),"category_reliability":averages(category),
        "top_categories":topics.most_common(10),
        "outcome_horizon_coverage":horizon_coverage,
        "outcome_maturity":{"24h":coverage("seen_again_24h"),"48h":coverage("seen_again_48h"),"7d":coverage("seen_again_7d")},
        "false_positives":sum(1 for r in learning if str(r.get("false_positive",""))=="1"),
        "missed_stories":sum(1 for r in learning if str(r.get("missed",""))=="1"),
    }



def backtest_learning(data_path, min_score=0):
    """Evaluate historical predictions without using future rows for ranking."""
    rows=read_rows(data_path/"news_learning.csv")
    evaluated=[]
    for r in rows:
        try:
            initial=float(r.get("initial_score") or 0)
            outcome=float(r.get("outcome_score") or r.get("learning_value") or 0)
        except (TypeError,ValueError):
            continue
        if initial < float(min_score): continue
        evaluated.append({
            "run_date":r.get("run_date",""),"event_id":r.get("event_id",""),
            "initial_score":initial,"outcome_score":outcome,
            "selected":str(r.get("selected","")).lower() in {"true","1","yes"},
        })
    if not evaluated:
        return {"samples":0,"selected":0,"avg_outcome":0,"mae":0,"hit_rate":0}
    errors=[abs(x["initial_score"]/100-x["outcome_score"]) for x in evaluated]
    hits=[x for x in evaluated if (x["initial_score"]>=50)==(x["outcome_score"]>=0.5)]
    return {"samples":len(evaluated),"selected":sum(x["selected"] for x in evaluated),
            "avg_outcome":round(sum(x["outcome_score"] for x in evaluated)/len(evaluated),3),
            "mae":round(sum(errors)/len(errors),3),"hit_rate":round(len(hits)/len(evaluated),3)}

def backtest_learning_v2(data_path, min_score=0):
    """Leakage-safe diagnostic backtest with precision, recall and score buckets."""
    rows=read_rows(data_path/"news_learning.csv"); samples=[]
    for r in rows:
        try: score=float(r.get("initial_score") or 0); outcome=float(r.get("outcome_score") or r.get("learning_value") or 0)
        except (TypeError,ValueError): continue
        if score>=float(min_score): samples.append((score,outcome))
    if not samples: return {"samples":0,"precision":0,"recall":0,"f1":0,"hit_rate":0,"mae":0,"buckets":{}}
    predicted=[s>=50 for s,_ in samples]; actual=[o>=0.5 for _,o in samples]
    tp=sum(p and q for p,q in zip(predicted,actual)); fp=sum(p and not q for p,q in zip(predicted,actual)); fn=sum((not p) and q for p,q in zip(predicted,actual))
    precision=tp/max(1,tp+fp); recall=tp/max(1,tp+fn); f1=2*precision*recall/max(1,precision+recall)
    mae=sum(abs(s/100-o) for s,o in samples)/len(samples); hit=sum(p==q for p,q in zip(predicted,actual))/len(samples)
    buckets={}
    for lo,hi in ((0,50),(50,70),(70,85),(85,101)):
        group=[o for s,o in samples if lo<=s<hi]; buckets[f"{lo}-{hi-1}"]={"samples":len(group),"avg_outcome":round(sum(group)/len(group),3) if group else 0}
    return {"samples":len(samples),"precision":round(precision,3),"recall":round(recall,3),"f1":round(f1,3),"hit_rate":round(hit,3),"mae":round(mae,3),"buckets":buckets}

def quality_dashboard(data_path):
    """Return compact operational metrics for daily/weekly observability."""
    report=build_report(data_path)
    return {
        "learning_samples":report["learning_samples"],
        "history_stories":report["history_stories"],
        "daily_runs":report["daily_runs"],
        "avg_outcome":report["avg_outcome"],
        "false_positive_rate":round(report["false_positives"]/max(1,report["selected_samples"]),3),
        "horizon_coverage":report["outcome_horizon_coverage"],
        "top_categories":report["top_categories"][:5],
        "backtest":backtest_learning_v2(data_path),
    }
def write_reports(data_path):
    report=build_report(data_path)
    (data_path/"analytics_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    today=date.today()
    cutoff=today-timedelta(days=7)
    daily=read_rows(data_path/"news_learning_daily.csv")
    recent=[r for r in daily if str(r.get("date",""))[:10] >= cutoff.isoformat()]
    report["last_7_days"]={
        "runs":len(recent),
        "avg_success_rate":round(sum(float(r.get("success_rate") or 0) for r in recent)/len(recent),3) if recent else 0,
        "avg_false_positive_rate":round(sum(float(r.get("false_positive_rate") or 0) for r in recent)/len(recent),3) if recent else 0,
        "avg_miss_rate":round(sum(float(r.get("miss_rate") or 0) for r in recent)/len(recent),3) if recent else 0,
    }
    (data_path/"analytics_weekly.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report
