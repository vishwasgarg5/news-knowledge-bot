#!/usr/bin/env python3
"""Compare installed Ollama models on small, evidence-grounded news tasks.

This is a benchmark only: it never changes AI_MODEL or production configuration.
Install candidate models explicitly with Ollama, then pass their tags via --models.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DEFAULT_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
TASKS = [
    {
        "name": "supported_fact_extraction",
        "system": "Extract only facts stated in the evidence. Return compact JSON with keys fact and number.",
        "prompt": "Evidence: The central bank reduced the repo rate by 25 basis points on Tuesday. Return the action and number.",
        "required": ("25", "repo"),
        "forbidden": (),
    },
    {
        "name": "unsupported_claim_restraint",
        "system": "Use only the evidence. If no decision is stated, say so. Do not infer or invent. Return plain text.",
        "prompt": "Evidence: The monetary policy committee met on Tuesday. No decision or rate change is mentioned. What rate decision did it make?",
        "required": ("not stated",),
        "forbidden": ("cut the rate", "raised the rate", "reduced the rate", "increased the rate"),
    },
    {
        "name": "event_status_precision",
        "system": "Summarize only the procedural status explicitly stated. Do not infer an outcome.",
        "prompt": "Evidence: The High Court issued a notice to the company and scheduled the next hearing for 12 November. State the case status.",
        "required": ("notice",),
        "forbidden": ("convicted", "found guilty", "ruled against", "case dismissed"),
    },
    {
        "name": "uncertainty_preservation",
        "system": "Preserve uncertainty. Never turn allegations into established facts.",
        "prompt": "Evidence: Police said they are investigating an allegation that a contractor falsified records. Describe what is known.",
        "required": ("allegation",),
        "forbidden": ("falsified records", "the contractor falsified"),
    },
]


def score_response(task: dict, response: str) -> dict:
    normalized = response.casefold()
    missing = [term for term in task["required"] if term.casefold() not in normalized]
    violations = [term for term in task["forbidden"] if term.casefold() in normalized]
    return {"passed": not missing and not violations, "missing": missing, "violations": violations}


def _json_request(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
    with urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def benchmark_model(model: str, base_url: str = DEFAULT_URL) -> dict:
    results = []
    total_seconds = 0.0
    for task in TASKS:
        start = time.perf_counter()
        try:
            payload = _json_request(base_url + "/api/generate", {
                "model": model,
                "system": task["system"],
                "prompt": task["prompt"],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 120},
            })
            answer = str(payload.get("response", "")).strip()
            elapsed = time.perf_counter() - start
            total_seconds += elapsed
            grade = score_response(task, answer)
            results.append({"task": task["name"], "seconds": round(elapsed, 2), "response": answer, **grade})
        except (TimeoutError, OSError, ValueError, HTTPError, URLError) as exc:
            results.append({"task": task["name"], "passed": False, "error": str(exc)[:240]})
    passed = sum(bool(item.get("passed")) for item in results)
    return {
        "model": model,
        "passed": passed,
        "total": len(TASKS),
        "pass_rate": round(passed / len(TASKS), 3),
        "average_seconds": round(total_seconds / max(1, len(results)), 2),
        "tasks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="Comma-separated tags already installed in Ollama")
    parser.add_argument("--url", default=DEFAULT_URL, help="Ollama base URL (default: %(default)s)")
    args = parser.parse_args()
    try:
        installed = {item.get("name", "") for item in _json_request(args.url.rstrip("/") + "/api/tags").get("models", [])}
    except (TimeoutError, OSError, ValueError, HTTPError, URLError) as exc:
        parser.error(f"Cannot reach Ollama: {exc}")
    requested = [name.strip() for name in args.models.split(",") if name.strip()]
    missing = [name for name in requested if name not in installed]
    if missing:
        parser.error("Models are not installed: " + ", ".join(missing) + ". Pull them with ollama pull before benchmarking.")
    reports = [benchmark_model(name, args.url.rstrip("/")) for name in requested]
    reports.sort(key=lambda report: (-report["pass_rate"], report["average_seconds"]))
    print(json.dumps({"benchmark": "news-evidence-contract-v1", "promotion_policy": "benchmark only; no automatic production model switch", "results": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
