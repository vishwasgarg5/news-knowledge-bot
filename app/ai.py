from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence for factual claims. Never invent facts, dates, people, numbers or quotations. If evidence is insufficient, say so. Clearly distinguish today's development from older history. Prefer multiple independent sources. The goal is long-term knowledge: explain who/what/when/where/why, relevant history, cause-effect connections, useful concepts, vocabulary, and neutral cultural/religious context. Avoid sensationalism and political persuasion."""
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


def _model_name() -> str:
    return os.getenv("AI_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL


def _call_ollama(prompt: str, system: str = SYSTEM, as_json: bool = False):
    payload = json.dumps({"model": _model_name(), "system": system, "prompt": prompt, "stream": False, **({"format": "json"} if as_json else {})}).encode("utf-8")
    request = Request(_ollama_url(), data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "300"))) as response:
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
        raise RuntimeError(f"AI returned invalid JSON: {exc}") from exc


def _build_prompt(articles, previous, today, research):
    compact = [{k: a.get(k, "") for k in ("title", "summary", "url", "source", "category", "published")} for a in articles]
    schema = {
        "top_stories": [{"story_id":"stable_slug","headline":"","importance":0,"category":"","what":"","who":"","when":"","where":"","why":"","why_important":"","latest_update":"","timeline":[{"date":"","headline":"","event":"","source_url":""}],"sources":[""],"people":[{"name":"","role":"","background":"","why_in_news":""}],"places":[{"name":"","location":"","background":"","why_important":""}],"concepts":[{"topic":"","category":"","explanation":"","related_topics":""}],"vocabulary":[{"word":"","meaning":"","simple_meaning":"","hindi":"","example":""}]}],
        "current_affairs":[{"topic":"","category":"","summary":"","why_important":"","source_url":""}],
        "culture":[{"topic":"","type":"","explanation":"","origin":"","significance":"","source_url":""}],
        "religion":[{"tradition":"","topic":"","explanation":"","historical_context":"","source_url":""}],
        "connect_the_dots":[{"chain":"","explanation":""}],
        "revision":[{"topic":"","question":"","answer":""}],
        "quiz":[{"question":"","answer":"","topic":"","difficulty":"easy|medium|hard"}],
    }
    return f"""Today is {today}. Build the morning knowledge briefing from the supplied evidence.\n\nExisting long-term knowledge:\n{json.dumps(previous, ensure_ascii=False)[:50000]}\n\nToday's articles:\n{json.dumps(compact, ensure_ascii=False)[:100000]}\n\nHistorical research (may be empty):\n{json.dumps(research or {}, ensure_ascii=False)[:50000]}\n\nReturn ONLY valid JSON matching this schema:\n{json.dumps(schema, ensure_ascii=False)}\n\nRules:\n- Pick 10-15 consequential, diverse stories; deduplicate articles into one story.\n- Rank by India relevance, human impact, geopolitical/economic significance, future consequences, and genuine novelty.\n- For continuing stories, use 2-6 earlier milestones only when supported by supplied evidence or existing knowledge.\n- Every important story must have at least one supplied source URL.\n- Current affairs: government decisions, appointments, reports, rankings, agreements, economy, defence, science and major international developments.\n- Culture/religion: educational, neutral and respectful; do not promote or rank religions.\n- Vocabulary: useful English drawn from today's stories, with simple English and Hindi.\n- Revision: prefer older concepts that are due for review.\n- Quiz: test understanding and cause/effect, not only memorisation.\n"""


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    return _call_ollama(_build_prompt(articles, previous, today, research), as_json=True)


def generate_text(prompt: str, system: str = "You are a factual knowledge teacher. Use only supplied data; do not invent.") -> str:
    return _call_ollama(prompt, system=system, as_json=False)


def configured_model() -> str:
    return _model_name()
