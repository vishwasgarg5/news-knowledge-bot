import copy
import hashlib
import json

import pytest

from scripts.build_policy_evidence_bundle import ARTIFACTS, build_bundle, verify_bundle


def fixture_artifacts(tmp_path, *, decision="GO", improvement="supported_on_this_cohort_only"):
    base = {"policy_version": "policy-v1", "status": "pass", "passed": True}
    candidate = {"policy_version": "policy-v2", "status": "pass", "passed": True}
    comparison = {"status": "comparable", "comparable": True,
                  "baseline_policy_version": "policy-v1", "candidate_policy_version": "policy-v2"}
    regression = {"status": "pass", "passed": True,
                  "baseline_policy_version": "policy-v1", "candidate_policy_version": "policy-v2"}
    release = {"decision": decision, "baseline_policy_version": "policy-v1",
               "candidate_policy_version": "policy-v2"}
    uncertainty = {
        "summary_schema_version": "1.0", "status": "complete", "comparable": True,
        "cohort": {"fingerprint_sha256": hashlib.sha256(b"cohort").hexdigest(),
                   "baseline_policy_version": "policy-v1", "candidate_policy_version": "policy-v2"},
        "improvement_claim": improvement,
        "paired_bootstrap": {"intervals": {
            "inclusion_precision": {"status": "candidate_higher"},
            "inclusion_recall": {"status": "candidate_higher"},
        }},
    }
    values = {"comparison": comparison, "baseline_audit": base, "candidate_audit": candidate,
              "regression_gate": regression, "release_decision": release,
              "uncertainty_summary": uncertainty}
    paths = {}
    for name, value in values.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[name] = path
    return paths


def test_build_bundle_is_self_contained_and_verifiable(tmp_path):
    bundle = build_bundle(fixture_artifacts(tmp_path))
    assert bundle["bundle_schema_version"] == "1.0"
    assert set(bundle["artifacts"]) == set(ARTIFACTS)
    assert bundle["integrity"]["source_artifacts_verified"] == len(ARTIFACTS)
    assert verify_bundle(bundle)["passed"] is True


def test_missing_required_artifact_blocks_bundle(tmp_path):
    paths = fixture_artifacts(tmp_path)
    del paths["uncertainty_summary"]
    with pytest.raises(ValueError, match="missing"):
        build_bundle(paths)


def test_policy_identifier_mismatch_blocks_bundle(tmp_path):
    paths = fixture_artifacts(tmp_path)
    value = json.loads(paths["comparison"].read_text())
    value["candidate_policy_version"] = "wrong-policy"
    paths["comparison"].write_text(json.dumps(value))
    with pytest.raises(ValueError, match="identifiers"):
        build_bundle(paths)


def test_go_requires_positive_precision_and_recall_uncertainty(tmp_path):
    paths = fixture_artifacts(tmp_path, improvement="not_supported")
    with pytest.raises(ValueError, match="conflicts with uncertainty"):
        build_bundle(paths)


def test_bundle_tampering_is_detected(tmp_path):
    bundle = build_bundle(fixture_artifacts(tmp_path))
    altered = copy.deepcopy(bundle)
    altered["artifacts"]["comparison"]["payload"]["comparable"] = False
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        verify_bundle(altered)


def test_no_go_can_bundle_complete_but_uncertain_evidence(tmp_path):
    paths = fixture_artifacts(tmp_path, decision="NO-GO", improvement="not_supported")
    bundle = build_bundle(paths)
    assert bundle["identity"]["release_decision"] == "NO-GO"
    assert verify_bundle(bundle)["passed"] is True


def test_payload_hash_detects_edit_even_if_outer_fingerprint_is_recomputed(tmp_path):
    bundle = build_bundle(fixture_artifacts(tmp_path))
    bundle["artifacts"]["comparison"]["payload"]["comparable"] = False
    # Simulate an editor who recomputes the outer fingerprint: the per-payload
    # digest still catches that the embedded artifact no longer matches its hash.
    from scripts.build_policy_evidence_bundle import _canonical, _sha256
    payload = {key: value for key, value in bundle.items() if key != "bundle_fingerprint_sha256"}
    bundle["bundle_fingerprint_sha256"] = _sha256(_canonical(payload))
    with pytest.raises(ValueError, match="payload hash mismatch"):
        verify_bundle(bundle)


def test_verifier_checks_original_source_bytes_when_directory_is_supplied(tmp_path):
    paths = fixture_artifacts(tmp_path)
    bundle = build_bundle(paths)
    assert verify_bundle(bundle, source_paths=paths)["passed"] is True
    paths["comparison"].write_text('{"comparable": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="source artifact hash mismatch"):
        verify_bundle(bundle, source_paths=paths)


def test_embedded_history_is_reaudited_during_verification(tmp_path):
    paths = fixture_artifacts(tmp_path)
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps({"history_schema_version": "1.0", "entries": []}), encoding="utf-8")
    bundle = build_bundle(paths, history_path)
    assert verify_bundle(bundle)["history_audit_status"] == "pass"
    bundle["integrity"]["history_payload"]["entries"].append({"run_id": "tampered"})
    from scripts.build_policy_evidence_bundle import _canonical, _sha256
    payload = {key: value for key, value in bundle.items() if key != "bundle_fingerprint_sha256"}
    bundle["bundle_fingerprint_sha256"] = _sha256(_canonical(payload))
    with pytest.raises(ValueError, match="history payload hash mismatch"):
        verify_bundle(bundle)


def test_bundle_build_is_deterministic_and_cli_round_trip_verifies_originals(tmp_path):
    import subprocess
    import sys

    paths = fixture_artifacts(tmp_path)
    script = "scripts/build_policy_evidence_bundle.py"
    outputs = [tmp_path / "bundle-a.json", tmp_path / "bundle-b.json"]
    common = [sys.executable, script, "build"]
    for output in outputs:
        command = common[:]
        for name, path in paths.items():
            command.extend(["--" + name.replace("_", "-"), str(path)])
        command.extend(["--output", str(output)])
        subprocess.run(command, check=True, capture_output=True, text=True)
    first = json.loads(outputs[0].read_text(encoding="utf-8"))
    second = json.loads(outputs[1].read_text(encoding="utf-8"))
    assert first == second
    checked = subprocess.run(
        [sys.executable, script, "verify", str(outputs[0]), "--artifact-dir", str(tmp_path)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(checked.stdout)["status"] == "pass"


def test_invalid_cohort_fingerprint_is_rejected(tmp_path):
    paths = fixture_artifacts(tmp_path)
    value = json.loads(paths["uncertainty_summary"].read_text(encoding="utf-8"))
    value["cohort"]["fingerprint_sha256"] = "g" * 64
    paths["uncertainty_summary"].write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="cohort SHA-256"):
        build_bundle(paths)
