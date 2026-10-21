#!/usr/bin/env python3
"""Offline shadow comparison of verification policies on explicitly labelled fixtures.

All cases are synthetic. Metrics validate policy behavior on these fixtures only;
they are not estimates of real-world news accuracy. No network or delivery calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.research import verify_article

def _published(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

def _article(title: str, source: str, url: str, hours_ago: float = 2, summary: str = "") -> dict[str, str]:
    return {"title": title, "source": source, "url": url, "published": _published(hours_ago), "summary": summary}

def labelled_cases() -> list[dict[str, Any]]:
    """Small, hand-labelled fixtures for known positive and negative evidence patterns."""
    return [
        {
            "id": "two-independent-matching-reports",
            "label": True,
            "story": {"headline": "Government approves new flood barrier after severe river flooding", "source": "Local News", "url": "https://local.example/flood", "published": _published(3), "summary": ""},
            "articles": [
                _article("Government approves new flood barrier after severe river flooding", "Reuters", "https://reuters.com/world/flood", summary="Officials confirmed the approval."),
                _article("New flood barrier approved by government following river flooding", "Associated Press", "https://apnews.com/article/flood", summary="The government approved a barrier after flooding."),
            ],
        },
        {
            "id": "unrelated-headline-shares-general-topic",
            "label": False,
            "story": {"headline": "Central bank raises benchmark interest rate after inflation accelerates", "source": "Local News", "url": "https://local.example/rates", "published": _published(3), "summary": ""},
            "articles": [
                _article("Technology company raises quarterly revenue forecast after demand accelerates", "Reuters", "https://reuters.com/technology/revenue", summary="The company raised its forecast."),
                _article("Central bank publishes annual financial stability report", "Associated Press", "https://apnews.com/article/stability", summary="The report reviewed financial conditions."),
            ],
        },
        {
            "id": "two-syndicated-copies-of-one-report",
            "label": False,
            "story": {"headline": "City approves new bridge after severe flood damage across northern region", "source": "Local News", "url": "https://local.example/bridge", "published": _published(3), "summary": ""},
            "articles": [
                _article("City approves new bridge after severe flood damage across northern region", "Publisher A", "https://publisher-a.example/bridge", summary="City officials approved the new bridge after severe flood damage across the northern region. Construction plans are expected next week."),
                _article("City approves new bridge after severe flood damage across northern region", "Publisher B", "https://publisher-b.example/bridge", summary="City officials approved the new bridge after severe flood damage across the northern region. Construction plans are expected next week."),
            ],
        },
        {
            "id": "only-one-independent-report",
            "label": True,
            "story": {"headline": "Regulator suspends licence of regional bank after audit", "source": "Local News", "url": "https://local.example/bank", "published": _published(3), "summary": ""},
            "articles": [
                _article("Regulator suspends licence of regional bank after audit", "Reuters", "https://reuters.com/business/bank", summary="The regulator announced the suspension after an audit."),
            ],
        },
        {
            "id": "matching-but-stale-evidence",
            "label": False,
            "story": {"headline": "Government signs new cross-border energy agreement", "source": "Local News", "url": "https://local.example/energy", "published": _published(3), "summary": ""},
            "articles": [
                _article("Government signs new cross-border energy agreement", "Reuters", "https://reuters.com/world/energy", hours_ago=120, summary="Officials announced the agreement."),
                _article("Government signs new cross-border energy agreement", "Associated Press", "https://apnews.com/article/energy", hours_ago=130, summary="Officials announced the agreement."),
            ],
        },
        {
            "id": "publisher-aliases-same-identity",
            "label": True,
            "story": {"headline": "City council approves new bridge funding after flood damage", "source": "Local News", "url": "https://local.example/bridge-funding", "published": _published(3), "summary": ""},
            "articles": [
                _article("City council approves new bridge funding after flood damage", "Reuters", "https://www.reuters.com/world/bridge-a"),
                _article("City council approves new bridge funding after flood damage", "Reuters.com", "https://www.reuters.com/world/bridge-b"),
            ],
        },
        {
            "id": "same-headline-distinct-independent-reporting",
            "label": True,
            "story": {"headline": "Government approves new flood barrier after severe river flooding", "source": "Local News", "url": "https://local.example/flood-independent", "published": _published(3), "summary": ""},
            "articles": [
                _article("Government approves new flood barrier after severe river flooding", "Reuters", "https://www.reuters.com/world/flood-a", summary="Officials said the barrier followed a new hydrology review and budget approval."),
                _article("Government approves new flood barrier after severe river flooding", "Associated Press", "https://apnews.com/article/flood-b", summary="Local authorities said construction will begin after a public procurement process."),
            ],
        },
        {
            "id": "conflicting-reporting-flags-contradiction",
            "label": False,
            "story": {"headline": "Regulator confirms regional bank licence remains active after audit", "source": "Local News", "url": "https://local.example/licence", "published": _published(3), "summary": "The regulator confirmed the licence remains active."},
            "articles": [
                _article("Regulator confirms regional bank licence remains active after audit", "Reuters", "https://www.reuters.com/business/licence", summary="The regulator denies reports that it suspended the bank licence and says the licence remains active."),
                _article("Regulator confirms regional bank licence remains active after audit", "Associated Press", "https://apnews.com/article/licence", summary="Officials say the bank's licence remains active following the audit."),
            ],
        },
        {
            "id": "derivative-primary-roundup",
            "label": False,
            "story": {"headline": "Daily news roundup: regulator suspends regional bank licence after audit", "source": "Daily News Roundup", "url": "https://digest.example/bank", "published": _published(3), "summary": ""},
            "articles": [
                _article("Regulator suspends regional bank licence after audit", "Reuters", "https://www.reuters.com/business/bank-roundup"),
                _article("Regulator suspends regional bank licence after audit", "Associated Press", "https://apnews.com/article/bank-roundup"),
            ],
        },
        {
            "id": "official-primary-source",
            "label": True,
            "story": {"headline": "Ministry announces revised national flood warning system", "source": "pib.gov.in", "url": "https://pib.gov.in/example", "published": _published(2), "summary": ""},
            "articles": [],
        },
    ]

def _metrics(labels: list[bool], predictions: list[bool]) -> dict[str, Any]:
    tp = sum(y and p for y, p in zip(labels, predictions))
    fp = sum((not y) and p for y, p in zip(labels, predictions))
    fn = sum(y and (not p) for y, p in zip(labels, predictions))
    tn = sum((not y) and (not p) for y, p in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}

def evaluate() -> dict[str, Any]:
    cases = labelled_cases()
    labels: list[bool] = []
    baseline: list[bool] = []
    candidate: list[bool] = []
    rows = []
    for case in cases:
        result = verify_article(case["story"], case["articles"])
        independent = int(result.get("independent_sources", 0) or 0)
        official = bool(result.get("official_source"))
        primary_fresh = bool(result.get("primary_fresh"))
        contradiction = bool(result.get("contradiction_flag"))
        derivative = bool(result.get("primary_derivative"))
        # Baseline mirrors the current tier semantics: any independent report or official primary.
        baseline_accept = official or independent >= 1
        # Candidate shadow gate: official primary OR two independent fresh reports,
        # fresh primary, and no recorded contradiction/roundup primary.
        candidate_accept = official or (
            independent >= 2 and primary_fresh and not contradiction and not derivative
        )
        labels.append(bool(case["label"]))
        baseline.append(baseline_accept)
        candidate.append(candidate_accept)
        rows.append({
            "case": case["id"], "label": bool(case["label"]),
            "baseline_accept": baseline_accept, "candidate_accept": candidate_accept,
            "independent_sources": independent, "tier": result.get("verification"),
            "primary_fresh": primary_fresh, "contradiction": contradiction,
            "primary_derivative": derivative,
        })
    return {
        "evaluation_type": "synthetic_fixture_shadow_only",
        "cases": len(cases),
        "label_source": "hand-authored test fixtures; not historical ground truth",
        "baseline_metrics": _metrics(labels, baseline),
        "candidate_metrics": _metrics(labels, candidate),
        "cases_detail": rows,
        "limitations": [
            "Synthetic fixtures do not estimate real-world precision, recall, or F1.",
            "The baseline and candidate run against the same fixture article pools.",
            "Saved production snapshots do not retain all original candidate articles, so historical replay cannot reliably calculate labelled precision/F1.",
            "Candidate policy is diagnostic only and does not change production verification or ranking.",
        ],
    }

def main() -> int:
    print(json.dumps(evaluate(), indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
