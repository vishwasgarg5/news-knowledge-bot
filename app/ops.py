from __future__ import annotations
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

def _f(v,d=0.0):
    """Keep non-finite telemetry out of operational and confidence summaries."""
    import math
    try:
        value=float(v)
    except (TypeError,ValueError,OverflowError):
        return d
    return value if math.isfinite(value) else d

def research_completion_rate(queue_size, corroborated):
    """Return completed/queued research, treating an empty queue as complete.

    Invalid metrics fail closed; counts are bounded to the actual queue size.
    """
    try:
        queued = int(queue_size)
        completed = int(corroborated)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if queued < 0 or completed < 0:
        return 0.0
    if queued == 0:
        return 1.0
    return round(min(queued, completed) / queued, 6)


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

def historical_trend(history, days=7, as_of=None):
    """Summarize a closed calendar window ending at as_of (today by default).

    An explicit anchor keeps reports and contract tests reproducible and prevents
    future-dated records from contaminating historical trend counts.
    """
    try:
        anchor = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10]) if as_of else date.today()
    except (TypeError, ValueError):
        anchor = date.today()
    cutoff=(anchor-timedelta(days=max(1,int(days))-1)).isoformat()
    end=anchor.isoformat()
    rows=[x for x in (history or []) if cutoff <= str(x.get("date",""))[:10] <= end]
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
    evaluation=stats.get("v5_production_evaluation") or {}
    evidence=evaluation.get("evidence") or {}
    coverage=stats.get("regional_coverage_audit") or {}
    gap_rate=_f(evidence.get("evidence_gap_rate"),1.0)
    evidence_ok=bool(evidence) and gap_rate<=0.25
    # Missing coverage telemetry is unknown, not a pass. Fail closed so a
    # malformed/older audit cannot hide a regional shortfall.
    coverage_ok=bool(coverage) and (
        _f(coverage.get("india_shortfall"),1.0)==0
        and _f(coverage.get("world_shortfall"),1.0)==0
        and "india_shortfall" in coverage
        and "world_shortfall" in coverage
    )
    checks=dict(health["checks"])
    checks["evidence"]=evidence_ok
    checks["regional_coverage"]=coverage_ok
    blockers=[]
    if not evidence_ok: blockers.append("evidence_gaps")
    if not coverage_ok: blockers.append("regional_coverage_shortfall")
    gate=stats.get("v5_quality_gate") or {}
    gate_status=str(gate.get("status","UNKNOWN")).upper()
    gate_blockers=[str(x) for x in (gate.get("blockers") or []) if str(x)]
    # A HOLD status is itself a blocker even when an older/malformed gate
    # payload omitted its blocker list. Never allow that to become a clean PASS.
    if gate and gate_status != "PASS" and not gate_blockers:
        gate_blockers.append(
            "production_quality_gate_hold" if gate_status == "HOLD"
            else "production_quality_gate_unresolved"
        )
    # Surface every production-gate blocker in the final audit, not only
    # evidence/coverage issues; otherwise calibration, drift, or ranking holds
    # can be misreported as a clean PASS.
    for blocker in gate_blockers:
        if blocker not in blockers:
            blockers.append(blocker)
    checks["production_quality_gate"] = gate_status == "PASS"
    # A missing gate is unknown, not a pass. Always surface the failed check
    # as a blocker so the summary health cannot contradict the check matrix.
    if gate_status != "PASS" and not gate_blockers:
        blocker = (
            "production_quality_gate_hold" if gate_status == "HOLD"
            else "production_quality_gate_unresolved"
        )
        if blocker not in blockers:
            blockers.append(blocker)
    # Research completion is a first-class final-audit requirement too; do not
    # depend exclusively on the upstream gate payload being present/correct.
    completion = stats.get("research_completion_rate")
    research_complete = completion is not None and _f(completion, 0.0) >= 1.0
    checks["research_completion"] = research_complete
    if not research_complete and "research_incomplete" not in blockers:
        blockers.append("research_incomplete")
    if _f(stats.get("source_failures"))>0 and "source_collection_failures" not in blockers:
        blockers.append("source_collection_failures")
    if _f(stats.get("source_warnings"))>0 and "source_collection_warnings" not in blockers:
        blockers.append("source_collection_warnings")
    status=health["status"]
    if blockers:
        status="DEGRADED"
    return {
        "health":status,
        "checks":checks,
        "blockers":blockers,
        "evidence_gap_rate":round(gap_rate,3) if evidence else None,
        "production_quality_gate":gate_status,
        "stories":len(stories),
        "india":sum(str(x.get("region","")).lower()=="india" for x in stories),
        "world":sum(str(x.get("region","")).lower()=="world" for x in stories),
        "confidence":conf,
        "contradictions":sum(bool((x.get("verification") or {}).get("contradiction_flag")) for x in stories),
        "breaking":sum(_f(x.get("breaking_score"))>=50 for x in stories),
    }
