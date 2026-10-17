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
def coverage_audit(stories,india_target=5,world_target=5):
    rows=list(stories or []); india=[r for r in rows if str(r.get("region","")).lower()=="india"]; world=[r for r in rows if str(r.get("region","")).lower()=="world"]
    return {"stories":len(rows),"india":len(india),"world":len(world),"india_target":max(0,int(india_target)),"world_target":max(0,int(world_target)),"india_shortfall":max(0,int(india_target)-len(india)),"world_shortfall":max(0,int(world_target)-len(world)),"distinct_sources":len({str(r.get("source","")).strip().lower() for r in rows if r.get("source")}),"distinct_categories":len({str(r.get("category","")).strip().lower() for r in rows if r.get("category")})}
def evidence_audit(stories):
    rows=list(stories or []); gaps=[]; contradictions=[]
    for story in rows:
        v=story.get("verification") or {}; missing=[]
        if not str(story.get("source","") or "").strip(): missing.append("source")
        if not str(story.get("url","") or "").strip(): missing.append("url")
        if not str(story.get("summary","") or "").strip(): missing.append("summary")
        independent=int(v.get("independent_sources",0) or 0); evidence=v.get("evidence") or v.get("sources") or []
        if independent<1 and not evidence and v.get("verification")!="official-source": missing.append("independent_corroboration")
        if missing: gaps.append({"headline":story.get("headline",""),"missing":missing})
        if v.get("contradiction_flag"): contradictions.append({"headline":story.get("headline",""),"reason":"source contradiction"})
    return {"stories":len(rows),"contradictions":contradictions,"evidence_gaps":gaps,"evidence_gap_rate":round(len(gaps)/max(1,len(rows)),3),"corroborated":sum(1 for s in rows if (s.get("verification") or {}).get("verification") in {"multi-source","multi-report","official-source"})}
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
    if not (ranking or {}).get("promote",False): blockers.append("ranking_improvement_not_proven")
    return {"status":"PASS" if not blockers else "HOLD","blockers":list(dict.fromkeys(blockers)),"criteria":{"minimum_paired_folds":5,"minimum_calibration_holdout":60,"maximum_calibrated_ece":0.15,"maximum_evidence_gap_rate":0.25,"regional_targets_required":True}}
