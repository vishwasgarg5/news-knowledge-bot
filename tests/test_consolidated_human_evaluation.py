from scripts.consolidate_human_evaluation import consolidate_reviews


def review(candidate_id, label, reviewer):
    return {
        "candidate_id": candidate_id,
        "disposition": "included",
        "title": "Example headline",
        "source": "Publisher",
        "url": f"https://example.com/{candidate_id}",
        "published_at": "2026-10-21T09:00:00+05:30",
        "summary": "Evidence summary",
        "relevance_label": label,
        "reviewer_id": reviewer,
        "reviewed_at": "2026-10-21T10:00:00+05:30",
        "rationale": "Independent review rationale.",
    }


def queue(path, reviews):
    return (path, {
        "run_id": "run-1",
        "sampling_method": "deterministic_stratified_by_disposition",
        "sampling_seed": "seed-1",
        "strata": {"included": {"selected": len(reviews)}},
        "reviews": reviews,
    })


def test_consolidated_report_keeps_disagreement_unresolved_without_adjudication():
    report = consolidate_reviews([
        queue("a.json", [review("c1", "relevant", "reviewer-a")]),
        queue("b.json", [review("c1", "not_relevant", "reviewer-b")]),
    ])

    assert report["review_disagreement_count"] == 1
    assert report["unresolved_candidate_count"] == 1
    assert report["candidate_summaries"][0]["status"] == "unresolved_disagreement"
    assert report["adjudications_accepted"] == 0


def test_explicit_valid_adjudication_resolves_status_and_preserves_audit_trail():
    adjudications = {"adjudications": [{
        "candidate_id": "c1",
        "final_label": "relevant",
        "adjudicator_id": "senior-reviewer",
        "adjudicated_at": "2026-10-21T12:00:00+05:30",
        "rationale": "Primary source and target scope reviewed.",
    }]}
    report = consolidate_reviews([
        queue("a.json", [review("c1", "relevant", "reviewer-a")]),
        queue("b.json", [review("c1", "not_relevant", "reviewer-b")]),
    ], adjudications)

    row = report["candidate_summaries"][0]
    assert row["status"] == "adjudicated"
    assert row["adjudication"]["adjudicator_id"] == "senior-reviewer"
    assert report["review_disagreement_count"] == 1
    assert report["unresolved_candidate_count"] == 0


def test_invalid_adjudication_is_not_accepted_and_case_stays_unresolved():
    report = consolidate_reviews(
        [queue("a.json", [review("c1", "relevant", "reviewer-a")]),
         queue("b.json", [review("c1", "not_relevant", "reviewer-b")])],
        {"adjudications": [{
            "candidate_id": "c1", "final_label": "maybe", "adjudicator_id": "",
            "adjudicated_at": "not-a-time", "rationale": "",
        }]},
    )

    assert report["adjudications_accepted"] == 0
    assert report["unresolved_candidate_count"] == 1
    assert report["malformed_entries"][0]["issues"]


def test_report_flags_missing_evidence_uncertainty_and_sampling_metadata():
    row = review("c2", "uncertain", "reviewer-c")
    row["url"] = ""
    report = consolidate_reviews([queue("q.json", [row])])

    assert report["uncertain_candidate_count"] == 1
    assert report["evidence_gap_count"] == 1
    assert report["sampling_metadata"][0]["sampling_seed"] == "seed-1"
