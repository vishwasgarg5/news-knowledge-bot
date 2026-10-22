#!/usr/bin/env python3
"""Summarize paired policy changes with deterministic bootstrap uncertainty intervals."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from scripts.compare_policy_evaluations import compare_policy_reports


def _eligible_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("candidate_results", [])
    if not isinstance(rows, list):
        return {}
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("eligible_for_precision_recall") is not True:
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        label = row.get("adjudicated_label")
        if candidate_id and label in {"relevant", "not_relevant"}:
            result[candidate_id] = row
    return result


def _metrics(rows: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    tp = fp = fn = 0
    for _, base, candidate in rows:
        truth = candidate.get("adjudicated_label")
        # The candidate report's label is used only after the comparator proves labels match.
        base_included = base.get("disposition") == "included"
        cand_included = candidate.get("disposition") == "included"
        if cand_included and truth == "relevant":
            pass
        tp += int(cand_included and truth == "relevant")
        fp += int(cand_included and truth == "not_relevant")
        fn += int(not cand_included and truth == "relevant")
    included_base = sum(base.get("disposition") == "included" for _, base, _ in rows)
    included_cand = sum(candidate.get("disposition") == "included" for _, _, candidate in rows)
    tp_base = sum(base.get("disposition") == "included" and candidate.get("adjudicated_label") == "relevant"
                  for _, base, candidate in rows)
    fp_base = sum(base.get("disposition") == "included" and candidate.get("adjudicated_label") == "not_relevant"
                  for _, base, candidate in rows)
    fn_base = sum(base.get("disposition") != "included" and candidate.get("adjudicated_label") == "relevant"
                  for _, base, candidate in rows)
    relevant = sum(candidate.get("adjudicated_label") == "relevant" for _, _, candidate in rows)
    def div(a: int, b: int) -> float | None:
        return a / b if b else None
    return {
        "baseline": {"true_positives": tp_base, "false_positives": fp_base,
                     "missed_relevant_candidates": fn_base,
                     "inclusion_precision": div(tp_base, included_base),
                     "inclusion_recall": div(tp_base, relevant)},
        "candidate": {"true_positives": tp, "false_positives": fp,
                      "missed_relevant_candidates": fn,
                      "inclusion_precision": div(tp, included_cand),
                      "inclusion_recall": div(tp, relevant)},
    }


def summarize_paired_evaluation(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    baseline_gate: dict[str, Any],
    candidate_gate: dict[str, Any],
    *,
    bootstrap_samples: int = 2000,
    seed: int = 20261022,
) -> dict[str, Any]:
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")
    comparison = compare_policy_reports(baseline_report, candidate_report, baseline_gate, candidate_gate)
    if comparison.get("comparable") is not True:
        return {
            "summary_schema_version": "1.0",
            "status": "blocked",
            "comparable": False,
            "comparison_errors": comparison.get("errors", []),
            "comparison_checks": comparison.get("checks", []),
            "improvement_claim": "not_supported",
            "reason": "The comparator did not establish a matching, valid adjudicated cohort.",
        }

    baseline_rows = _eligible_rows(baseline_report)
    candidate_rows = _eligible_rows(candidate_report)
    ids = sorted(set(baseline_rows) & set(candidate_rows))
    if not ids:
        return {"summary_schema_version": "1.0", "status": "blocked", "comparable": False,
                "comparison_errors": ["no_metric_eligible_paired_candidates"],
                "improvement_claim": "not_supported"}
    paired = [(cid, baseline_rows[cid], candidate_rows[cid]) for cid in ids]
    point = _metrics(paired)
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {"inclusion_precision": [], "inclusion_recall": []}
    skipped = {"inclusion_precision": 0, "inclusion_recall": 0}
    for _ in range(bootstrap_samples):
        resample = [paired[rng.randrange(len(paired))] for _ in paired]
        result = _metrics(resample)
        for metric in samples:
            left = result["baseline"][metric]
            right = result["candidate"][metric]
            if left is None or right is None:
                skipped[metric] += 1
            else:
                samples[metric].append(right - left)

    intervals = {}
    for metric, values in samples.items():
        if len(values) < max(100, int(bootstrap_samples * 0.8)):
            intervals[metric] = {
                "delta": (point["candidate"][metric] - point["baseline"][metric]
                          if point["candidate"][metric] is not None and point["baseline"][metric] is not None else None),
                "confidence_level": 0.95, "lower": None, "upper": None,
                "status": "uncertain_insufficient_defined_resamples",
                "defined_resamples": len(values), "skipped_resamples": skipped[metric],
            }
            continue
        ordered = sorted(values)
        lower = ordered[int(0.025 * (len(ordered) - 1))]
        upper = ordered[int(0.975 * (len(ordered) - 1))]
        delta = point["candidate"][metric] - point["baseline"][metric]
        intervals[metric] = {
            "delta": delta, "confidence_level": 0.95, "lower": lower, "upper": upper,
            "status": "uncertain_interval_includes_zero" if lower <= 0 <= upper else
                      ("candidate_higher" if lower > 0 else "candidate_lower"),
            "defined_resamples": len(values), "skipped_resamples": skipped[metric],
        }

    fingerprint_payload = {
        "candidate_ids": ids,
        "labels": [(cid, candidate_rows[cid].get("adjudicated_label")) for cid in ids],
        "sampling_metadata": candidate_report.get("sampling_metadata", []),
    }
    cohort_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    claims_supported = all(intervals[m]["status"] == "candidate_higher"
                            for m in ("inclusion_precision", "inclusion_recall"))
    return {
        "summary_schema_version": "1.0",
        "status": "complete",
        "comparable": True,
        "cohort": {
            "fingerprint_sha256": cohort_fingerprint,
            "eligible_paired_candidates": len(ids),
            "baseline_policy_version": comparison.get("baseline_policy_version"),
            "candidate_policy_version": comparison.get("candidate_policy_version"),
            "sampling_design": candidate_report.get("sampling_metadata", []),
        },
        "observed_metrics": point,
        "paired_bootstrap": {
            "method": "paired candidate-level percentile bootstrap",
            "confidence_level": 0.95,
            "requested_resamples": bootstrap_samples,
            "seed": seed,
            "intervals": intervals,
            "caveat": "Intervals quantify resampling uncertainty under this reviewed cohort; they do not correct selection bias or prove causal effects.",
        },
        "improvement_claim": "supported_on_this_cohort_only" if claims_supported else "not_supported",
        "warnings": [
            "Do not claim general or causal improvement from this summary.",
            "A policy improvement claim is withheld unless both precision and recall intervals are entirely above zero.",
            "A matching candidate set and sampling metadata do not prove the reviewed cohort is representative.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_report", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("--baseline-gate", required=True, type=Path)
    parser.add_argument("--candidate-gate", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        inputs = [json.loads(path.read_text(encoding="utf-8")) for path in
                  (args.baseline_report, args.candidate_report, args.baseline_gate, args.candidate_gate)]
        if not all(isinstance(value, dict) for value in inputs):
            raise ValueError("all input JSON roots must be objects")
        result = summarize_paired_evaluation(*inputs, bootstrap_samples=args.bootstrap_samples, seed=args.seed)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result.get("comparable") else 1
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
