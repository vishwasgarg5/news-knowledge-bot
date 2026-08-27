# News Knowledge Bot

An automated, zero-input Telegram morning briefing designed to build long-term knowledge, not just deliver headlines.

## What it does

Every morning the system collects news from multiple RSS sources, removes duplicates, clusters articles into stories, scores importance, and creates a concise learning-oriented briefing.

The briefing covers:

- Top 10–15 news stories
- Who / what / when / where / why
- Previous major headlines and story timelines
- Current affairs
- India, world, economy, defence, science/AI/technology
- Culture, heritage, religion and philosophy (neutral/educational)
- People, places and concepts
- Cause → effect / "connect the dots"
- News-based vocabulary with simple English and Hindi
- Spaced-repetition revision
- Daily quiz
- Breaking-news threshold alerts

Persistent memory is stored in CSV files committed to GitHub. No local database is required.

## Architecture

`RSS feeds → normalize → deduplicate → story clustering → importance scoring → AI research/explanation → knowledge update → Telegram messages → CSV persistence → GitHub commit`

## Required GitHub Actions secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `OPENAI_API_KEY`

Optional:

- `OPENAI_MODEL` (default: `gpt-5.6-mini`)

## Morning schedule

The workflow is scheduled for 07:00 IST (01:30 UTC) and can also be started manually from GitHub Actions.

## Local test

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'
export OPENAI_API_KEY='...'
python -m app.main
```

The bot intentionally does not require daily user input. Telegram commands are optional helpers for later phases.
