import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = ROOT / "config" / "sources.yaml"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "").strip() or os.environ.get("OLLAMA_MODEL", "").strip() or "qwen2.5:7b"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate").strip() or "http://localhost:11434/api/generate"
TIMEZONE = "Asia/Kolkata"
