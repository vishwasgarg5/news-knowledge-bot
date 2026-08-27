from __future__ import annotations

from datetime import date
from urllib.parse import quote

import requests

CULTURE_TOPICS = [
    "Indian classical music", "Kathak", "Bharatanatyam", "Indian architecture",
    "UNESCO Intangible Cultural Heritage", "Indian textiles", "Japanese tea ceremony",
    "Persian literature", "African traditional music", "Greek theatre", "Mughal architecture",
    "Sanskrit literature", "Indian folk art", "World heritage sites",
]
RELIGION_TOPICS = [
    "Hinduism", "Buddhism", "Jainism", "Sikhism", "Islam", "Christianity", "Judaism",
    "Zoroastrianism", "Baháʼí Faith", "Confucianism", "Taoism", "Shinto",
]


def wiki_summary(title: str) -> dict:
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe="_")
    try:
        r = requests.get(url, headers={"User-Agent": "NewsKnowledgeBot/1.0"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {"title": data.get("title", title), "extract": data.get("extract", ""), "url": data.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{quote(title.replace(' ','_'))}")}
    except Exception as exc:
        print(f"Wikipedia lookup failed for {title}: {exc}")
        return {"title": title, "extract": "", "url": ""}


def daily_learning():
    day = date.today().toordinal()
    culture = wiki_summary(CULTURE_TOPICS[day % len(CULTURE_TOPICS)])
    religion = wiki_summary(RELIGION_TOPICS[day % len(RELIGION_TOPICS)])
    return {"culture": culture, "religion": religion}
