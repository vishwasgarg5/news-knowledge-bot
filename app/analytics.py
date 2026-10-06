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
    return {
        "learning_samples":len(learning),"selected_samples":len(selected),
        "avg_outcome":round(sum(outcomes)/len(outcomes),3) if outcomes else 0,
        "daily_runs":len(daily),"history_stories":len(history),
        "source_reliability":averages(source),"category_reliability":averages(category),
        "top_categories":topics.most_common(10),
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
