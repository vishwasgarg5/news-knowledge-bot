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
