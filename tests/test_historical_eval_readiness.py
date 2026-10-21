from scripts.audit_historical_eval_readiness import audit_snapshot


def test_current_style_snapshot_is_blocked_without_pool_or_truth_labels():
    result = audit_snapshot({
        "date": "2026-10-21",
        "intelligence_v5": {
            "stories": [{
                "headline": "Example event",
                "verification": {
                    "evidence": [{
                        "title": "Example event reported",
                        "source": "Example News",
                        "url": "https://example.com/story",
                        "published": "2026-10-21T08:00:00Z",
                        "summary": "An example summary.",
                    }]
                },
            }]
        },
    })

    assert result["story_records"] == 1
    assert result["saved_evidence_rows"] == 1
    assert result["saved_evidence_replay_possible"] is True
    assert result["labelled_historical_evaluation_ready"] is False
    assert "original_candidate_article_pool_not_persisted" in result["blockers"]
    assert "human_or_verified_story_labels_not_persisted" in result["blockers"]


def test_pool_and_explicit_label_are_required_for_labelled_evaluation():
    snapshot = {
        "date": "2026-10-21",
        "candidate_articles": [{
            "title": "Example event reported",
            "source": "Example News",
            "url": "https://example.com/story",
            "published": "2026-10-21T08:00:00Z",
            "summary": "An example summary.",
        }],
        "intelligence_v5": {
            "stories": [{
                "story_id": "event-1",
                "headline": "Example event",
                "ground_truth_label": True,
                "verification": {"evidence": []},
            }]
        },
    }

    result = audit_snapshot(snapshot)

    assert result["explicit_candidate_pool_available"] is True
    assert result["labelled_stories"] == 1
    assert result["labelled_historical_evaluation_ready"] is True
    assert result["blockers"] == []


def test_audit_does_not_infer_truth_from_verification_decision():
    result = audit_snapshot({
        "date": "2026-10-21",
        "candidate_articles": [{"title": "Example event"}],
        "intelligence_v5": {
            "stories": [{
                "story_id": "event-1",
                "headline": "Example event",
                "verification": {"verified": True, "evidence": []},
            }]
        },
    })

    assert result["labelled_stories"] == 0
    assert result["labelled_historical_evaluation_ready"] is False
    assert "human_or_verified_story_labels_not_persisted" in result["blockers"]


def test_malformed_story_container_is_reported_as_missing_records():
    result = audit_snapshot({"date": "2026-10-21", "intelligence_v5": {"stories": None}})

    assert result["story_records"] == 0
    assert result["saved_evidence_replay_possible"] is False
    assert "no_intelligence_v5_story_records" in result["blockers"]
