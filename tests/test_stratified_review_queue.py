import json

import pytest

from scripts.create_stratified_review_queue import select_review_queue


def sample_record():
    rows = []
    for disposition, count in (("included", 4), ("excluded", 5), ("duplicate", 2), ("out_of_scope", 1)):
        for index in range(count):
            rows.append({
                "candidate_id": f"{disposition}-{index}",
                "title": f"{disposition} title {index}",
                "source": "Publisher",
                "url": f"https://example.com/{disposition}/{index}",
                "published_at": "2026-10-21T09:00:00+05:30",
                "summary": "Example summary",
                "disposition": disposition,
            })
    return {"run_id": "run-1", "policy_version": "policy-v1", "candidate_articles": rows,
            "candidate_reviews": [{"candidate_id": "included-0", "relevance_label": "relevant"}]}


def test_queue_selects_each_disposition_reproducibly_and_respects_cap():
    record = sample_record()
    first = select_review_queue(record, per_disposition=2, seed="fixed-seed")
    second = select_review_queue(record, per_disposition=2, seed="fixed-seed")

    assert first == second
    assert len(first["reviews"]) == 7
    assert first["strata"]["included"]["eligible_unreviewed"] == 3
    assert first["strata"]["included"]["selected"] == 2
    assert first["strata"]["excluded"]["selected"] == 2
    assert first["strata"]["duplicate"]["selected"] == 2
    assert first["strata"]["out_of_scope"]["selected"] == 1
    assert "included-0" not in {row["candidate_id"] for row in first["reviews"]}


def test_queue_contains_blank_review_fields_and_never_autolabels():
    queue = select_review_queue(sample_record(), per_disposition=1)
    assert all(row["relevance_label"] == "" for row in queue["reviews"])
    assert all(row["reviewer_id"] == "" for row in queue["reviews"])
    assert all(row["reviewed_at"] == "" for row in queue["reviews"])
    assert all(row["rationale"] == "" for row in queue["reviews"])
    assert queue["sampling_method"] == "deterministic_stratified_by_disposition"


def test_queue_rejects_nonpositive_sample_size():
    with pytest.raises(ValueError, match="at least 1"):
        select_review_queue(sample_record(), per_disposition=0)


def test_queue_can_be_serialized():
    queue = select_review_queue(sample_record(), per_disposition=1)
    assert json.loads(json.dumps(queue))["run_id"] == "run-1"
