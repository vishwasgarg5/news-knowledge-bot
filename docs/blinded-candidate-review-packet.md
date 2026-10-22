# Blinded candidate review packet

Use the offline packet builder to prepare candidates for independent human relevance review:

\`\`\`bash
python scripts/build_blinded_review_packet.py data/historical_evaluation_records \
  --queue-output /tmp/candidate-review-queue.json \
  --key-output /tmp/candidate-review-answer-key.json \
  --sample-per-disposition 25 --seed review-2026-10
\`\`\`

The queue and answer key are separate files. **Do not share the answer key with reviewers until their labels are finalized.** The queue omits pipeline disposition and leaves relevance label, reviewer alias, review timestamp, rationale, and evidence URL fields blank. Reviewers should use relevant, not_relevant, or uncertain; timestamps must be timezone-aware ISO-8601 when labels are entered.

Sampling is deterministic for a fixed input and seed and samples independently within each available disposition group (included, excluded, duplicate, out_of_scope), up to the requested maximum per group. The output records available and selected counts. Small groups are included in full. This helps expose errors in both included and excluded decisions but does not, by itself, create a statistically representative sample or authorize population-level accuracy claims.

Candidate metadata is copied as captured. Missing fields remain blank and are not inferred or synthesized. The builder performs no fetching, production ranking, label creation, or delivery. Keep the answer key access-controlled and preserve the queue and key together with the seed for auditability.


After reviewers complete the queue, validate it against the separately stored answer key:

\`\`\`bash
python scripts/validate_blinded_review_packet.py \\
  /path/to/completed-review-queue.json \\
  /path/to/candidate-review-answer-key.json --json --require-complete
\`\`\`

The validator rejects mismatched item IDs, duplicate IDs, unblinded queues, invalid labels, missing reviewer/rationale, timestamps without timezone offsets, and missing/invalid evidence URLs for definitive labels. It reports `valid` (structural and review-field validity) separately from `complete` (no unreviewed items and no validation errors). Use `--require-complete` for a final audit; this makes the command fail if any queue item is unreviewed. It reports descriptive confusion-matrix metrics only for definitive labels on included and excluded candidates. Uncertain, duplicate, and out-of-scope are not guessed into binary classes. This report validates a review packet; it does not automatically modify the historical capture records or make the evaluation sample representative.
