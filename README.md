# News Knowledge Bot — Stage 5

Automated **Telegram news + long-term knowledge engine**. It converts important daily news into a simple flowchart-like learning format and continuously builds revision memory.

## Daily briefing

- 🌅 **06:00 IST** — 12 stories
- 🌆 **16:00 IST** — 12 stories / updates
- 🇮🇳 **50% India + 🌍 50% World target** (6 + 6 per run)
- 📱 One story per Telegram message for easy reading
- 🔒 Same-topic and same-day deduplication
- 🔎 Multi-source corroboration and confidence scoring
- 🔄 Story change tracking and historical timeline

## Memory-first story format

Each story follows:

`EVENT → WHO → WHEN/WHERE → WHY → IMPACT → CHANGE → NEXT → CONNECTION → REMEMBER`

The goal is to understand the story in seconds and retain the underlying knowledge.

## Stage 3 — Intelligence

- India/World balanced selection
- Source diversity and credibility weighting
- Multi-source corroboration from the collected news pool
- Confidence score
- Historical story matching
- Story evolution/change tracking
- Related-story evidence
- Knowledge graph relationships

## Stage 4 — Adaptive learning

- Persistent learning progress in GitHub CSVs
- Due/overdue revision queue
- Mastery score
- Weak-topic prioritization
- Adaptive review intervals
- Vocabulary tracking
- Weekly and monthly adaptive revision
- Connect-the-dots learning

## Stage 5 — Knowledge engine

`NEWS → FILTER → BALANCE → VERIFY → EXPLAIN → CONNECT → STORE → REVISE → IMPROVE`

Persistent GitHub memory includes:

- `news_history.csv`
- `story_timeline.csv`
- `current_affairs.csv`
- `knowledge_cards.csv`
- `knowledge_graph.csv`
- `learning_progress.csv`
- `vocabulary.csv`
- `quiz_history.csv`
- people / places / culture / religion memory

No local database is required.

## GitHub Actions

- `.github/workflows/morning_news.yml` — 06:00 IST
- `.github/workflows/afternoon_news.yml` — 16:00 IST
- `.github/workflows/knowledge_review.yml` — scheduled weekly/monthly revision

Daily workflows support manual execution. Existing CSV files are automatically migrated to the new schema when new fields are introduced.

## AI

AI runs locally with **Ollama + Qwen 2.5 7B**. Daily workflows use a larger context/output budget than V4 for richer evidence and memory explanations.

## Secrets

Required:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

No OpenAI API key is required for the current local-Ollama setup.

## Local test

```bash
pip install -r requirements.txt
python -m app.main
```

Set Telegram and Ollama environment variables when testing locally.

## Goal

**Read less → understand faster → connect knowledge → remember longer → revise intelligently.**
