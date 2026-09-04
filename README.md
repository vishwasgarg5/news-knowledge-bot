# News Knowledge Bot

A **news-only India + World intelligence bot** for Telegram. Run it manually from GitHub Actions whenever you want a fresh briefing.

## Run

GitHub → **Actions → News Intelligence → Run workflow**.

There are no automatic morning/afternoon schedules.

## Flow
```text
SCAN → SOURCE HEALTH → DEDUPLICATE → RANK
→ INDIA + WORLD BALANCE → VERIFY → HISTORY
→ AI: EVENT → WHY → IMPACT → CHANGE → NEXT → REMEMBER
→ TELEGRAM → GITHUB NEWS MEMORY
```

## Telegram output
- No fixed 12-story output limit; every usable, non-duplicate collected story is processed
- **Message 1:** complete numbered headline index for the run
- **Following messages:** exactly one detailed message per story
- Detailed stories include event, why, impact, history, change, next step, memory hook and verification
- Source-health and failure tracking
- Exact + semantic duplicate filtering
- Multi-source corroboration and confidence
- Continuing-story and historical context

## Memory
- `data/news_history.csv` — delivered news history
- `data/story_timeline.csv` — story evolution/history

GitHub is the only persistent memory. No separate learning database.

## AI
Ollama + Qwen 2.5 7B.

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Removed
Old scheduled workflows and non-news modules were removed. The repository is intentionally **news only**.
