from __future__ import annotations

from copy import deepcopy
import json

from scripts.validate_blinded_review_packet import main, validate_packets


def packets():
    queue = {
        "packet_type": "blinded_candidate_relevance_review",
        "packet_version": "1.0",
        "sampling": {"seed": "seed-1"},
        "items": [
            {"item_id": "run::a", "review": {
                "relevance_label": "relevant", "reviewer_id": "reviewer-a",
                "reviewed_at": "2026-10-22T10:00:00+00:00",
                "rationale": "Evidence supports topical relevance.",
                "evidence_urls": ["https://example.com/evidence-a"],
            }},
            {"item_id": "run::b", "review": {
                "relevance_label": "not_relevant", "reviewer_id": "reviewer-b",
                "reviewed_at": "2026-10-22T11:00:00Z",
                "rationale": "Evidence does not match the target topic.",
                "evidence_urls": ["https://example.com/evidence-b"],
            }},
            {"item_id": "run::c", "review": {
                "relevance_label": "uncertain", "reviewer_id": "reviewer-a",
                "reviewed_at": "2026-10-22T12:00:00+00:00",
                "rationale": "Evidence is ambiguous.", "evidence_urls": [],
            }},
            {"item_id": "run::d", "review": {
                "relevance_label": "", "reviewer_id": "", "reviewed_at": "",
                "rationale": "", "evidence_urls": [],
            }},
        ],
    }
    key = {
        "packet_type": "candidate_review_answer_key",
        "packet_version": "1.0",
        "seed": "seed-1",
        "items": [
            {"item_id": "run::a", "pipeline_disposition": "included"},
            {"item_id": "run::b", "pipeline_disposition": "included"},
            {"item_id": "run::c", "pipeline_disposition": "excluded"},
            {"item_id": "run::d", "pipeline_disposition": "excluded"},
        ],
    }
    return queue, key


def test_validates_reviews_and_reports_only_definitive_binary_metrics():
    queue, key = packets()
    report = validate_packets(queue, key)

    assert report["valid"] is True
    assert report["completed_review_count"] == 3
    assert report["unreviewed_item_ids"] == ["run::d"]
    assert report["metric_eligible_review_count"] == 2
    assert report["confusion_matrix"] == {
        "true_positives": 1, "false_positives": 1,
        "true_negatives": 0, "false_negatives": 0,
    }
    assert report["precision"] == 0.5
    assert report["recall"] == 1.0


def test_rejects_malformed_review_and_missing_evidence_for_definitive_label():
    queue, key = packets()
    queue["items"][0]["review"]["reviewed_at"] = "2026-10-22T10:00:00"
    queue["items"][0]["review"]["evidence_urls"] = []
    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "reviewed_at_must_be_timezone_aware_iso8601:run::a" in report["errors"]
    assert "definitive_label_requires_evidence_url:run::a" in report["errors"]


def test_rejects_unblinded_queue_and_mismatched_answer_key():
    queue, key = packets()
    queue["items"][0]["disposition"] = "included"
    key["items"].pop()
    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "queue_not_blinded:run::a" in report["errors"]
    assert "queue_answer_key_item_ids_mismatch" in report["errors"]


def test_rejects_invalid_label_and_duplicate_item_ids():
    queue, key = packets()
    queue["items"][0]["review"]["relevance_label"] = "yes"
    queue["items"].append(deepcopy(queue["items"][0]))
    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "relevance_label_invalid:run::a" in report["errors"]
    assert "queue_item_id_duplicate:run::a" in report["errors"]


def test_duplicate_and_out_of_scope_are_not_scored_as_binary_predictions():
    queue, key = packets()
    queue["items"][0]["review"]["relevance_label"] = "relevant"
    key["items"][0]["pipeline_disposition"] = "duplicate"
    queue["items"][1]["review"]["relevance_label"] = "not_relevant"
    key["items"][1]["pipeline_disposition"] = "out_of_scope"
    report = validate_packets(queue, key)

    assert report["valid"] is True
    assert report["metric_eligible_review_count"] == 0
    assert report["precision"] is None
    assert report["recall"] is None



def test_rejects_malformed_sampling_metadata_without_crashing():
    queue, key = packets()
    queue["sampling"] = None

    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "sampling_metadata_invalid" in report["errors"]


def test_rejects_non_string_labels_and_dispositions_without_crashing():
    queue, key = packets()
    queue["items"][0]["review"]["relevance_label"] = ["relevant"]
    key["items"][1]["pipeline_disposition"] = ["included"]

    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "relevance_label_invalid:run::a" in report["errors"]
    assert "key_disposition_invalid:run::b" in report["errors"]


def test_rejects_malformed_url_authority_without_crashing():
    queue, key = packets()
    queue["items"][0]["review"]["evidence_urls"] = ["http://[invalid"]

    report = validate_packets(queue, key)

    assert report["valid"] is False
    assert "evidence_urls_must_be_http_urls:run::a" in report["errors"]



def test_completion_status_is_distinct_from_structural_validity():
    queue, key = packets()
    report = validate_packets(queue, key)

    assert report["valid"] is True
    assert report["complete"] is False
    queue["items"][3]["review"] = {
        "relevance_label": "uncertain", "reviewer_id": "reviewer-c",
        "reviewed_at": "2026-10-22T13:00:00+00:00",
        "rationale": "Evidence remains ambiguous.", "evidence_urls": [],
    }
    report = validate_packets(queue, key)
    assert report["valid"] is True
    assert report["complete"] is True


def test_cli_require_complete_fails_for_unreviewed_items(tmp_path):
    queue, key = packets()
    queue_path = tmp_path / "queue.json"
    key_path = tmp_path / "key.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    key_path.write_text(json.dumps(key), encoding="utf-8")

    assert main([str(queue_path), str(key_path), "--require-complete", "--json"]) == 1
    assert main([str(queue_path), str(key_path), "--json"]) == 0
