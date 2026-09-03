# News Knowledge Bot — Stage 5

Automated **India + World news intelligence bot** for Telegram.

## What it does

```text
RSS / News
   ↓
Collect
   ↓
Deduplicate
   ↓
🇮🇳 India 50% + 🌍 World 50%
   ↓
Rank by importance
   ↓
Multi-source verification
   ↓
AI explanation
   ↓
EVENT → WHY → IMPACT → CHANGE → NEXT → CONNECTION → REMEMBER
   ↓
Telegram
   ↓
News history + story timeline on GitHub
```

## Daily output

- **12 important stories per run**
- Target: **6 India + 6 World**
- Morning and afternoon runs
- Duplicate/same-topic filtering
- Continuing-story detection
- Multi-source corroboration
- Confidence score
- Historical story context
- Flowchart-style, easy-to-read explanations

## Telegram story format

```text
📰 INDIA / WORLD
        ↓
🔴 EVENT
        ↓
❓ WHY
        ↓
💡 IMPACT
        ↓
🔄 CHANGE
        ↓
🔮 NEXT
        ↓
🔗 CONNECTION
        ↓
🧠 REMEMBER
        ↓
🔎 VERIFY
```

## Memory

Only **news memory** is retained:

- `data/news_history.csv` — delivered news history
- `data/story_timeline.csv` — evolution of important stories

No separate culture, religion, vocabulary, quiz, people, places, knowledge-card, or learning database is used.

## Schedule

- Morning: **06:00 IST**
- Afternoon: **16:00 IST**
- Both workflows support manual execution.

## AI

Runs locally with **Ollama + Qwen 2.5 7B**. No OpenAI API key is required.

## Secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Goal

**50% India news + 50% World news — less noise, better understanding, easier memory.**
