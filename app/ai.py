from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence for factual claims. Never invent facts, dates, people, numbers or quotations. If evidence is insufficient, say so. Be concise, neutral and source-backed."""
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


def _model_name() -> str:
    return os.getenv("AI_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL


def _call_ollama(prompt: str, system: str = SYSTEM, as_json: bool = False, num_predict: int | None = None):
    payload = {"model": _model_name(), "system": system, "prompt": prompt, "stream": False, "keep_alive": "10m", "options": {"temperature": 0.1, "num_ctx": int(os.getenv("AI_CONTEXT", "4096")), "num_predict": num_predict or int(os.getenv("AI_MAX_OUTPUT", "1200"))}}
    if as_json: payload["format"] = "json"
    request = Request(_ollama_url(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "360"))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach Ollama at {_ollama_url()}: {exc.reason}") from exc
    text = result.get("response", "").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    if not as_json: return text
    try: return json.loads(text)
    except json.JSONDecodeError as exc: raise RuntimeError(f"AI returned invalid JSON: {exc}. Raw: {text[:800]}") from exc


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{4,}", text.lower()))


def _deterministic_score(a: dict) -> float:
    title, summary = str(a.get("title", "")), str(a.get("summary", ""))
    source, category = str(a.get("source", "")).lower(), str(a.get("category", "")).lower()
    text = f"{title} {summary}".lower()
    score = 35.0
    if any(x in source for x in ("reuters", "bbc", "associated press", "ap news", "the hindu", "indian express", "times of india", "pib")): score += 12
    if category in {"india", "national", "politics", "world", "economy", "business", "defence", "science", "technology"}: score += 8
    keywords = {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}
    for term, boost in keywords.items():
        if term in text: score += boost
    impact_terms = ("million", "billion", "lakh", "crore", "dead", "killed", "injured", "arrested", "approved", "launched", "signed")
    score += min(10, 2 * sum(term in text for term in impact_terms))
    score += min(8, len(_words(title)) * 0.7)
    return min(100.0, score)


def select_stories(articles: list[dict], top_n: int = 12) -> list[dict]:
    """Fast deterministic selection; reserves the local LLM for explanation/learning."""
    ranked, seen_words = [], []
    for a in articles:
        title = str(a.get("title", "")).strip()
        if not title or not a.get("url"): continue
        words = _words(title)
        if any(len(words & old) / max(1, len(words | old)) >= 0.72 for old in seen_words): continue
        seen_words.append(words)
        ranked.append((round(_deterministic_score(a), 1), a))
    ranked.sort(key=lambda x: (-x[0], str(x[1].get("published", ""))))
    selected, categories = [], {}
    for score, a in ranked:
        category = str(a.get("category", "Other"))
        if categories.get(category, 0) >= max(3, top_n // 3): continue
        categories[category] = categories.get(category, 0) + 1
        headline = str(a.get("title", ""))[:240]
        story_id = hashlib.sha1(headline.lower().encode("utf-8")).hexdigest()[:16]
        selected.append({"story_id": story_id, "rank": len(selected)+1, "headline": headline, "importance": score, "category": category, "url": str(a.get("url", "")), "reason": "Deterministic impact/source/relevance score; local AI is reserved for explanation."})
        if len(selected) >= top_n: break
    return selected


def _story_evidence(selected: list[dict], articles: list[dict], research: dict | None) -> list[dict]:
    by_url = {str(a.get("url", "")): a for a in articles}
    evidence = []
    for s in selected:
        a = by_url.get(str(s.get("url", "")), {})
        sid = s.get("story_id") or hashlib.sha1(str(s.get("headline", "")).lower().encode()).hexdigest()[:16]
        evidence.append({"story_id": sid, "headline": s.get("headline", ""), "importance": s.get("importance", 0), "category": s.get("category", ""), "source": a.get("source", ""), "url": s.get("url", ""), "summary": str(a.get("summary", ""))[:450], "historical": (research or {}).get(sid, [])[:2]})
    return evidence


def _story_batch(batch: list[dict], today: str) -> list[dict]:
    prompt = f"Today is {today}. Explain these selected news stories using ONLY the supplied evidence. Keep each story very concise. Return ONLY JSON with key top_stories. Each item: story_id, headline, importance, category, what, who, when, where, why, why_important, latest_update, timeline (max 2), sources, people (max 2), places (max 2), concepts (max 1), vocabulary (max 2). Missing evidence must be written as 'Not stated in supplied sources'. Never invent.\n\nEvidence:\n{json.dumps(batch, ensure_ascii=False)}"
    result = _call_ollama(prompt, as_json=True, num_predict=1000)
    return result.get("top_stories", [])


def _extras(evidence: list[dict], previous: dict, today: str) -> dict:
    old = {k: v[-8:] for k, v in previous.items() if k in {"knowledge_cards", "vocabulary", "current_affairs"}}
    prompt = f"Today is {today}. From ONLY this supplied evidence, create compact learning extras. Return ONLY JSON with keys current_affairs, culture, religion, connect_the_dots, revision, quiz. current_affairs max 3; culture max 1; religion max 1 and only if supported; connect_the_dots max 2; revision max 3; quiz exactly 3. Keep every item short. Do not invent.\n\nEvidence:\n{json.dumps(evidence, ensure_ascii=False)}\n\nOlder knowledge:\n{json.dumps(old, ensure_ascii=False)}"
    return _call_ollama(prompt, as_json=True, num_predict=700)


def generate_briefing(selected: list[dict], articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    evidence = _story_evidence(selected, articles, research)
    stories: list[dict] = []
    for i in range(0, len(evidence), 4): stories.extend(_story_batch(evidence[i:i+4], today))
    extras = _extras(evidence, previous, today)
    return {"top_stories": stories[:12], "current_affairs": extras.get("current_affairs", [])[:3], "culture": extras.get("culture", [])[:1], "religion": extras.get("religion", [])[:1], "connect_the_dots": extras.get("connect_the_dots", [])[:2], "revision": extras.get("revision", [])[:3], "quiz": extras.get("quiz", [])[:3]}


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    return generate_briefing(select_stories(articles, top_n=12), articles, previous, today, research)


def generate_text(prompt: str, system: str = "You are a factual knowledge teacher. Use only supplied data; do not invent.") -> str:
    return _call_ollama(prompt, system=system, as_json=False)


def configured_model() -> str: return _model_name()
