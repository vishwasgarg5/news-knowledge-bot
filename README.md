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

## Output
- Up to 12 priority stories, targeting 6 India + 6 World
- Source-health and failure tracking
- Exact + semantic duplicate filtering
- Multi-source corroboration and confidence
- Continuing-story and historical context
- Concise evidence-only AI analysis
- Clean Telegram report with run-health footer

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
