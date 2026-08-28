from __future__ import annotations

import json
import os
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
    payload = {
        "model": _model_name(), "system": system, "prompt": prompt,
        "stream": False, "keep_alive": "10m",
        "options": {
            "temperature": 0.1,
            "num_ctx": int(os.getenv("AI_CONTEXT", "4096")),
            "num_predict": num_predict or int(os.getenv("AI_MAX_OUTPUT", "1800")),
        },
    }
    if as_json:
        payload["format"] = "json"
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
    if not text:
        raise RuntimeError("Ollama returned an empty response")
    if not as_json:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI returned invalid JSON: {exc}. Raw: {text[:800]}") from exc


def _compact_articles(articles: list[dict], limit: int = 60) -> list[dict]:
    return [{
        "title": str(a.get("title", ""))[:220], "summary": str(a.get("summary", ""))[:420],
        "source": str(a.get("source", ""))[:70], "url": str(a.get("url", ""))[:400],
        "category": str(a.get("category", ""))[:40], "published": str(a.get("published", ""))[:35],
    } for a in articles[:limit]]


def select_stories(articles: list[dict], top_n: int = 12) -> list[dict]:
    compact = _compact_articles(articles, 60)
    prompt = f"""Select the {top_n} most consequential and diverse news stories from these candidates. Priorities: India relevance, human impact, geopolitical/economic significance, science/technology importance and future consequences. Deduplicate the same event. Return ONLY JSON: {{\"selected\":[{{\"rank\":1,\"headline\":\"exact candidate headline\",\"importance\":95,\"category\":\"India|World|Economy|Defence|Science|Technology|Culture|Other\",\"url\":\"exact candidate URL\",\"reason\":\"short reason\"}}]}}. URLs must come from candidates.\n\nCandidates:\n{json.dumps(compact, ensure_ascii=False)}"""
    result = _call_ollama(prompt, as_json=True, num_predict=900)
    return result.get("selected", [])[:top_n]


def _story_evidence(selected: list[dict], articles: list[dict], research: dict | None) -> list[dict]:
    by_url = {str(a.get("url", "")): a for a in articles}
    evidence = []
    for s in selected:
        a = by_url.get(str(s.get("url", "")), {})
        sid = s.get("headline", "").lower().strip().replace(" ", "_")[:80]
        evidence.append({
            "story_id": sid, "headline": s.get("headline", ""), "importance": s.get("importance", 0),
            "category": s.get("category", ""), "source": a.get("source", ""), "url": s.get("url", ""),
            "summary": str(a.get("summary", ""))[:550], "historical": (research or {}).get(sid, [])[:3],
        })
    return evidence


def _story_batch(batch: list[dict], today: str) -> list[dict]:
    prompt = f"""Today is {today}. Explain these selected news stories using ONLY the supplied evidence. Keep each story concise. Return ONLY JSON with key top_stories. Each item must contain: story_id, headline, importance, category, what, who, when, where, why, why_important, latest_update, timeline (max 3), sources, people (max 2), places (max 2), concepts (max 1), vocabulary (max 2). Never invent missing details.\n\nEvidence:\n{json.dumps(batch, ensure_ascii=False)}"""
    result = _call_ollama(prompt, as_json=True, num_predict=1400)
    return result.get("top_stories", [])


def _extras(evidence: list[dict], previous: dict, today: str) -> dict:
    # Small independent call: auxiliary learning content is separated from story generation.
    old = {k: v[-12:] for k, v in previous.items() if k in {"knowledge_cards", "vocabulary", "current_affairs"}}
    prompt = f"""Today is {today}. From ONLY this supplied evidence, create compact learning extras. Return ONLY JSON with keys current_affairs, culture, religion, connect_the_dots, revision, quiz. current_affairs max 5; culture max 2; religion max 2 and only if genuinely supported; connect_the_dots max 3; revision max 5 using older knowledge when relevant; quiz exactly 5. Each factual item must use a supplied source_url where available. Do not invent. Vocabulary and story explanations are handled separately.\n\nEvidence:\n{json.dumps(evidence, ensure_ascii=False)}\n\nOlder knowledge:\n{json.dumps(old, ensure_ascii=False)}"""
    return _call_ollama(prompt, as_json=True, num_predict=1200)


def generate_briefing(selected: list[dict], articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    evidence = _story_evidence(selected, articles, research)
    # Three small story calls prevent the previous 32K-token monolithic prompt and keep CPU generation bounded.
    stories: list[dict] = []
    for i in range(0, len(evidence), 4):
        stories.extend(_story_batch(evidence[i:i + 4], today))
    extras = _extras(evidence, previous, today)
    return {
        "top_stories": stories[:12],
        "current_affairs": extras.get("current_affairs", [])[:5],
        "culture": extras.get("culture", [])[:2],
        "religion": extras.get("religion", [])[:2],
        "connect_the_dots": extras.get("connect_the_dots", [])[:3],
        "revision": extras.get("revision", [])[:5],
        "quiz": extras.get("quiz", [])[:5],
    }


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    selected = select_stories(articles, top_n=12)
    return generate_briefing(selected, articles, previous, today, research)


def generate_text(prompt: str, system: str = "You are a factual knowledge teacher. Use only supplied data; do not invent.") -> str:
    return _call_ollama(prompt, system=system, as_json=False)


def configured_model() -> str:
    return _model_name()
