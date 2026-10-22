import json

from scripts.policy_evaluation_history import append_history, build_history_entry, build_trends


def artifacts():
    comparison = {
        "status": "comparable",
        "metric_deltas_candidate_minus_baseline": {"inclusion_precision": 0.1},
        "baseline_metrics": {"inclusion_precision": 0.5, "inclusion_recall": 0.6},
        "candidate_metrics": {
            "inclusion_precision": 0.6, "inclusion_recall": 0.7,
            "false_positives": 2, "missed_relevant_candidates": 1,
        },
    }
    base = {
        "policy_version": "policy-v1", "status": "pass",
        "checks": [{"name": "minimum_review_coverage", "observed": 0.8, "required": 0.5}],
    }
    candidate = {
        "policy_version": "policy-v2", "status": "pass",
        "checks": [{"name": "minimum_review_coverage", "observed": 0.9, "required": 0.5}],
    }
    regression = {"status": "pass", "passed": True}
    decision = {"decision": "GO", "blockers": []}
    hashes = {"comparison": "a" * 64, "baseline_audit": "b" * 64,
              "candidate_audit": "c" * 64, "regression_gate": "d" * 64,
              "release_decision": "e" * 64}
    return comparison, base, candidate, regression, decision, hashes


def test_history_entry_has_stable_id_hashes_and_metrics():
    entry = build_history_entry(*artifacts(), recorded_at="2026-10-22T09:00:00+05:30")
    assert entry["run_id"]
    assert entry["entry_sha256"]
    assert entry["candidate_metrics"]["inclusion_precision"] == 0.6
    assert entry["release_decision"] == "GO"
    assert entry["candidate_review_coverage"] == 0.9


def test_append_history_is_idempotent_for_same_artifacts(tmp_path):
    history_path = tmp_path / "history.json"
    first = build_history_entry(*artifacts(), recorded_at="2026-10-22T09:00:00+05:30")
    second = build_history_entry(*artifacts(), recorded_at="2026-10-22T10:00:00+05:30")
    assert first["run_id"] == second["run_id"]
    assert append_history(history_path, first) is True
    assert append_history(history_path, second) is False
    data = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1


def test_trends_preserve_order_and_warn_about_incomparable_cohorts():
    entry = build_history_entry(*artifacts(), recorded_at="2026-10-22T09:00:00+05:30")
    result = build_trends({"entries": [entry]})
    assert result["entry_count"] == 1
    assert result["latest"]["release_decision"] == "GO"
    assert any("different policy pairs" in warning for warning in result["warnings"])


def test_history_rejects_invalid_existing_schema(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"history_schema_version":"99","entries":[]}', encoding="utf-8")
    entry = build_history_entry(*artifacts(), recorded_at="2026-10-22T09:00:00+05:30")
    try:
        append_history(path, entry)
    except ValueError as exc:
        assert "unsupported or invalid schema" in str(exc)
    else:
        raise AssertionError("invalid history schema should be rejected")
