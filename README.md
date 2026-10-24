# News Knowledge Bot

A **news-only India + World intelligence bot** for Telegram. It scans a large article pool, reduces it to high-value event candidates, selects **every story above the importance threshold**, and learns from what happens to those stories after selection.

## Run
GitHub → **Actions → News Intelligence (Manual or Scheduled) → Run workflow**. The daily schedule runs validation only; it does not fetch production news or send Telegram messages. Production is a separate explicit manual mode and remains blocked whenever validation or the release quality gate fails. Pushes, commits, and pull requests do not trigger this workflow.

## Intelligence flow
```
SCAN → DEDUP → CANDIDATES → OUTCOME LEARNING → IMPORTANCE
→ VERIFICATION → RERANK → IMPORTANCE THRESHOLD → QWEN → TELEGRAM
→ MEMORY / SQLITE → FUTURE OUTCOME EVALUATION
```

## Learning system
- Stores the candidate pool, not just the final 24.
- Uses a stable event ID for outcome tracking.
- Evaluates whether selected stories reappear after roughly 24h, 48h and 7 days.
- Detects **misses**: a story not selected later becomes a candidate again.
- Detects **false positives**: a selected story shows no persistence by the 48h checkpoint.
- Learns bounded source/category adjustments from historical outcomes.
- Uses persistence as a **proxy for impact**, not as ground truth.
- Adds a bounded outcome score for calibration and keeps the ranking deterministic.
- Keeps learned adjustments small (maximum ±5 importance points) to prevent runaway self-learning.
- Learning is deterministic and stored in GitHub CSV files; Qwen does not rewrite the ranking algorithm.

## Telegram output
- Headline index followed by one detailed message for every story that clears the importance threshold.
- Shows verification, confidence, source count, change/history and next step.
- Shows learning counts: evaluated stories, misses and false positives.
- No 24-story Telegram cap. `NEWS_MIN_IMPORTANCE` controls which stories are reported; `NEWS_MAX_STORIES=0` means unlimited.

## Memory
- `data/news_history.csv` — delivered story memory
- `data/story_timeline.csv` — story evolution
- `data/news_learning.csv` — candidate/outcome learning history
- `data/news_knowledge.db` — indexed SQLite knowledge store mirrored from the CSV memory

## AI
Ollama + Qwen 2.5 3B (configurable via `AI_MODEL`).

## Adaptive category-diverse selection (upgrade)

Final regional selection now balances three goals in order: verification strength first, category diversity second, and the existing quality ranking third. Within the same verification tier, categories already represented in the briefing are deprioritized so strong stories from economy, science, technology, defence, and other available categories have a better chance to appear. Publisher caps, event-family deduplication, single-source limits, freshness checks, and evidence gates remain in force. Diversity never promotes a lower verification tier over a higher one, and it never invents a missing category: regional/category shortfalls remain visible in the audit.

## Targeted category-gap discovery

Before final candidate selection, the pipeline checks whether the configured feeds yielded eligible economy or defence stories. When either category is missing, it runs a bounded Google News RSS search (up to eight queries by default, configurable with `NEWS_CATEGORY_RESEARCH_QUERIES`). If selection still shows a gap, a second pass uses distinct query variants within the same total budget. Results must be fresh, unique, and still pass normal deterministic scoring, event deduplication, independent verification, and production quality gates. The second pass targets initially missing categories that remain below two selected candidates, so one incidental result does not prematurely close a coverage gap. RFC 2822 feed timestamps are supported when parsed timestamps are absent, and publisher aliases are canonicalized before counting independent sources. Discovery counts, remaining gaps, and failures are recorded in the audit and briefing; this mechanism adds candidates, not automatic verification or a guaranteed category quota.

## Offline human review and evaluation

