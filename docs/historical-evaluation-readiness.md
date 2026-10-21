# Historical verification evaluation readiness

## Current finding (2026-10-21)

The current `data/operational_snapshot.json` contains 10 `intelligence_v5.stories` records and 5 saved verification evidence rows. It does not contain an explicit original candidate article pool or story-level human/independently verified truth labels.

Therefore:

- The saved evidence can support limited retrospective diagnostics, such as inspecting recorded evidence and copy-similarity signals.
- It cannot support trustworthy historical precision, recall, or F1 for the verification policy. The candidates that were excluded or never attached to a story are absent, and verification decisions are not ground-truth labels.
- Do not infer a truth label from the current verification result, source reputation, importance score, or whether a story was delivered.
- The production decision remains **HOLD**. This audit makes no production-policy changes.

## Reproduce the readiness audit

Run against the current snapshot:

```bash
python scripts/audit_historical_eval_readiness.py
python scripts/audit_historical_eval_readiness.py --json
```

Audit locally available historical snapshot commits:

```bash
python scripts/audit_historical_eval_readiness.py --revision 2026-10-19=14f385a048bbb6a2f28a32a528c1dbd36881dbb5 --revision 2026-10-20=57e7c97c17fe39baf829ef4f5d9be521bfaed2d0 --revision 2026-10-21=8626e62e354567f7dbaf02afb74791bdbb10074f --json
```

The revision mode reads local Git objects with `git show`; historical commits must already exist in the local clone. A missing historical object is an audit error, not evidence that the snapshot was empty.

## Capture required for a future labelled evaluation

For each scheduled or explicitly approved run, preserve a separate immutable evaluation record containing:

1. **Run metadata:** UTC run timestamp, snapshot/run ID, code revision, verification-policy version, and configuration fingerprint.
2. **Full candidate pool:** every candidate considered, including candidates later rejected or not attached to a selected story; preserve title/headline, publisher, canonical URL, publication timestamp, summary/snippet, and collection timestamp where available.
3. **Decision trace:** stable story/event ID, candidate-to-story association, evidence links, independent-publisher normalization, freshness decision, copy/derivative/contradiction flags, baseline decision, and shadow-candidate decision.
4. **Independent truth labels:** human-reviewed event existence and identity, with reviewer/source and label timestamp. Keep `unknown/unreviewed` distinct from positive and negative; do not silently count unknowns as negatives.
5. **Evaluation protocol:** frozen time-based train/validation/test boundaries, deduplication rules, label adjudication rules, and per-case error review.

The candidate pool and decision trace should be written as an offline audit artifact. They must not be wired into the production delivery path by this change. Keep secrets and user-specific data out of the artifact.

## Safety and interpretation

The readiness script is read-only: it does not fetch news, run the production pipeline, change ranking or verification, dispatch workflows, or send Telegram messages. Field presence is only a schema check, not proof that the data is complete or correct. Even when all required fields exist, metrics should be reported only on independently labelled examples with explicit sample sizes and limitations.
