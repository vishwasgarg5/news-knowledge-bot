#!/usr/bin/env python3
"""Build and verify a self-contained, offline policy-evaluation evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ARTIFACTS = (
    "comparison", "baseline_audit", "candidate_audit", "regression_gate",
    "release_decision", "uncertainty_summary",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_object(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value, _sha256(raw)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_artifacts(values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    comparison = values["comparison"]
    base = values["baseline_audit"]
    candidate = values["candidate_audit"]
    regression = values["regression_gate"]
    decision = values["release_decision"]
    uncertainty = values["uncertainty_summary"]

    _require(comparison.get("comparable") is True and comparison.get("status") == "comparable",
             "comparison must be comparable")
    _require(base.get("passed") is True and base.get("status") == "pass",
             "baseline quality audit must pass")
    _require(candidate.get("passed") is True and candidate.get("status") == "pass",
             "candidate quality audit must pass")
    _require(regression.get("passed") is True and regression.get("status") == "pass",
             "regression gate must pass")
    base_policy, candidate_policy = base.get("policy_version"), candidate.get("policy_version")
    _require(isinstance(base_policy, str) and bool(base_policy.strip()) and
             isinstance(candidate_policy, str) and bool(candidate_policy.strip()) and
             base_policy != candidate_policy, "two distinct policy versions are required")
    for name, artifact in (("comparison", comparison), ("regression_gate", regression),
                           ("release_decision", decision)):
        _require(artifact.get("baseline_policy_version") == base_policy and
                 artifact.get("candidate_policy_version") == candidate_policy,
                 f"{name} policy identifiers do not match the quality audits")
    _require(decision.get("decision") in {"GO", "NO-GO"}, "release decision must be GO or NO-GO")
    _require(uncertainty.get("summary_schema_version") == "1.0" and
             uncertainty.get("status") == "complete" and uncertainty.get("comparable") is True,
             "uncertainty summary must be complete and comparable")
    cohort = uncertainty.get("cohort")
    _require(isinstance(cohort, dict) and isinstance(cohort.get("fingerprint_sha256"), str)
             and len(cohort["fingerprint_sha256"]) == 64,
             "uncertainty summary must include a cohort SHA-256 fingerprint")
    _require(cohort.get("baseline_policy_version") == base_policy and
             cohort.get("candidate_policy_version") == candidate_policy,
             "uncertainty cohort policy identifiers do not match the quality audits")
    if decision["decision"] == "GO":
        intervals = uncertainty.get("paired_bootstrap", {}).get("intervals", {})
        _require(uncertainty.get("improvement_claim") == "supported_on_this_cohort_only" and
                 all(isinstance(intervals.get(metric), dict) and
                     intervals[metric].get("status") == "candidate_higher"
                     for metric in ("inclusion_precision", "inclusion_recall")),
                 "GO conflicts with uncertainty evidence: precision and recall intervals must both be above zero")
    return {
        "baseline_policy_version": base_policy,
        "candidate_policy_version": candidate_policy,
        "cohort_fingerprint_sha256": cohort["fingerprint_sha256"],
        "release_decision": decision["decision"],
        "improvement_claim": uncertainty.get("improvement_claim"),
    }


def build_bundle(paths: dict[str, Path], history_path: Path | None = None) -> dict[str, Any]:
    missing = [name for name in ARTIFACTS if name not in paths or not paths[name].is_file()]
    _require(not missing, "required evidence artifact(s) missing: " + ", ".join(missing))
    values: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for name in ARTIFACTS:
        values[name], hashes[name] = _read_object(paths[name])
    identity = _validate_artifacts(values)
    integrity: dict[str, Any] = {
        "algorithm": "sha256",
        "source_artifacts_verified": len(ARTIFACTS),
        "source_artifact_sha256": hashes,
        "history_audit": {"status": "not_provided", "entry_count": 0, "warnings": [
            "No history file supplied; source artifact hashes and bundle fingerprint are still verified."
        ]},
    }
    if history_path is not None:
        from scripts.policy_evaluation_history import audit_history
        history, history_hash = _read_object(history_path)
        audit = audit_history(history)
        _require(audit.get("passed") is True, "history integrity audit failed")
        integrity["history_audit"] = {
            "status": audit.get("status"), "entry_count": audit.get("entry_count"),
            "warnings": audit.get("warnings", []), "history_sha256": history_hash,
        }
        integrity["history_payload"] = history
    bundle: dict[str, Any] = {
        "bundle_schema_version": "1.0",
        "bundle_type": "offline_policy_evaluation_evidence",
        "identity": identity,
        "artifacts": {name: {"sha256": hashes[name], "payload_sha256": _sha256(_canonical(values[name])), "payload": values[name]} for name in ARTIFACTS},
        "integrity": integrity,
        "operational_boundary": "Offline audit artifact only; does not deploy a policy, change production behavior, or send Telegram notifications.",
    }
    bundle["bundle_fingerprint_sha256"] = _sha256(_canonical(bundle))
    return bundle


def verify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    _require(bundle.get("bundle_schema_version") == "1.0", "unsupported bundle schema")
    expected = bundle.get("bundle_fingerprint_sha256")
    payload = {key: value for key, value in bundle.items() if key != "bundle_fingerprint_sha256"}
    _require(isinstance(expected, str) and expected == _sha256(_canonical(payload)),
             "bundle fingerprint mismatch; bundle may have been modified")
    artifacts = bundle.get("artifacts")
    _require(isinstance(artifacts, dict) and set(ARTIFACTS).issubset(artifacts),
             "bundle is missing required artifacts")
    for name in ARTIFACTS:
        item = artifacts[name]
        _require(isinstance(item, dict) and isinstance(item.get("payload"), dict),
                 f"{name} payload missing")
        actual = _sha256(_canonical(item["payload"]))
        # Source hash preserves original bytes; payload hash binds parsed JSON content.
        source_hash = item.get("sha256")
        _require(isinstance(source_hash, str) and len(source_hash) == 64
                 and all(ch in "0123456789abcdef" for ch in source_hash),
                 f"{name} source hash is invalid")
        _require(item.get("payload_sha256") == actual,
                 f"{name} payload hash mismatch; embedded evidence was modified")
    identity = _validate_artifacts({name: artifacts[name]["payload"] for name in ARTIFACTS})
    _require(identity == bundle.get("identity"), "bundle identity does not match its artifacts")
    audit = bundle.get("integrity", {}).get("history_audit", {})
    _require(isinstance(audit, dict) and audit.get("status") in {"pass", "not_provided"},
             "history audit status is invalid")
    return {"passed": True, "status": "pass", "artifact_count": len(ARTIFACTS),
            "bundle_fingerprint_sha256": expected, "history_audit_status": audit["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build an evidence bundle")
    for name in ARTIFACTS:
        build.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    build.add_argument("--history", type=Path)
    build.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify", help="verify a previously built bundle")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            paths = {name: getattr(args, name) for name in ARTIFACTS}
            result = build_bundle(paths, args.history)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({"status": "pass", "output": str(args.output),
                              "bundle_fingerprint_sha256": result["bundle_fingerprint_sha256"]}))
            return 0
        bundle, _ = _read_object(args.bundle)
        print(json.dumps(verify_bundle(bundle), indent=2))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
