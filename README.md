# News Knowledge Bot — Final Stage

Automated **India + World news intelligence bot** for Telegram. News only.

## Final intelligence pipeline

```text
RSS / NEWS
   ↓
COLLECT
   ↓
DEDUPLICATE
   ↓
🇮🇳 INDIA 50%  +  🌍 WORLD 50%
   ↓
IMPORTANCE RANKING
   ↓
SOURCE CORROBORATION
   ↓
CONTINUING-STORY CHECK
   ↓
AI UNDERSTANDING
   ↓
EVENT → WHY → IMPACT → CHANGE → NEXT → REMEMBER
   ↓
CLEAN TELEGRAM REPORT
   ↓
NEWS HISTORY + STORY TIMELINE
```

## Final-stage capabilities

- 12 high-priority stories per run: target **6 India + 6 World**
- Importance ranking using source quality, category and event-impact signals
- Same-story and previously delivered-story filtering
- Continuing vs new story detection
- Multi-source corroboration and confidence score
- Historical context from GitHub news memory
- Strict evidence-only AI generation; no invented facts
- Compact flowchart-style Telegram report
- Separate India and World report blocks for fast scanning
- Morning + afternoon automation
- GitHub-only news memory; no learning/knowledge databases

## Telegram format

```text
📰 🇮🇳 INDIA
EVENT ↓
WHY ↓
IMPACT ↓
CHANGE ↓
NEXT ↓
REMEMBER ↓
VERIFY

📰 🌍 WORLD
EVENT ↓
WHY ↓
IMPACT ↓
CHANGE ↓
NEXT ↓
REMEMBER ↓
VERIFY
```

## Memory

Only news is retained:

- `data/news_history.csv` — delivered news history
- `data/story_timeline.csv` — important-story evolution

No culture, religion, vocabulary, quiz, people, places, current-affairs or separate learning modules.

## Schedule

- Morning: **06:00 IST**
- Afternoon: **16:00 IST**
- Both workflows support manual execution.

## AI

**Ollama + Qwen 2.5 7B**, configured for factual, low-temperature, concise output.

## Secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Design principle

**Less noise → better verification → clearer understanding → easier memory.**
