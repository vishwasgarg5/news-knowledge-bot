# Blinded candidate review packet

## Create or download a packet

The GitHub Actions workflow can create a blinded queue without running news discovery, production ranking, or Telegram delivery:

1. Open [News Intelligence workflow runs](https://github.com/vishwasgarg5/news-knowledge-bot/actions/workflows/news_intelligence.yml).
2. Select **Run workflow** on branch `main`.
3. Keep `mode` set to `review-packet`, then start the workflow.
4. Open the successful run and download the `blinded-review-queue` artifact.

The current workflow's default is the offline `review-packet` mode. The production mode is separate and must not be selected for review preparation.

For local offline generation, use:

```bash
mkdir -p "$HOME/news-review"
python scripts/build_blinded_review_packet.py \
  data/historical_evaluation_records/20261022T062359+0530-morning.json \
  --queue-output "$HOME/news-review/review-queue.json" \
  --key-output "$HOME/news-review/answer-key.json" \
  --sample-per-disposition 25 \
  --seed review-2026-10
```

The queue and answer key are separate files. **Never give the answer key to reviewers before their labels are finalized.** The queue omits pipeline disposition and starts with blank review fields. The builder is offline: it does not fetch news, run production ranking, create labels, or deliver messages.

## Instructions for reviewers

- Review each item independently using the available title, source, URL, publication time, and captured summary. Do not infer missing facts.
- Set `review.relevance_label` to exactly one of `relevant`, `not_relevant`, or `uncertain`.
- Enter a stable reviewer alias in `review.reviewer_id`.
- Enter `review.reviewed_at` as a timezone-aware ISO-8601 timestamp, for example `2026-10-22T10:00:00+05:30`.
- Explain the decision in `review.rationale`. For `relevant` or `not_relevant`, add at least one supporting `http://` or `https://` URL to `review.evidence_urls`. For `uncertain`, explain what remains unclear; evidence URLs may be empty.
- Preserve every `item_id` and all candidate metadata. Do not add a disposition field to the queue, delete items, or rename review fields. If you cannot assess an item, use `uncertain` rather than inventing a definitive label.

The queue artifact is not a private reviewer distribution channel: repository collaborators with Actions access may be able to download it. Share it only with intended reviewers, and do not put private reviewer notes or the answer key in the public repository.

## Sampling and interpretation

Sampling is deterministic for a fixed input and seed. It samples independently within each available pipeline-disposition group (`included`, `excluded`, `duplicate`, `out_of_scope`), up to the requested maximum per group; smaller groups are included in full. The queue records the sampling metadata. Sampling both included and excluded candidates can expose errors in either direction, but this packet is not necessarily a statistically representative sample and does not, by itself, authorize population-level accuracy claims.

Candidate metadata is copied as captured. Missing fields remain blank and are not inferred or synthesized. Preserve the queue and key with the seed for auditability, and keep the key access-controlled.

## Validate completed reviews

After reviewers finish, validate the queue against the separately stored answer key:

```bash
python scripts/validate_blinded_review_packet.py \
  /path/to/completed-review-queue.json \
  /path/to/candidate-review-answer-key.json --json --require-complete
```

The validator rejects empty packets, mismatched item IDs, duplicate IDs, unblinded queues, invalid labels, missing reviewer IDs or rationales, timestamps without timezone offsets, and missing or invalid evidence URLs for definitive labels. It reports `valid` (structural and review-field validity) separately from `complete` (no unreviewed items and no validation errors). Use `--require-complete` for the final audit; it fails if any queue item is unreviewed.

The report calculates descriptive confusion-matrix metrics only for definitive labels on candidates whose pipeline disposition was `included` or `excluded`. `uncertain`, `duplicate`, and `out_of_scope` cases are not forced into binary classes. Validation does not automatically modify historical capture records or make the sample representative. Do not claim model quality or release readiness until genuine reviews have been collected and the evaluation limitations have been assessed.
