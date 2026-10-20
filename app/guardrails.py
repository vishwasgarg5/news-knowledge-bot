from __future__ import annotations
from collections import Counter
from datetime import date
def _date(row):
    for key in ("run_date","date","published"):
        value=str(row.get(key,"") or "")[:10]
        try: date.fromisoformat(value); return value
        except ValueError: pass
    return ""
def temporal_drift_windows(rows,current_days=30,baseline_days=180):
    dated=[(_date(r),dict(r)) for r in (rows or []) if isinstance(r,dict) and _date(r)]
    if len(dated)>=40:
        dated.sort(key=lambda x:x[0]); latest=date.fromisoformat(dated[-1][0])
        current_start=date.fromordinal(latest.toordinal()-max(1,int(current_days))+1).isoformat()
        baseline_start=date.fromordinal(latest.toordinal()-max(1,int(current_days))-max(1,int(baseline_days))+1).isoformat()
        current=[r for d,r in dated if current_start<=d<=latest.isoformat()]
        baseline=[r for d,r in dated if baseline_start<=d<current_start]
        if len(current)>=20 and len(baseline)>=20:
            return {"current":current,"baseline":baseline,"current_start":current_start,"current_end":latest.isoformat(),"baseline_start":baseline_start,"baseline_end":date.fromordinal(date.fromisoformat(current_start).toordinal()-1).isoformat(),"method":"non_overlapping_calendar_windows"}
    clean=[dict(r) for r in (rows or []) if isinstance(r,dict)]; clean.sort(key=lambda r:(_date(r),str(r.get("event_id",""))))
    split=max(20,int(len(clean)*0.8))
    if len(clean)>=40 and split<len(clean):
        return {"current":clean[split:],"baseline":clean[:split],"current_start":_date(clean[split]) or None,"current_end":_date(clean[-1]) or None,"baseline_start":_date(clean[0]) or None,"baseline_end":_date(clean[split-1]) or None,"method":"chronological_fallback"}
    return {"current":[],"baseline":[],"current_start":None,"current_end":None,"baseline_start":None,"baseline_end":None,"method":"insufficient_data"}
def _safe_count(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0

def _publisher_key(row):
    """Canonicalize known publisher aliases using the research identity rules."""
    from .research import _source_key

    if not isinstance(row, dict):
        return ""
    source = str(row.get("source", "") or "").strip()
    url = str(row.get("url", "") or "").strip()
    return _source_key(source, url) or ""

def coverage_audit(stories,india_target=5,world_target=5):
    rows=[r for r in (stories or []) if isinstance(r,dict)]
    regions=[str(r.get("region","") or "").strip().lower() for r in rows]
    india=[r for r,region in zip(rows,regions) if region=="india"]
    world=[r for r,region in zip(rows,regions) if region=="world"]
    other_region=sum(1 for region in regions if region and region not in {"india","world"})
    missing_region=sum(1 for region in regions if not region)
    requested_india=max(0,_safe_count(india_target))
    requested_world=max(0,_safe_count(world_target))
    return {
        "stories":len(rows),
        "india":len(india),
        "world":len(world),
        "other_region":other_region,
        "missing_region":missing_region,
        "india_target":requested_india,
        "world_target":requested_world,
        "india_shortfall":max(0,requested_india-len(india)),
        "world_shortfall":max(0,requested_world-len(world)),
        "distinct_sources":len({key for r in rows if (key:=_publisher_key(r))}),
        "distinct_categories":len({str(r.get("category","")).strip().lower() for r in rows if r.get("category")}),
    }

def evidence_audit(stories):
    rows=[s for s in (stories or []) if isinstance(s,dict)]
    gaps=[]; contradictions=[]; tiers=Counter(); independent_total=0; independent_stories=0
    for story in rows:
        raw=story.get("verification") or {}
        v=raw if isinstance(raw,dict) else {}
        missing=[]
        if not str(story.get("source","") or "").strip(): missing.append("source")
        if not str(story.get("url","") or "").strip(): missing.append("url")
        if not str(story.get("summary","") or "").strip(): missing.append("summary")
        independent=_safe_count(v.get("independent_sources",0))
        independent_total+=independent
        independent_stories+=int(independent>0)
        tier=str(v.get("verification","unverified") or "unverified").lower()
        tiers[tier]+=1
        evidence=v.get("evidence") or v.get("sources") or []
        if independent<1 and not evidence and tier!="official-source": missing.append("independent_corroboration")
        if missing: gaps.append({"headline":story.get("headline",""),"missing":missing})
        if v.get("contradiction_flag"): contradictions.append({"headline":story.get("headline",""),"reason":"source contradiction"})
    total=len(rows)
    corroborated=sum(tiers[t] for t in ("multi-source","multi-report","official-source"))
    return {
        "stories":total,
        "contradictions":contradictions,
        "contradiction_count":len(contradictions),
        "contradiction_rate":round(len(contradictions)/max(1,total),3),
        "evidence_gaps":gaps,
        "evidence_gap_rate":round(len(gaps)/max(1,total),3),
        "corroborated":corroborated,
        "verification_tiers":dict(tiers),
        "independent_source_stories":independent_stories,
        "independent_sources_total":independent_total,
        "independent_source_coverage":round(independent_stories/max(1,total),3),
        "mean_independent_sources":round(independent_total/max(1,total),2),
    }
def production_readiness_gate(ranking,calibration,drift,evidence,coverage=None):
    blockers=[]
    if int((ranking or {}).get("paired_folds",0) or 0)<5: blockers.append("insufficient_paired_folds")
    cal=calibration or {}
    if int(cal.get("samples",0) or 0)<60: blockers.append("insufficient_calibration_holdout")
    ece=cal.get("ece")
    if ece is None or float(ece)>0.15: blockers.append("poor_calibration")
    if (drift or {}).get("status")!="STABLE": blockers.append("distribution_drift_or_insufficient_window")
    ev=evidence or {}
    if int(ev.get("stories",0) or 0)==0: blockers.append("missing_evidence_audit")
    elif float(ev.get("evidence_gap_rate",1.0) or 0)>0.25: blockers.append("evidence_gaps")
    cov=coverage or {}
    if int(cov.get("stories",0) or 0)>0 and (int(cov.get("india_shortfall",0) or 0)>0 or int(cov.get("world_shortfall",0) or 0)>0): blockers.append("regional_coverage_shortfall")
    if int(cov.get("source_failures",0) or 0)>0: blockers.append("source_collection_failures")
    if int(cov.get("source_warnings",0) or 0)>0: blockers.append("source_collection_warnings")
    # Fail closed: a missing completion metric is not proof research finished.
    if "research_completion_rate" not in cov or float(cov.get("research_completion_rate",0) or 0)<1.0: blockers.append("research_incomplete")
    if not (ranking or {}).get("promote",False): blockers.append("ranking_improvement_not_proven")
    return {"status":"PASS" if not blockers else "HOLD","blockers":list(dict.fromkeys(blockers)),"criteria":{"minimum_paired_folds":5,"minimum_calibration_holdout":60,"maximum_calibrated_ece":0.15,"maximum_evidence_gap_rate":0.25,"regional_targets_required":True}}
