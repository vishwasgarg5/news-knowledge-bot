from __future__ import annotations
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

def _f(v,d=0.0):
    try:return float(v)
    except (TypeError,ValueError):return d

def confidence_snapshot(stories):
    vals=[_f((s.get("verification") or {}).get("confidence")) for s in stories]
    calibrated=[_f(s.get("calibrated_confidence"),_f((s.get("verification") or {}).get("confidence"))) for s in stories]
    return {
        "stories":len(stories),
        "avg_raw":round(sum(vals)/max(1,len(vals)),1),
        "avg_calibrated":round(sum(calibrated)/max(1,len(calibrated)),1),
        "high_confidence":sum(x>=80 for x in calibrated),
        "low_confidence":sum(x<60 for x in calibrated),
    }

def historical_trend(history, days=7):
    cutoff=(date.today()-timedelta(days=max(1,int(days))-1)).isoformat()
    rows=[x for x in (history or []) if str(x.get("date",""))[:10] >= cutoff]
    by_day=Counter(str(x.get("date","")) for x in rows if x.get("date"))
    by_region=Counter(str(x.get("region","world")).lower() for x in rows)
    by_status=Counter(str(x.get("event_status","NEW")) for x in rows)
    return {"days":int(days),"stories":len(rows),"daily_counts":dict(by_day),"regions":dict(by_region),"statuses":dict(by_status)}

def operational_health(stats):
    checks={
        "sources":_f(stats.get("source_failures"))==0 and _f(stats.get("source_warnings"))==0,
        "verification":_f(stats.get("current_evidence"))/max(1,_f(stats.get("total")))>=0.50,
        "data":bool((stats.get("data_quality") or {}).get("ok",False)),
        "database":bool(stats.get("db_path")) and Path(str(stats.get("db_path"))).exists(),
        "learning":_f(stats.get("learning_labeled"))>=0,
    }
    return {"status":"PASS" if all(checks.values()) else "WARN","checks":checks,"failed_checks":[k for k,v in checks.items() if not v]}

def final_audit(stats, stories):
    health=operational_health(stats)
    conf=confidence_snapshot(stories)
    return {
        "health":health["status"],
        "checks":health["checks"],
        "stories":len(stories),
        "india":sum(str(x.get("region","")).lower()=="india" for x in stories),
        "world":sum(str(x.get("region","")).lower()=="world" for x in stories),
        "confidence":conf,
        "contradictions":sum(bool((x.get("verification") or {}).get("contradiction_flag")) for x in stories),
        "breaking":sum(_f(x.get("breaking_score"))>=50 for x in stories),
    }
