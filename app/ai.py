from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence for factual claims. Never invent facts, dates, people, numbers or quotations. If evidence is insufficient, say so. Prefer concise, useful explanations and source-backed facts. Be neutral and respectful about politics, culture and religion."""
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


def _model_name() -> str:
    return os.getenv("AI_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL


def _call_ollama(prompt: str, system: str = SYSTEM, as_json: bool = False):
    payload = {
        "model": _model_name(),
        "system": system,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.1,
            "num_ctx": int(os.getenv("AI_CONTEXT", "4096")),
            "num_predict": int(os.getenv("AI_MAX_OUTPUT", "2500")),
        },
    }
    if as_json:
        payload["format"] = "json"
    request = Request(_ollama_url(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "600"))) as response:
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
    out = []
    for a in articles[:limit]:
        out.append({
            "title": str(a.get("title", ""))[:240],
            "summary": str(a.get("summary", ""))[:500],
            "source": str(a.get("source", ""))[:80],
            "url": str(a.get("url", ""))[:500],
            "category": str(a.get("category", ""))[:50],
            "published": str(a.get("published", ""))[:40],
        })
    return out


def select_stories(articles: list[dict], top_n: int = 12) -> list[dict]:
    """Small first-pass prompt: headlines/summaries only, never the full knowledge payload."""
    compact = _compact_articles(articles, 60)
    prompt = f"""Select the {top_n} most consequential and diverse news stories from these candidates.

Priorities: India relevance, human impact, geopolitical/economic significance, science/technology importance, future consequences, and genuine novelty. Deduplicate articles covering the same event. Do not select stories merely because they are sensational.

Candidates:
{json.dumps(compact, ensure_ascii=False)}

Return ONLY JSON in this exact shape:
{{"selected":[{{"rank":1,"headline":"exact candidate headline","importance":95,"category":"India|World|Economy|Defence|Science|Technology|Culture|Other","url":"exact candidate URL","reason":"short reason"}}]}}
Return at most {top_n} items. URLs must come from the candidates."""
    result = _call_ollama(prompt, as_json=True)
    return result.get("selected", [])[:top_n]


def _story_evidence(selected: list[dict], articles: list[dict], research: dict | None) -> list[dict]:
    by_url = {str(a.get("url", "")): a for a in articles}
    evidence = []
    for s in selected:
        a = by_url.get(str(s.get("url", "")), {})
        sid = s.get("headline", "").lower().strip().replace(" ", "_")[:80]
        evidence.append({
            "story_id": sid,
            "headline": s.get("headline", ""),
            "importance": s.get("importance", 0),
            "category": s.get("category", ""),
            "source": a.get("source", ""),
            "url": s.get("url", ""),
            "summary": str(a.get("summary", ""))[:700],
            "historical": (research or {}).get(sid, [])[:4],
        })
    return evidence


def generate_briefing(selected: list[dict], articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    evidence = _story_evidence(selected, articles, research)
    # Keep the final prompt deliberately small enough for a 4K-context local model.
    previous_small = {
        "knowledge_cards": previous.get("knowledge_cards", [])[-40:],
        "vocabulary": previous.get("vocabulary", [])[-40:],
        "story_timeline": previous.get("story_timeline", [])[-60:],
    }
    schema = {
        "top_stories": [{"story_id":"","headline":"","importance":0,"category":"","what":"","who":"","when":"","where":"","why":"","why_important":"","latest_update":"","timeline":[{"date":"","headline":"","event":"","source_url":""}],"sources":[""],"people":[{"name":"","role":"","background":"","why_in_news":""}],"places":[{"name":"","location":"","background":"","why_important":""}],"concepts":[{"topic":"","category":"","explanation":"","related_topics":""}],"vocabulary":[{"word":"","meaning":"","simple_meaning":"","hindi":"","example":""}]}],
        "current_affairs":[{"topic":"","category":"","summary":"","why_important":"","source_url":""}],
        "culture":[{"topic":"","type":"","explanation":"","origin":"","significance":"","source_url":""}],
        "religion":[{"tradition":"","topic":"","explanation":"","historical_context":"","source_url":""}],
        "connect_the_dots":[{"chain":"","explanation":""}],
        "revision":[{"topic":"","question":"","answer":""}],
        "quiz":[{"question":"","answer":"","topic":"","difficulty":"easy|medium|hard"}]
    }
    prompt = f"""Today is {today}. Create a concise morning knowledge briefing from ONLY the evidence below.

SELECTED STORIES:
{json.dumps(evidence, ensure_ascii=False)}

OLDER KNOWLEDGE (use only when relevant):
{json.dumps(previous_small, ensure_ascii=False)}

Return ONLY valid JSON matching this schema:
{json.dumps(schema, ensure_ascii=False)}

Rules:
- Keep 10-12 selected stories if evidence supports them; do not invent missing details.
- Each story must cite its supplied URL in sources.
- Timeline should contain only supported earlier milestones; historical list may be empty.
- Current affairs should cover important government, economy, defence, science, appointments, reports and international developments present in the evidence.
- Include 1-3 useful culture/heritage items and 1-2 neutral religion/philosophy learning items only when supported by evidence or stable supplied knowledge.
- Vocabulary: 5-8 useful English words from the briefing, with simple English, Hindi and an example.
- Revision: prefer older knowledge items. Quiz: 5 questions testing understanding.
- Be concise. Do not add commentary outside JSON."""
    return _call_ollama(prompt, as_json=True)


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    selected = select_stories(articles, top_n=12)
    return generate_briefing(selected, articles, previous, today, research)


def generate_text(prompt: str, system: str = "You are a factual knowledge teacher. Use only supplied data; do not invent.") -> str:
    return _call_ollama(prompt, system=system, as_json=False)


def configured_model() -> str:
    return _model_name()
