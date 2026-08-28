from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SYSTEM = """You are a rigorous news editor and knowledge teacher. Use ONLY supplied evidence. Never invent facts, dates, people, numbers or quotations. If evidence is missing, say 'Not stated in supplied sources'. Be concise."""
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


def _model_name() -> str:
    return os.getenv("AI_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL


def _call_ollama(prompt: str, system: str = SYSTEM, as_json: bool = False, num_predict: int | None = None):
    payload = {"model": _model_name(), "system": system, "prompt": prompt, "stream": False, "keep_alive": "10m",
               "options": {"temperature": 0.1, "num_ctx": int(os.getenv("AI_CONTEXT", "2048")),
                            "num_predict": num_predict or int(os.getenv("AI_MAX_OUTPUT", "500"))}}
    request = Request(_ollama_url(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "120"))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach Ollama: {exc.reason}") from exc
    text = result.get("response", "").strip()
    if not text: raise RuntimeError("Ollama returned an empty response")
    if not as_json: return text
    try: return json.loads(text)
    except json.JSONDecodeError as exc: raise RuntimeError(f"AI returned invalid JSON: {exc}. Raw: {text[:500]}") from exc


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{4,}", text.lower()))


def _deterministic_score(a: dict) -> float:
    title, summary = str(a.get("title", "")), str(a.get("summary", "")); source, category = str(a.get("source", "")).lower(), str(a.get("category", "")).lower()
    text = f"{title} {summary}".lower(); score = 35.0
    if any(x in source for x in ("reuters", "bbc", "associated press", "ap news", "the hindu", "indian express", "times of india", "pib")): score += 12
    if category in {"india", "national", "politics", "world", "economy", "business", "defence", "science", "technology"}: score += 8
    keywords = {"government":8,"supreme court":10,"parliament":9,"election":9,"prime minister":9,"president":8,"war":10,"conflict":9,"ceasefire":10,"terror":8,"defence":8,"military":8,"economy":7,"inflation":7,"interest rate":7,"rbi":9,"budget":8,"trade":7,"sanction":8,"nuclear":9,"space":7,"isro":9,"ai":6,"artificial intelligence":7,"climate":7,"earthquake":8,"cyclone":8,"flood":7,"health":6,"vaccine":6,"scam":7,"policy":6}
    for term, boost in keywords.items():
        if term in text: score += boost
    score += min(10, 2 * sum(x in text for x in ("million", "billion", "lakh", "crore", "dead", "killed", "injured", "arrested", "approved", "launched", "signed")))
    score += min(8, len(_words(title)) * 0.7)
    return min(100.0, score)


def select_stories(articles: list[dict], top_n: int = 12) -> list[dict]:
    ranked, seen_words = [], []
    for a in articles:
        title = str(a.get("title", "")).strip()
        if not title or not a.get("url"): continue
        words = _words(title)
        if any(len(words & old) / max(1, len(words | old)) >= 0.72 for old in seen_words): continue
        seen_words.append(words); ranked.append((round(_deterministic_score(a), 1), a))
    ranked.sort(key=lambda x: (-x[0], str(x[1].get("published", ""))))
    selected, categories = [], {}
    for score, a in ranked:
        category = str(a.get("category", "Other"))
        if categories.get(category, 0) >= max(3, top_n // 3): continue
        categories[category] = categories.get(category, 0) + 1
        headline = str(a.get("title", ""))[:240]; story_id = hashlib.sha1(headline.lower().encode("utf-8")).hexdigest()[:16]
        selected.append({"story_id": story_id, "rank": len(selected)+1, "headline": headline, "importance": score, "category": category, "url": str(a.get("url", "")), "reason": "Deterministic impact/source/relevance score."})
        if len(selected) >= top_n: break
    return selected


def _story_evidence(selected: list[dict], articles: list[dict], research: dict | None) -> list[dict]:
    by_url = {str(a.get("url", "")): a for a in articles}; evidence = []
    for s in selected:
        a = by_url.get(str(s.get("url", "")), {}); sid = s.get("story_id") or hashlib.sha1(str(s.get("headline", "")).lower().encode()).hexdigest()[:16]
        evidence.append({"story_id": sid, "headline": s.get("headline", ""), "importance": s.get("importance", 0), "category": s.get("category", ""), "source": a.get("source", ""), "url": s.get("url", ""), "summary": str(a.get("summary", ""))[:300], "historical": (research or {}).get(sid, [])[:2]})
    return evidence


def _story_one(item: dict, today: str) -> dict:
    prompt = f"Today {today}. Explain ONE news story using only evidence below. Return plain text ONLY, exactly these lines: WHAT: one short sentence; WHO: names if stated; WHEN: date/time if stated; WHERE: place if stated; WHY: one short sentence; WHY IMPORTANT: one short sentence; LEARN: one useful context sentence. Do not use JSON. Evidence: {json.dumps(item, ensure_ascii=False)}"
    text = _call_ollama(prompt, num_predict=150)
    out = {"story_id": item["story_id"], "headline": item["headline"], "importance": item["importance"], "category": item["category"], "what": item["summary"], "who": "Not stated in supplied sources", "when": "Not stated in supplied sources", "where": "Not stated in supplied sources", "why": "Not stated in supplied sources", "why_important": "Selected by importance score", "learn": "", "latest_update": item["summary"], "timeline": [], "sources": [item["url"]], "people": [], "places": [], "concepts": [], "vocabulary": []}
    keys = {"what","who","when","where","why","why_important","learn"}
    for line in text.splitlines():
        if ":" in line:
            k,v=line.split(":",1); k=k.strip().lower().replace(" ","_"); v=v.strip()
            if k in keys and v: out[k]=v
    return out


def _extras(evidence: list[dict], previous: dict, today: str) -> dict:
    compact = [{"headline": x["headline"], "summary": x["summary"]} for x in evidence]
    prompt = f"Today {today}. Based ONLY on these headlines and summaries, write plain text, not JSON. Sections: CURRENT AFFAIRS (2 short points); CULTURE (1 point only if supported); RELIGION (1 point only if supported); VOCABULARY (3 word-meaning pairs); REVISION (2 questions); QUIZ (2 questions with answers). Do not invent facts. Evidence: {json.dumps(compact, ensure_ascii=False)}"
    return {"text": _call_ollama(prompt, num_predict=260)}


def generate_briefing(selected: list[dict], articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    evidence = _story_evidence(selected, articles, research); stories=[]
    for i,item in enumerate(evidence,1):
        print(f"[AI] story {i}/{len(evidence)}", flush=True)
        try: stories.append(_story_one(item,today))
        except Exception as exc:
            print(f"[WARN] story {i} AI failed: {exc}", flush=True)
            stories.append({"story_id":item["story_id"],"headline":item["headline"],"importance":item["importance"],"category":item["category"],"what":item["summary"],"who":"Not stated in supplied sources","when":"Not stated in supplied sources","where":"Not stated in supplied sources","why":"Not stated in supplied sources","why_important":"Selected by importance score","learn":"","latest_update":item["summary"],"timeline":[],"sources":[item["url"]],"people":[],"places":[],"concepts":[],"vocabulary":[]})
    try: extra_text=_extras(evidence,previous,today).get("text","")
    except Exception as exc: print(f"[WARN] learning extras failed: {exc}",flush=True); extra_text=""
    return {"top_stories":stories[:12],"learning_text":extra_text}


def generate(articles: list[dict], previous: dict, today: str, research: dict | None = None) -> dict:
    return generate_briefing(select_stories(articles,12),articles,previous,today,research)


def generate_text(prompt: str, system: str = "You are a factual knowledge teacher. Use only supplied data; do not invent.") -> str:
    return _call_ollama(prompt,system=system,as_json=False)


def configured_model() -> str: return _model_name()
