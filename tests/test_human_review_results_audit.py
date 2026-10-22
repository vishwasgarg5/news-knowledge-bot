import json

import pytest

from scripts.audit_human_review_results import audit_review_queues


def queue(path_label, reviews, run_id="run-1"):
    return (path_label, {
        "run_id": run_id,
        "sampling_method": "deterministic_stratified_by_disposition",
        "sampling_seed": "seed-1",
        "per_disposition_cap": 3,
        "strata": {"included": {"selected": 2}},
        "reviews": reviews,
    })


def review(candidate_id, disposition, label, reviewer, **overrides):
    row = {
        "candidate_id": candidate_id,
        "disposition": disposition,
        "title": "Example story",
        "source": "Publisher",
        "url": f"https://example.com/{candidate_id}",
        "published_at": "2026-10-21T10:00:00+05:30",
        "summary": "Evidence summary",
        "relevance_label": label,
        "reviewer_id": reviewer,
        "reviewed_at": "2026-10-21T11:00:00+05:30",
        "rationale": "Reviewed independently.",
    }
    row.update(overrides)
    return row


def test_audit_flags_disagreement_and_uncertainty_across_reviewers():
    a = queue("reviewer-a.json", [
        review("c1", "included", "relevant", "reviewer-a"),
        review("c2", "excluded", "uncertain", "reviewer-a"),
    ])
    b = queue("reviewer-b.json", [
        review("c1", "included", "not_relevant", "reviewer-b"),
        review("c2", "excluded", "uncertain", "reviewer-b"),
    ])

    report = audit_review_queues([a, b], min_reviews_per_disposition=1)

    assert report["disagreement_count"] == 1
    assert report["disagreements"][0]["candidate_id"] == "c1"
    assert report["uncertain_candidate_count"] == 1
    assert report["uncertain_candidates"][0]["candidate_id"] == "c2"
    assert report["sampling_metadata"][0]["sampling_seed"] == "seed-1"


def test_audit_flags_missing_evidence_and_incomplete_review_fields():
    item = review("c1", "included", "", "")
    item["url"] = ""
    item["summary"] = ""
    item["reviewed_at"] = ""
    item["rationale"] = ""
    report = audit_review_queues([queue("q.json", [item])], min_reviews_per_disposition=2)

    assert report["missing_candidate_evidence_count"] == 1
    assert set(report["missing_candidate_evidence"][0]["missing_fields"]) == {"url", "summary"}
    assert report["incomplete_review_count"] == 1
    assert set(report["incomplete_reviews"][0]["missing_fields"]) == {
        "relevance_label", "reviewer_id", "reviewed_at", "rationale"
    }
    assert report["disposition_coverage"]["included"]["under_reviewed"] is True
    assert report["disposition_coverage"]["excluded"]["under_reviewed"] is True


def test_audit_does_not_call_different_reviews_adjudicated_truth():
    a = queue("a.json", [review("c1", "included", "relevant", "reviewer-a")])
    b = queue("b.json", [review("c1", "included", "not_relevant", "reviewer-b")])

    report = audit_review_queues([a, b])

    assert report["disagreement_count"] == 1
    assert any("not automatically an adjudicated error" in item for item in report["limitations"])


def test_audit_flags_duplicate_reviewer_entries_instead_of_treating_them_as_independent():
    a = queue("copy-a.json", [
        review("c1", "included", "relevant", "reviewer-a"),
    ])
    b = queue("copy-b.json", [
        review("c1", "included", "not_relevant", "reviewer-a"),
        review("c1", "included", "relevant", "reviewer-b"),
    ])

    report = audit_review_queues([a, b], min_reviews_per_disposition=1)

    assert report["disagreement_count"] == 1
    assert report["duplicate_reviewer_entry_count"] == 1
    duplicate = report["duplicate_reviewer_entries"][0]
    assert duplicate["candidate_id"] == "c1"
    assert duplicate["reviewer_id"] == "reviewer-a"
    assert duplicate["entry_count"] == 2
    assert duplicate["labels"] == ["not_relevant", "relevant"]


def test_audit_requires_positive_under_reviewed_threshold():
    with pytest.raises(ValueError, match="at least 1"):
        audit_review_queues([], min_reviews_per_disposition=0)
