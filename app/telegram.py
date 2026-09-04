from __future__ import annotations

import re
import time
import requests

from .settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API = "https://api.telegram.org/bot{}/sendMessage"
# Telegram applies per-chat flood limits. Keep a safe spacing between messages.
MIN_SEND_INTERVAL = 1.15
MAX_RETRIES = 6
_LAST_SEND = 0.0


def _plain(text: str) -> str:
    return re.sub(r"</?b>", "", text).replace("||", "")


def send(text: str):
    global _LAST_SEND
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets are not configured")

    # Pace every message, including retries, so a long briefing does not
    # trigger Telegram's per-chat flood protection.
    wait = MIN_SEND_INTERVAL - (time.monotonic() - _LAST_SEND)
    if wait > 0:
        time.sleep(wait)

    for attempt in range(MAX_RETRIES):
        r = requests.post(API.format(TELEGRAM_BOT_TOKEN), data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": _plain(text),
            "disable_web_page_preview": True,
        }, timeout=30)

        if r.ok:
            _LAST_SEND = time.monotonic()
            return

        # Telegram returns 429 with parameters.retry_after. Respect that
        # server-provided delay rather than failing the complete workflow.
        if r.status_code == 429:
            retry_after = 3.0
            try:
                payload = r.json()
                retry_after = float(payload.get("parameters", {}).get("retry_after", retry_after))
            except (ValueError, TypeError):
                pass
            time.sleep(max(retry_after, MIN_SEND_INTERVAL))
            _LAST_SEND = time.monotonic()
            continue

        # Retry transient 5xx responses, but fail fast on permanent errors.
        if 500 <= r.status_code < 600 and attempt < MAX_RETRIES - 1:
            time.sleep(min(2 ** attempt, 15))
            continue

        r.raise_for_status()

    raise RuntimeError("Telegram delivery failed after retries")


def chunks(text: str, size: int = 3800):
    lines, current, length = [], [], 0
    for line in text.splitlines():
        if length + len(line) + 1 > size and current:
            lines.append("\n".join(current))
            current = []
            length = 0
        current.append(line)
        length += len(line) + 1
    if current:
        lines.append("\n".join(current))
    return lines


def send_text(text: str):
    for part in chunks(text):
        send(part)
