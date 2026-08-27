from __future__ import annotations

import json
from datetime import date
from openai import OpenAI

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY the supplied article evidence for factual claims. Never invent facts, dates, people, numbers or quotations. If evidence is insufficient, say so. Separate current facts from background. Prefer multiple independent sources when available. The goal is long-term knowledge: explain who/what/when/where/why, relevant history, cause-effect connections, useful concepts, vocabulary, and neutral cultural/religious context. Avoid sensationalism and political persuasion."""


def _client():
    from .settings import OPENAI_API_KEY, OPENAI_MODEL
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY), OPENAI_MODEL


def generate(articles: list[dict], previous: dict, today: str) -> dict:
    client, model = _client()
    compact = [{k: a.get(k, "") for k in ("title", "summary", "url", "source", "category", "published")} for a in articles]
    prompt = f"""Today is {today}. Select and build the morning knowledge briefing from the supplied articles.

Existing long-term knowledge (may be empty):
{json.dumps(previous, ensure_ascii=False)[:50000]}

Articles:
{json.dumps(compact, ensure_ascii=False)[:100000]}

Return ONLY valid JSON with this structure:
{{
  "top_stories": [{{"story_id":"stable_slug","headline":"","importance":0,"category":"","what":"","who":"","when":"","where":"","why":"","why_important":"","latest_update":"","timeline":[{{"date":"","headline":"","event":"","source_url":""}}],"sources":[""],"people":[{{"name":"","role":"","background":"","why_in_news":""}}],"places":[{{"name":"","location":"","background":"","why_important":""}}],"concepts":[{{"topic":"","category":"","explanation":"","related_topics":""}}],"vocabulary":[{{"word":"","meaning":"","simple_meaning":"","hindi":"","example":""}}]}],
  "current_affairs":[{{"topic":"","category":"","summary":"","why_important":"","source_url":""}}],
  "culture": [{{"topic":"","type":"","explanation":"","origin":"","significance":"","source_url":""}}],
  "religion": [{{"tradition":"","topic":"","explanation":"","historical_context":"","source_url":""}}],
  "connect_the_dots":[{{"chain":"","explanation":""}}],
  "revision":[{{"topic":"","question":"","answer":""}}],
  "quiz":[{{"question":"","answer":"","topic":"","difficulty":"easy|medium|hard"}}]
}}

Rules:
- Pick the most consequential, diverse stories; normally 10-15.
- Deduplicate articles into one story.
- Do not fill the briefing with celebrity/sports/viral stories unless genuinely nationally or globally important.
- For continuing stories, include 2-6 relevant earlier milestones ONLY when supported by the supplied evidence or existing knowledge.
- Current affairs should prioritize government decisions, appointments, reports, rankings, agreements, economy, defence, science and major international developments.
- Culture/religion should be educational and neutral; avoid preaching or ranking religions.
- Vocabulary should be useful English drawn from today's stories; include Hindi meaning.
- Revision must reuse older concepts when available.
- Quiz tests understanding, not trivia.
"""
    response = client.responses.create(model=model, instructions=SYSTEM, input=prompt)
    text = response.output_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)