The manual workflow defaults to `review-packet`, which builds a blinded queue from a historical capture without running production news fetching, ranking, or Telegram delivery. Open [Actions → News Intelligence](https://github.com/vishwasgarg5/news-knowledge-bot/actions/workflows/news_intelligence_main.yml), choose **Run workflow**, leave `mode` as `review-packet`, and download the `blinded-review-queue` artifact from the successful run.

Read [the blinded review guide](docs/blinded-candidate-review-packet.md) before distributing the queue. Keep the separate answer key private until reviewers finish. Human reviewers must provide genuine labels, reviewer IDs, timezone-aware timestamps, rationale, and evidence URLs for definitive labels. Never fabricate missing labels or treat pipeline decisions as ground truth. The current historical capture is not enough to claim model quality or release readiness until genuine review labels have been collected and audited.

The queue artifact is available to repository collaborators with Actions access, so it is not a restricted reviewer-sharing mechanism. Use a deliberate sharing process and keep the answer key out of the repository and artifact.

## Research coverage and model evaluation

The default corroboration search budget is 20 Google News RSS queries, balanced up to 10 candidates per region. Override with `NEWS_RESEARCH_SEARCH_QUERIES` and `NEWS_RESEARCH_QUERIES_PER_REGION` if runtime budgets require it. An official Reserve Bank of India RSS source is also configured under `economy`; feed availability and category coverage are measured at run time, so an unavailable feed is reported rather than silently treated as evidence.

Compare installed local Ollama models before changing production configuration:

```bash
python scripts/benchmark_ollama_models.py --models qwen2.5:3b,qwen3:4b
```

Only pass model tags that are already installed. The benchmark checks evidence extraction, unsupported-claim restraint, procedural-status precision, and preservation of allegations; it reports latency and contract scores but never switches `AI_MODEL`. Treat this as a screening test, not a substitute for a representative historical evaluation and production shadow run.

## Evidence-gap-first corroboration

External research discovery now filters out stale or undated RSS entries before adding them to the verification pool and records stale skips, missing metadata/timestamps, duplicate URLs, and distinct publishers. The bounded external research queue is prioritized by the evidence already present in collected feeds: unresolved contradictions and stories with no independent corroboration are searched before already corroborated stories, with importance used to break ties. India and world query caps remain in force. Preflight results are diagnostic only; they do not alter verification labels or bypass freshness, publisher independence, content quality, or production gates. The audit records how many candidates had zero independent sources and the evidence-priority tiers actually searched.

## Evidence quality diagnostics

The production audit canonicalizes known publisher aliases before measuring source diversity. It also reports evidence gaps, independent-source coverage, verification tiers, contradictions, and stories whose region is missing or outside the India/World taxonomy. Ranking ignores non-finite numeric inputs such as NaN and Infinity rather than allowing them to contaminate scores. These checks measure evidence availability and data quality; they do not establish that a story is true.

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Design rule
News only. No separate app or unrelated modules.


## Phase 6-7: Intelligence and personalization

The production pipeline now adds an intelligence layer after learning and regional normalization. It calculates breaking-news signals, historical topic/trend signals, emerging-topic flags, and a personalized score. Preferences are stored in `config/preferences.yaml` and are applied before research, re-ranking, final AI briefing, persistence, and Telegram delivery.

Flow:
`RSS → dedup → event/learning → region → trends/breaking → personalization → research → rerank → AI briefing → quality gate → memory/SQLite → Telegram`.

Personalization is bounded and additive: it does not bypass verification or the minimum importance quality gate.


## Phase 8: Analytics

Each run produces machine-readable analytics covering learning samples, outcome calibration, source/category reliability and topic/category frequency. The analytics summary is included in the final audit artifact and uses the same persisted memory as the learning pipeline.


## Evidence and corroboration audit

Research audit statistics distinguish fresh independent corroboration from a publisher label alone. The audit records verification-tier counts, independent-source coverage, mean independent publishers per story, single-source rate, stale primary-source count, and contradiction rate. A stale single-source item no longer inflates the research-current coverage metric. These metrics describe evidence availability, not the truth of a claim.

## Production hardening

The final ranking incorporates personalization, breaking-news and trend signals while retaining verification gates. Event memory now supports NEW, DEVELOPING, ESCALATING, CONFIRMED and RESOLVED states. CSV writes use atomic replacement to reduce partial-write corruption, and the workflow compiles the complete application and runs cross-module smoke validation before delivery.

The latest successful scheduled production run should be treated as the baseline; subsequent code changes require the next scheduled/manual run to validate the new code in GitHub Actions.


## Single main workflow and production safety

- `.github/workflows/news_intelligence_main.yml` is the only workflow file. It is triggered only by manual dispatch or the daily schedule; pushes, commits, and pull requests do not trigger it. The validation job compiles the application, validates YAML configuration, runs regression contract tests, and audits installed dependencies.
- The daily schedule runs validation only. Production fetching, Telegram delivery, and production-memory writes can run only after an explicit manual dispatch with `mode=production` on `main`, and only if the validation job passes. The historical capture-quality gate is currently failing, so release remains on HOLD. Choose `mode=validate` for validation-only or `mode=review-packet` for offline human-review preparation.
- Production writes are scoped to the production job; the validation job has read-only repository permissions.
- Production quality stays on `HOLD` when regional targets are missed, source collection fails, queued research remains uncorroborated, evidence gaps exceed the threshold, calibration/drift checks fail, or out-of-sample ranking improvement is not proven.
- RSS collection uses explicit HTTP timeouts and a bot User-Agent; source errors report HTTP status and parser context where available. Failed feeds remain visible in health checks rather than being silently treated as successful.
- Source metadata timestamps are restored from the original feed article when enrichment drops them. Missing timestamps are never invented.
