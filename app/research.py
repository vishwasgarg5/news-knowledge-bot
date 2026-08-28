from __future__ import annotations

from datetime import datetime, timedelta, timezone
import requests

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def historical_headlines(query: str, days: int = 180, limit: int = 5) -> list[dict]:
    end = datetime.now(timezone.utc); start = end - timedelta(days=days)
    params = {"query": query[:120], "mode": "artlist", "maxrecords": min(limit, 250), "format": "json",
              "startdatetime": start.strftime("%Y%m%d%H%M%S"), "enddatetime": end.strftime("%Y%m%d%H%M%S")}
    try:
        r = requests.get(API, params=params, timeout=8); r.raise_for_status()
        data = r.json()
        articles = data.get("articles", []) if isinstance(data, dict) else []
        return [{"title": a.get("title", ""), "date": a.get("seendate", ""), "source": a.get("domain", ""), "url": a.get("url", "")} for a in articles[:limit]]
    except Exception as exc:
        print(f"[WARN] historical research failed: {exc}", flush=True); return []


def research_stories(stories: list[dict]) -> dict[str, list[dict]]:
    output={}; ok=0; failed=0
    for s in stories:
        sid, query=s.get("story_id", ""), s.get("headline", "")
        if not sid or not query: continue
        result=historical_headlines(query); output[sid]=result
        if result: ok+=1
        else: failed+=1
    total=len(stories); status="PASS" if total and ok==total else ("WARN" if ok else "FAIL")
    print(f"[INFO] historical research status={status}: {ok}/{total} stories returned evidence; {failed} empty/failed", flush=True)
    return output
