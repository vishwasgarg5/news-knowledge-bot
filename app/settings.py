import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = ROOT / "config" / "sources.yaml"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
# Empty OPENAI_MODEL must never be passed to the API.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"

TIMEZONE = "Asia/Kolkata"
