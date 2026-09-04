# News Knowledge Bot — Final Stage

Automated **India + World news intelligence bot** for Telegram. **News only.**

## Pipeline
```text
SCAN → DEDUPLICATE → INDIA 6 + WORLD 6 → RANK
→ VERIFY → HISTORY → AI UNDERSTAND
→ EVENT → WHY → IMPACT → CHANGE → NEXT → REMEMBER
→ TELEGRAM → NEWS MEMORY
```

## Final capabilities
- Up to 12 priority stories per run: target **6 India + 6 World**
- Source/category-first India/World classification
- Exact + semantic headline deduplication
- Source health and failure tracking
- Importance ranking and continuing-story detection
- Multi-source corroboration with confidence score
- Historical context from `story_timeline.csv`
- Evidence-only AI briefing with concise fallback text
- Clean India/World Telegram blocks and run-health footer
- Morning **06:00 IST** + afternoon **16:00 IST** automation
- Shared workflow concurrency prevents overlapping memory writes
- GitHub-only memory; no separate learning database

## Telegram format
```text
📰 🇮🇳 INDIA
EVENT ↓ WHY ↓ IMPACT ↓ HISTORY ↓ CHANGE ↓ NEXT ↓ REMEMBER ↓ VERIFY

📰 🌍 WORLD
EVENT ↓ WHY ↓ IMPACT ↓ HISTORY ↓ CHANGE ↓ NEXT ↓ REMEMBER ↓ VERIFY

📊 NEWS STATUS
India | World | scanned | selected | verified
exact dup | similar filtered | source failures | runtime
```

## Memory
- `data/news_history.csv` — delivered story history
- `data/story_timeline.csv` — daily evolution of important stories

No culture, religion, vocabulary, quiz, people, places, or separate learning modules.

## AI
Ollama + Qwen 2.5 7B, configured for factual and concise output.

## Secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Principle
**Less noise → better verification → clearer understanding → easier memory.**
