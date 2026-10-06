# News Knowledge Bot

A **news-only India + World intelligence bot** for Telegram. It scans a large article pool, reduces it to high-value event candidates, selects **every story above the importance threshold**, and learns from what happens to those stories after selection.

## Run
GitHub → **Actions → News Intelligence → Run workflow**. The production workflow runs only by manual dispatch or its configured daily schedule; repository pushes do not trigger news delivery.

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

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Design rule
News only. No separate app or unrelated modules.
