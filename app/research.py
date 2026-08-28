from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import requests

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def historical_headlines(query: str, days: int = 180, limit: int = 5) -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {"query": f'"{query[:140]}"', "mode": "artlist", "maxrecords": min(limit, 250), "format": "json",
              "startdatetime": start.strftime("%Y%m%d%H%M%S"), "enddatetime": end.strftime("%Y%m%d%H%M%S")}
    try:
        r = requests.get(API, params=params, timeout=10); r.raise_for_status(); data = r.json()
    except Exception as exc:
        print(f"[WARN] historical research failed: {exc}", flush=True); return []
    result = []
    for a in data.get("articles", [])[:limit]:
        result.append({"title": a.get("title", ""), "date": a.get("seendate", ""), "source": a.get("domain", ""), "url": a.get("url", "")})
    return result


def research_stories(stories: list[dict]) -> dict[str, list[dict]]:
    output = {}; ok = 0; failed = 0
    for s in stories:
        sid, query = s.get("story_id", ""), s.get("headline", "")
        if not sid or not query: continue
        result = historical_headlines(query)
        output[sid] = result
        if result: ok += 1
        else: failed += 1
    print(f"[INFO] historical research: {ok}/{len(stories)} stories returned evidence; {failed} empty/failed", flush=True)
    return output
