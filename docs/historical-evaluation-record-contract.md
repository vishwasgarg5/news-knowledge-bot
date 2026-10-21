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


## Audit completed human-review queues

Save each reviewer's completed queue separately, preserving candidate IDs and the sampling
metadata. Compare two or more reviewer files without overwriting the source record:

```bash
python scripts/audit_human_review_results.py review-a.json review-b.json --min-reviews-per-disposition 3 --output review-audit.json
```

The report flags different labels for the same candidate, any candidate marked uncertain,
missing reviewer/timestamp/rationale fields, missing source evidence metadata, and
under-reviewed disposition groups. It carries sampling metadata through for inspection.
A disagreement is a prompt for adjudication, not a declaration that either reviewer is
wrong. Use distinct, independent reviewer files; repeated copies from the same reviewer
must not be treated as independent opinions. The default minimum of three candidates per
stratum is an operational warning threshold, not a statistical guarantee.


## Adjudication and consolidated evaluation report

Keep each reviewer's completed queue as a separate file. Record an adjudication only when
a named adjudicator has explicitly resolved the case. Example adjudication file:

```json
{
  "adjudications": [
    {
      "candidate_id": "candidate-123",
      "final_label": "relevant",
      "adjudicator_id": "review-lead-01",
      "adjudicated_at": "2026-10-21T12:00:00+05:30",
      "rationale": "Reviewed the source evidence and briefing scope."
    }
  ]
}
```

Generate a consolidated report:

```bash
python scripts/consolidate_human_evaluation.py review-a.json review-b.json \\
  --adjudications adjudications.json --output consolidated-evaluation.json
```

The report keeps original reviewer disagreements visible even after adjudication, and
summarizes accepted adjudications, uncertain candidates, incomplete reviews, missing
evidence, unresolved cases, and per-queue sampling metadata. A disagreement without a
valid adjudication remains unresolved; a label is never inferred from a production
decision. Candidates with missing evidence, uncertainty, or incomplete review must not
silently enter definitive metrics. This tool is an audit report, not an accuracy calculator.


## Adjudicated-only offline metrics

For a conservative precision/recall report, pass the completed reviewer queues and the
explicit adjudication file to the offline evaluator:

```bash
python scripts/evaluate_adjudicated_reviews.py review-a.json review-b.json \\
  --adjudications adjudications.json --output adjudicated-metrics.json
pytest -q tests/test_adjudicated_review_metrics.py
```

Only candidates with a valid explicit adjudication, complete source evidence (`source`,
`url`, `published_at`, `summary`), and an `included` or `excluded` disposition can enter
the precision/recall denominators. The report lists each candidate's eligibility and
exclusion reasons. Unadjudicated candidates, uncertain labels, duplicate/out-of-scope
dispositions, and evidence-incomplete candidates are not silently treated as negatives.
A missing denominator yields `null`, not a guessed zero. The report retains sampling
metadata and does not apply sampling weights or claim population-level accuracy.


## Versioned evaluation baseline and sample-size gates

Start from `config/evaluation_baseline.example.json`. Before using it, replace
`REPLACE_WITH_IMMUTABLE_POLICY_ID` with the exact policy identifier recorded in every
review queue. Do not treat a code commit SHA as a policy version unless your team has
explicitly chosen and documented that convention.

After producing the adjudicated metrics report, audit it against the baseline:

```bash
python scripts/evaluate_adjudicated_reviews.py review-a.json review-b.json \\
  --adjudications adjudications.json --output adjudicated-metrics.json
python scripts/audit_evaluation_baseline.py adjudicated-metrics.json \\
  --baseline config/evaluation-baseline.json --output baseline-audit.json
pytest -q tests/test_evaluation_baseline.py
```

The example thresholds require at least 30 eligible candidates, at least five eligible
included and excluded candidates each, and at least 50% eligible adjudication/evidence
coverage across candidates in the supplied queues. These are starting operational gates,
not statistical guarantees; calibrate them before drawing conclusions. The audit blocks
an unpinned placeholder policy, missing queue policy versions, mixed policy versions,
invalid thresholds, or sample/coverage shortfalls. Copy the example to your chosen
baseline path and set the immutable policy identifier and thresholds before use.

Review queues should include `policy_version` alongside their run and sampling metadata.
The evaluator preserves that field for the baseline audit. A passing audit means only
that configured process thresholds were met; it does not establish label correctness,
causal improvement, or representative sampling.


## Compare policy versions on the same reviewed set

First generate an adjudicated metrics report for each policy from the same queue files and
same adjudication artifact, then audit each report against its own pinned policy baseline.
The evaluator now includes a SHA-256 fingerprint of each candidate's source evidence so the
comparison can verify the evidence snapshot is identical even when policy disposition changes.

```bash
python scripts/evaluate_adjudicated_reviews.py shared-review-queue.json \\
  --adjudications shared-adjudications.json --output policy-v1-report.json
python scripts/evaluate_adjudicated_reviews.py shared-review-queue.json \\
  --adjudications shared-adjudications.json --output policy-v2-report.json
python scripts/audit_evaluation_baseline.py policy-v1-report.json \\
  --baseline baseline-v1.json --output policy-v1-gate.json
python scripts/audit_evaluation_baseline.py policy-v2-report.json \\
  --baseline baseline-v2.json --output policy-v2-gate.json
python scripts/compare_policy_evaluations.py policy-v1-report.json policy-v2-report.json \\
  --baseline-gate policy-v1-gate.json --candidate-gate policy-v2-gate.json \\
  --output policy-comparison.json
pytest -q tests/test_compare_policy_evaluations.py
```

The comparison blocks unless both policy-specific baseline audits pass, candidate IDs and
adjudicated labels match, evidence fingerprints match, and the sampling method and seed
match. It reports precision/recall deltas and per-disposition counts for included, excluded,
duplicate, and out-of-scope candidates. Each report's own baseline must pin its policy version.
A comparable result is descriptive only: it does not prove causality or statistical
significance, and it cannot correct a non-representative sample. Use the exact same
reviewed candidate/evidence set and adjudication file; do not re-adjudicate between policy
runs when measuring the policy effect.
