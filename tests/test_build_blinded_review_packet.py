from __future__ import annotations

import json

import pytest

from scripts.build_blinded_review_packet import build_packet, main


def make_record(run_id, candidates):
    return {"run_id": run_id, "policy_version": "policy-test", "candidate_articles": candidates}


def candidate(candidate_id, disposition, **fields):
    return {
        "candidate_id": candidate_id,
        "disposition": disposition,
        "title": fields.get("title", f"Title {candidate_id}"),
        "source": "Example Publisher",
        "url": f"https://example.com/{candidate_id}",
        "published_at": "2026-10-22T08:00:00+00:00",
        "summary": fields.get("summary", "Evidence summary supplied by capture."),
    }


def test_packet_blinds_pipeline_disposition_and_keeps_answer_key_separate():
    records = [(
        "capture.json",
        make_record("run-1", [
            candidate("a", "included"),
            candidate("b", "excluded"),
            candidate("c", "duplicate"),
            candidate("d", "out_of_scope"),
        ]),
    )]

    queue, key = build_packet(records, sample_per_disposition=10, seed="stable")

    assert len(queue["items"]) == 4
    assert all("disposition" not in item and "pipeline_disposition" not in item for item in queue["items"])
    assert all(item["review"]["relevance_label"] == "" for item in queue["items"])
    assert all(item["review"]["rationale"] == "" for item in queue["items"])
    assert {item["pipeline_disposition"] for item in key["items"]} == {
        "included", "excluded", "duplicate", "out_of_scope"
    }
    assert queue["sampling"]["selected_by_disposition"]["included"] == 1


def test_sampling_is_deterministic_and_stratified():
    candidates = [candidate(str(i), "included" if i % 2 == 0 else "excluded") for i in range(20)]
    records = [("capture.json", make_record("run-1", candidates))]

    queue_a, key_a = build_packet(records, sample_per_disposition=3, seed="same")
    queue_b, key_b = build_packet(records, sample_per_disposition=3, seed="same")

    assert queue_a == queue_b
    assert key_a == key_b
    assert queue_a["sampling"]["selected_by_disposition"]["included"] == 3
    assert queue_a["sampling"]["selected_by_disposition"]["excluded"] == 3
    assert len(queue_a["items"]) == 6


def test_missing_evidence_is_not_fabricated_and_candidate_ids_are_namespaced():
    records = [
        ("one.json", make_record("run-a", [candidate("same", "included", summary="")])),
        ("two.json", make_record("run-b", [candidate("same", "excluded", summary="")])),
    ]

    queue, _ = build_packet(records, sample_per_disposition=1, seed="s")

    assert {item["item_id"] for item in queue["items"]} == {"run-a::same", "run-b::same"}
    assert all(item["summary"] == "" for item in queue["items"])


@pytest.mark.parametrize("records, message", [
    ([], "no JSON records"),
    ([("bad.json", {"candidate_articles": []})], "run_id"),
    ([("bad.json", make_record("run", [candidate("x", "unknown")]))], "invalid disposition"),
    ([("bad.json", make_record("run", [candidate("", "included")]))], "candidate_id"),
    ([("a.json", make_record("run", [candidate("x", "included")])),
      ("b.json", make_record("run", [candidate("x", "excluded")]))], "duplicate review item id"),
])
def test_invalid_input_is_rejected(records, message):
    with pytest.raises(ValueError, match=message):
        build_packet(records, sample_per_disposition=2)


def test_cli_writes_distinct_queue_and_key(tmp_path):
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(make_record("run-1", [candidate("a", "included")])), encoding="utf-8")
    queue_path = tmp_path / "out" / "queue.json"
    key_path = tmp_path / "out" / "key.json"

    assert main([str(record_path), "--queue-output", str(queue_path), "--key-output", str(key_path)]) == 0
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    assert "pipeline_disposition" not in queue["items"][0]
    assert key["items"][0]["pipeline_disposition"] == "included"



@pytest.mark.parametrize("records, message", [
    ([("bad.json", None)], "record root must be an object"),
    ([("bad.json", {"run_id": "run", "candidate_articles": None})], "candidate_articles must be a list"),
    ([("bad.json", make_record("run", [candidate("x", ["included"])]))], "invalid disposition"),
])
def test_builder_rejects_malformed_record_shapes(records, message):
    with pytest.raises(ValueError, match=message):
        build_packet(records)


@pytest.mark.parametrize("sample_cap", [0, -1, 1.5, "2", True])
def test_builder_requires_positive_integer_sample_cap(sample_cap):
    records = [("record.json", make_record("run", [candidate("x", "included")]))]
    with pytest.raises(ValueError, match="sample_per_disposition"):
        build_packet(records, sample_per_disposition=sample_cap)


@pytest.mark.parametrize("same_output", ["queue", "key"])
def test_cli_refuses_to_overwrite_input_record(tmp_path, same_output):
    record_path = tmp_path / "record.json"
    original = json.dumps(make_record("run-1", [candidate("a", "included")]))
    record_path.write_text(original, encoding="utf-8")
    queue_path = record_path if same_output == "queue" else tmp_path / "queue.json"
    key_path = record_path if same_output == "key" else tmp_path / "key.json"

    with pytest.raises(SystemExit) as exc:
        main([str(record_path), "--queue-output", str(queue_path), "--key-output", str(key_path)])
    assert exc.value.code == 2
    assert record_path.read_text(encoding="utf-8") == original


def test_cli_refuses_outputs_inside_input_directory(tmp_path):
    input_dir = tmp_path / "records"
    input_dir.mkdir()
    (input_dir / "record.json").write_text(
        json.dumps(make_record("run-1", [candidate("a", "included")])), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc:
        main([str(input_dir), "--queue-output", str(input_dir / "queue.json"),
              "--key-output", str(tmp_path / "key.json")])
    assert exc.value.code == 2
    assert not (input_dir / "queue.json").exists()
