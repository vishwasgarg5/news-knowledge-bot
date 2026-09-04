# News Knowledge Bot

A **news-only India + World intelligence bot** for Telegram. Run it manually from GitHub Actions whenever you want a fresh briefing.

## Run

GitHub → **Actions → News Intelligence → Run workflow**.

There are no automatic schedules.

## Flow
```text
SCAN ALL → SOURCE HEALTH → DEDUPLICATE → SMART QUALITY FILTER
→ FRESHNESS / CHANGE DETECTION → PRIORITY → VERIFY → HISTORY
→ TELEGRAM: HEADLINES FIRST → ONE DETAILED MESSAGE PER STORY
→ GITHUB NEWS MEMORY
```

## Telegram output
- No fixed 12-story output limit; every story above the quality threshold can be included
- Low-value/noisy stories are filtered by importance instead of an arbitrary count
- Unchanged stories already seen in memory are suppressed
- Breaking/urgent stories are promoted automatically
- **Message 1:** complete numbered headline index grouped by priority/category
- **Following messages:** exactly one detailed message per story
- Detailed stories include event, why, impact, history, change, next step, memory hook and verification
- Verification distinguishes **Confirmed · multi-source**, **Confirmed · official source**, **Single source** and **Unverified**
- Confidence and source count are shown for every story
- Source-health, duplicate filtering and run-health statistics are included

## Memory
- `data/news_history.csv` — delivered news history
- `data/story_timeline.csv` — story evolution/history

GitHub is the only persistent memory. No separate learning database.

## AI
Ollama + Qwen 2.5 7B.

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Design rule
The repository is intentionally **news only**. No culture, religion, quiz, vocabulary, people/places or separate learning modules.
