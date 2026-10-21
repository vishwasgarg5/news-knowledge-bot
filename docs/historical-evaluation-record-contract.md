# Historical evaluation record contract

Use `docs/historical-evaluation-record-template.json` as a starting template and validate a completed record with:

```bash
python scripts/validate_evaluation_record.py path/to/record.json
pytest -q tests/test_evaluation_record_contract.py
```

## Contract requirements

- `schema_version` is currently `1.0`.
- Every run has a stable `run_id`, timezone-aware ISO-8601 `run_timestamp`, and immutable `policy_version`.
- `candidate_articles` retains both included and excluded candidates. Each candidate records a stable ID, title, source, URL, publication timestamp, summary, and disposition.
- `story_labels` records an independent review outcome: `supported`, `not_supported`, or `uncertain`. Each label needs a reviewer alias, timezone-aware review timestamp, and rationale.
- Production verification decisions are not truth labels. The validator will not derive labels from `verified`, confidence, source reputation, or ranking.
- Keep credentials and private personal data out of records. Use reviewer aliases rather than personal names.
- The template's URLs and claims are placeholders; replace them with real, reviewed data before evaluating anything.

## Operational boundary

This is an offline data-contract addition only. It does not create labels, fetch articles, change production decisions, modify the scheduled run, or send notifications. The existing readiness audit remains a separate snapshot-shape check; a schema-valid record is not proof that its labels are correct.


## Automatic candidate-pool capture

The production pipeline now writes a run-specific record to
`data/historical_evaluation_records/` after its candidate list has been prepared.
The capture includes collected articles, a deterministic candidate ID, source
metadata, whether the candidate entered the prepared candidate set, the run
timestamp, and a policy-version identifier (the `NEWS_POLICY_VERSION` setting
if supplied, otherwise the GitHub commit SHA when available).

Capture deliberately writes `story_labels: []` and
`labeling_status: "pending_review"`. It never converts the production
verification decision into a truth label. A reviewer must add independent
labels and complete missing source fields before the record is suitable for
evaluation. Capture errors are logged as warnings and do not alter ranking or
briefing delivery.

For repeatable policy naming, configure `NEWS_POLICY_VERSION` in the runtime
environment to an immutable policy identifier. The default commit reference is
a code revision marker, not a claim that the verification policy itself is
independently versioned.


## Review queue audit

Inspect captured records without modifying them:

```bash
python scripts/audit_evaluation_captures.py --json
```

The audit reports run IDs, candidate-pool size, included/excluded counts, label counts,
and missing candidate metadata. It never creates labels. Missing metadata is reported
for reviewer follow-up without failing routine validation CI; unreadable or malformed
JSON records are still reported as invalid. No accuracy metric should be computed until
the candidate records have been independently reviewed and the evaluation record
passes `scripts/validate_evaluation_record.py`.
