# News Knowledge Bot

A **news-only India + World intelligence bot** for Telegram. Run it manually from GitHub Actions whenever you want a fresh briefing.

## Run

GitHub → **Actions → News Intelligence → Run workflow**.

There are no automatic schedules.

## Intelligence flow
```text
SCAN ALL → SOURCE HEALTH → ARTICLE DEDUPLICATION → EVENT CANDIDATES
→ IMPORTANCE → MULTI-SOURCE VERIFICATION → CONFIDENCE + NOVELTY
→ TOPIC DIVERSITY → MAX 24 HIGH-VALUE STORIES
→ QWEN ANALYSIS → HISTORY / CHANGE → TELEGRAM
→ GITHUB NEWS MEMORY
```

## Selection model
- Scans up to the configured source/article limits before ranking
- Builds a larger candidate pool before final selection
- Removes exact and semantic near-duplicates
- Treats related coverage as one event rather than filling the report with copies
- Separates **importance** from **confidence**
- Rewards independent source corroboration and penalizes unverified items
- Uses novelty/history so repeated coverage does not crowd out new developments
- Applies soft topic diversity limits to avoid one category dominating the briefing
- Sends **up to 24** high-value stories per run; fewer are sent when fewer meaningful stories qualify
- Never pads the report just to reach 24

## Telegram output
- **Message 1:** complete numbered headline index
- **Following messages:** exactly one detailed message per selected story
- Detailed stories include what happened, why, impact, prior context, change, next step, memory hook and verification
- Verification distinguishes **Confirmed · multi-source**, **Confirmed · official source**, **Single source** and **Unverified**
- Confidence and source count are shown for every story
- Vocabulary appears only when a genuinely difficult/important news term needs explanation
- Run-health statistics show scanned articles, candidate count, final count, duplicate filtering, verification and source failures

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
The repository is intentionally **news only**. No culture, religion, quiz, people/places or separate learning modules.
