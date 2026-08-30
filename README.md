# News Knowledge Bot V4

Automated **Telegram news + knowledge system**. It turns daily news into useful, long-term knowledge instead of just sending headlines.

## Daily

- 🌅 **06:00 IST** — 12 top stories
- 🌆 **16:00 IST** — 12 additional stories
- 🎯 Target: **24 unique stories/day**
- 📱 **1 story = 1 Telegram message**
- 🔒 Same-day topic deduplication
- 🧠 Story updates, timelines and historical context

## Learning

Each important story can update:

- 📰 Current affairs
- 📚 Knowledge cards
- 📖 Vocabulary
- ❓ Quiz history
- 🔗 Related topics and timelines
- 🧠 Connect-the-dots knowledge

## Knowledge Review

- Weekly and monthly revision
- Questions with **answers immediately below**
- Why-it-matters explanations
- Current-affairs revision
- Vocabulary revision
- Quick-memory section
- Spaced-repetition friendly knowledge history

## Architecture

`RSS/news → normalize → deduplicate → story selection → research → AI briefing → Telegram → GitHub memory → knowledge review`

AI runs locally with **Ollama + Qwen**. Persistent memory is stored in GitHub CSV files; no local database is required.

## GitHub Actions

Separate workflows keep scheduling simple:

- `.github/workflows/morning_news.yml` — 06:00 IST
- `.github/workflows/afternoon_news.yml` — 16:00 IST
- Knowledge review workflows run separately on their scheduled review cycle.

Both daily workflows support manual execution.

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

Set the Telegram and Ollama environment variables when testing locally.

## V4 goal

**Read less. Learn more. Remember what matters.**
