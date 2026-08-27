from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import requests

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def historical_headlines(query: str, days: int = 180, limit: int = 8) -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {
        "query": f'"{query[:180]}"',
        "mode": "artlist",
        "maxrecords": min(limit, 250),
        "format": "json",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    try:
        r = requests.get(API, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"historical research failed: {exc}")
        return []
    result = []
    for a in data.get("articles", [])[:limit]:
        result.append({
            "title": a.get("title", ""),
            "date": a.get("seendate", ""),
            "source": a.get("domain", ""),
            "url": a.get("url", ""),
        })
    return result


def research_stories(stories: list[dict]) -> dict[str, list[dict]]:
    output = {}
    for s in stories:
        sid = s.get("story_id", "")
        query = s.get("headline", "")
        if sid and query:
            output[sid] = historical_headlines(query)
    return output
