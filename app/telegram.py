from __future__ import annotations

import re
import time
import html
import requests

from .settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API = "https://api.telegram.org/bot{}/sendMessage"
# Telegram applies per-chat flood limits. Keep a safe spacing between messages.
MIN_SEND_INTERVAL = 1.15
MAX_RETRIES = 6
_LAST_SEND = 0.0


def _html(text: str) -> str:
    # Escape dynamic news text while preserving deliberate Telegram <b> tags.
    safe = html.escape(str(text).replace("||", ""), quote=False)
    return safe.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


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
            "text": _html(text),
            "parse_mode": "HTML",
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


def chunks(text: str, size: int = 3500):
    """Split at line/word boundaries and guarantee no single chunk exceeds size."""
    if size < 100:
        raise ValueError("Telegram chunk size must be at least 100 characters")

    def split_line(line):
        if len(line) <= size:
            return [line]
        bold = "<b>" in line and "</b>" in line
        body = line.replace("<b>", "").replace("</b>", "") if bold else line
        parts=[]; current=""
        for word in body.split():
            if len(word) > size:
                if current:
                    parts.append(current); current=""
                parts.extend(word[i:i+size] for i in range(0,len(word),size))
                continue
            candidate=(current+" "+word).strip()
            if len(candidate)>size and current:
                parts.append(current); current=word
            else:
                current=candidate
        if current:
            parts.append(current)
        return [f"<b>{part}</b>" for part in parts] if bold else parts

    result=[]; current=""
    for line in str(text).splitlines():
        for part in split_line(line):
            candidate=(current+"\n"+part).strip() if current else part
            if len(candidate)>size and current:
                result.append(current); current=part
            else:
                current=candidate
    if current:
        result.append(current)
    return result

def send_text(text: str):
    parts=chunks(text)
    for part in parts:
        send(part)
    print(f"[INFO] Telegram delivery success | messages={len(parts)}",flush=True)
