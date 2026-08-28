from __future__ import annotations

import json
from openai import OpenAI

from .settings import OPENAI_API_KEY, OPENAI_MODEL

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence for factual claims. Never invent facts, dates, people, numbers or quotations. If evidence is insufficient, say so. Clearly distinguish today's development from older history. Prefer multiple independent sources. The goal is long-term knowledge: explain who/what/when/where/why, relevant history, cause-effect connections, useful concepts, vocabulary, and neutral cultural/religious context. Avoid sensationalism and political persuasion."""


def _client():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = OPENAI_MODEL.strip() or "gpt-4.1-mini"
    return OpenAI(api_key=OPENAI_API_KEY), model


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    client, model = _client()
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
    prompt = f"""Today is {today}. Build the morning knowledge briefing from the supplied evidence.

Existing long-term knowledge:
{json.dumps(previous, ensure_ascii=False)[:50000]}

Today's articles:
{json.dumps(compact, ensure_ascii=False)[:100000]}

Historical research for important story candidates (may be empty):
{json.dumps(research or {}, ensure_ascii=False)[:50000]}

Return ONLY valid JSON matching this schema. Do not wrap it in markdown:
{json.dumps(schema, ensure_ascii=False)}

Rules:
- Pick 10-15 consequential, diverse stories; deduplicate articles into one story.
- Rank by India relevance, human impact, geopolitical/economic significance, future consequences, and genuine novelty.
- For continuing stories, use 2-6 earlier milestones from historical research or existing knowledge. Do not invent a timeline.
- Every important story must have at least one source URL from supplied evidence.
- Current affairs: government decisions, appointments, reports, rankings, agreements, economy, defence, science and major international developments.
- Culture/religion: educational, neutral and respectful; do not promote or rank religions.
- Vocabulary: useful English drawn from today's stories, with simple English and Hindi.
- Revision: prefer older concepts that are due for review.
- Quiz: test understanding and cause/effect, not only memorisation.
"""
    response = client.responses.create(model=model, instructions=SYSTEM, input=prompt)
    text = response.output_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI returned invalid JSON: {exc}") from exc
