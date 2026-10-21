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


## Candidate relevance reviews and offline metrics

Claim truth and candidate relevance answer different questions. Keep them separate:

- `story_labels` answers whether the story's core claim is independently supported.
- `candidate_reviews` answers whether a candidate belongs in the target news briefing. Each entry requires `candidate_id`, `relevance_label` (`relevant`, `not_relevant`, or `uncertain`), reviewer alias, timezone-aware review timestamp, and rationale.
- Candidate reviews must refer to IDs in that record's `candidate_articles`. Do not label candidates based on the production verification status alone.

After adding independent candidate reviews, validate and calculate offline metrics:

```bash
python scripts/validate_evaluation_record.py data/historical_evaluation_records/RECORD.json
python scripts/evaluate_historical_records.py data/historical_evaluation_records/
pytest -q tests/test_historical_record_metrics.py
```

The evaluator reports inclusion precision, recall, false positives (included but independently labelled not relevant), missed relevant candidates (excluded but labelled relevant), and candidate metadata field coverage. Uncertain reviews and duplicate/out-of-scope dispositions do not enter the precision/recall denominators. Unreviewed candidates are not treated as negatives. With no explicit candidate relevance labels, precision and recall are reported as null rather than guessed. Results are offline descriptive metrics, not proof of real-world performance or label quality.


## Review coverage is part of every result

The offline evaluator reports the number and share of candidates with explicit relevance
reviews, both overall and by disposition (included, excluded, duplicate, and
out_of_scope). Aggregate coverage is pooled across schema-valid records only.

Do not interpret precision/recall from a small or convenience-selected review sample as
unbiased system accuracy. Review included and excluded candidates, record the sampling
method outside the metric result, and expand review coverage when a disposition group
has few or no reviewed candidates. Coverage describes what was reviewed; it does not
prove the reviewed subset is representative.


## Stratified human-review queue

Create a deterministic review queue from a captured record without editing the source record:

```bash
python scripts/create_stratified_review_queue.py data/historical_evaluation_records/RECORD.json --per-disposition 10 --seed study-2026-01 --output review-queue.json
```

The queue samples each disposition separately, excludes candidates already present in
`candidate_reviews`, and records eligible and selected counts per stratum. Selection is
reproducible for the same record, seed, and cap. The output contains blank label fields;
it does not label candidates or claim that the selected sample is representative.

After independent review, merge the completed review entries into the original record's
`candidate_reviews` and add an `evaluation_sampling` object containing at least the
queue's `sampling_method`, `sampling_seed`, `per_disposition_cap`, and `strata`. Keep
that metadata with the record; the offline evaluator carries it into its report so readers
can assess the review design. Do not use sampling-adjusted population estimates unless a
statistically justified sampling design and weighting method have been specified.
