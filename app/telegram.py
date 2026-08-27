from __future__ import annotations

import re
import time
import requests

from .settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API = "https://api.telegram.org/bot{}/sendMessage"


def _plain(text: str) -> str:
    return re.sub(r"</?b>", "", text).replace("||", "")


def send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secrets are not configured")
    r = requests.post(API.format(TELEGRAM_BOT_TOKEN), data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": _plain(text),
        "disable_web_page_preview": True,
    }, timeout=30)
    r.raise_for_status()
    time.sleep(0.4)


def chunks(text: str, size: int = 3800):
    lines, current, length = [], [], 0
    for line in text.splitlines():
        if length + len(line) + 1 > size and current:
            lines.append("\n".join(current)); current=[]; length=0
        current.append(line); length += len(line)+1
    if current: lines.append("\n".join(current))
    return lines


def send_text(text: str):
    for part in chunks(text):
        send(part)
