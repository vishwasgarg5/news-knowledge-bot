"""Offline capture of original news candidate pools for future evaluation."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _clean_text(value: Any) -> str:
    """Normalize feed text without inventing missing article content."""
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, dict):
                part = item.get("value") or item.get("text") or item.get("summary") or ""
            else:
                part = item
            cleaned = _clean_text(part)
            if cleaned:
                parts.append(cleaned)
        return " ".join(parts).strip()
    if isinstance(value, dict):
        value = value.get("value") or value.get("text") or value.get("title") or ""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _first_text(article: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = article.get(key)
        if isinstance(value, dict) and key == "source":
            value = value.get("title") or value.get("name") or ""
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def build_capture_record(
    articles: list[dict[str, Any]],
    included_urls: set[str],
    run_id: str,
    run_timestamp: str,
    policy_version: str,
) -> dict[str, Any]:
    """Build a candidate-pool record without manufacturing truth labels."""
    candidates = []
    seen_ids: set[str] = set()
    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            continue
        url = _first_text(article, "url", "link")
        title = _first_text(article, "title", "headline")
        source = _first_text(article, "source", "publisher")
        published = _first_text(article, "published", "published_at", "publication_date", "date")
        summary_fields = ("summary", "description", "snippet", "abstract", "content")
        summary = _first_text(article, *summary_fields)
        # Prefer provenance recorded at the feed-parser boundary. Generic/offline
        # candidate inputs retain the normalized-field fallback for compatibility.
        source_diagnostics = article.get("summary_field_diagnostics")
        if isinstance(source_diagnostics, dict) and source_diagnostics:
            summary_field_diagnostics = {
                str(key): str(value) for key, value in source_diagnostics.items()
            }
            summary_selected_field = article.get("summary_selected_field")
        else:
            summary_field_diagnostics = {
                key: (
                    "missing_key" if key not in article else
                    "blank" if not _clean_text(article.get(key)) else
                    "present"
                )
                for key in summary_fields
            }
            summary_selected_field = next(
                (key for key in summary_fields if summary_field_diagnostics[key] == "present"),
                None,
            )
        identity = url or f"{source}|{title}|{published}|{index}"
        candidate_id = "candidate-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        candidates.append({
            "candidate_id": candidate_id,
            "title": title,
            "category": _first_text(article, "category"),
            "source": source,
            "url": url,
            "published_at": published,
            "summary": summary,
            # Preserve field presence without storing duplicate publisher text; this makes
            # future blank-summary captures diagnosable without live-feed replay.
            "summary_selected_field": summary_selected_field,
            "summary_field_diagnostics": summary_field_diagnostics,
            "disposition": "included" if url and url in included_urls else "excluded",
        })
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "policy_version": policy_version or "unversioned",
        "labeling_status": "pending_review",
        "candidate_articles": candidates,
        "story_labels": [],
    }


def write_capture_record(
    articles: list[dict[str, Any]],
    included_urls: set[str],
    output_dir: Path,
    run_timestamp: str,
    run_slot: str = "scheduled",
    policy_version: str = "unversioned",
) -> Path:
    """Atomically persist a capture record. Never creates labels or changes ranking."""
    timestamp = datetime.fromisoformat(run_timestamp.replace("Z", "+00:00"))
    stamp = timestamp.strftime("%Y%m%dT%H%M%S%z")
    safe_slot = "".join(char if char.isalnum() or char in "-_" else "_" for char in run_slot) or "scheduled"
    run_id = f"{stamp}-{safe_slot}"
    record = build_capture_record(articles, included_urls, run_id, run_timestamp, policy_version)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{run_id}.json"
    fd, temp_name = tempfile.mkstemp(prefix=".evaluation-record-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return destination
