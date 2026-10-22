from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.review_evaluation_capture import apply_human_label, write_record_atomically


def sample_record():
    return {
        "run_id": "run-1",
        "labeling_status": "pending_review",
        "candidate_articles": [
            {"candidate_id": "candidate-a", "title": "Reported event", "url": "https://news.example/a"},
            {"candidate_id": "candidate-b", "title": "Independent follow-up", "url": "https://wire.example/b"},
        ],
        "story_labels": [],
    }


def test_human_label_requires_explicit_evidence_and_references_real_candidates():
    updated = apply_human_label(
        sample_record(), story_id="story-1", label="supported", reviewer="reviewer-1",
        rationale="Both sources independently report the event.",
        candidate_ids=["candidate-a", "candidate-b"],
        evidence_urls=["https://official.example/statement"],
        reviewed_at="2026-10-22T10:00:00Z",
    )

    label = updated["story_labels"][0]
    assert label["label"] == "supported"
    assert label["review_method"] == "human"
    assert label["candidate_ids"] == ["candidate-a", "candidate-b"]
    assert label["evidence_urls"] == ["https://official.example/statement"]
    assert label["reviewed_at"] == "2026-10-22T10:00:00Z"
    assert updated["labeling_status"] == "reviewed"


@pytest.mark.parametrize("kwargs", [
    {"label": "supported", "evidence_urls": []},
    {"label": "unsupported", "evidence_urls": []},
    {"label": "invented", "evidence_urls": ["https://official.example"]},
    {"label": "supported", "evidence_urls": ["javascript:alert(1)"]},
])
def test_human_label_rejects_invalid_labels_or_missing_independent_evidence(kwargs):
    args = {"label": "supported", "evidence_urls": ["https://official.example/statement"]}
    args.update(kwargs)
    with pytest.raises(ValueError):
        apply_human_label(
            sample_record(), story_id="story-1", reviewer="reviewer-1",
            rationale="Reviewed against source material.", candidate_ids=["candidate-a"],
            **args,
        )


def test_human_label_rejects_unknown_candidate_ids_and_duplicate_labels():
    record = sample_record()
    args = dict(story_id="story-1", label="uncertain", reviewer="reviewer-1",
                rationale="Evidence is inconclusive.", candidate_ids=["missing-candidate"], evidence_urls=[])
    with pytest.raises(ValueError, match="not found"):
        apply_human_label(record, **args)

    args["candidate_ids"] = ["candidate-a"]
    labelled = apply_human_label(record, **args)
    with pytest.raises(ValueError, match="already has a label"):
        apply_human_label(labelled, **args)


def test_label_amendment_requires_explicit_replace_and_atomic_writer(tmp_path):
    record = sample_record()
    first = apply_human_label(
        record, story_id="story-1", label="uncertain", reviewer="reviewer-1",
        rationale="Need another independent source.", candidate_ids=["candidate-a"], evidence_urls=[],
    )
    revised = apply_human_label(
        first, story_id="story-1", label="supported", reviewer="reviewer-2",
        rationale="Official notice independently confirms the event.", candidate_ids=["candidate-a"],
        evidence_urls=["https://official.example/notice"], replace_existing=True,
    )
    path = tmp_path / "run.json"
    write_record_atomically(path, revised)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["story_labels"]) == 1
    assert saved["story_labels"][0]["label"] == "supported"
    assert saved["story_labels"][0]["reviewer"] == "reviewer-2"
    assert saved["labeling_status"] == "in_progress"



def test_record_is_marked_reviewed_only_when_every_candidate_is_labelled():
    record = sample_record()
    first = apply_human_label(
        record, story_id="story-a", label="supported", reviewer="reviewer-1",
        rationale="Official notice confirms the event.", candidate_ids=["candidate-a"],
        evidence_urls=["https://official.example/a"],
    )
    assert first["labeling_status"] == "in_progress"
    complete = apply_human_label(
        first, story_id="story-b", label="uncertain", reviewer="reviewer-1",
        rationale="No independent confirmation was found in reviewed material.",
        candidate_ids=["candidate-b"], evidence_urls=[],
    )
    assert complete["labeling_status"] == "reviewed"
