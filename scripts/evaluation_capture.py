"""Offline capture of original news candidate pools for future evaluation."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


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
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or article.get("headline") or "").strip()
        source = str(article.get("source") or "").strip()
        published = str(article.get("published") or article.get("published_at") or "").strip()
        summary = str(article.get("summary") or article.get("description") or "").strip()
        identity = url or f"{source}|{title}|{published}|{index}"
        candidate_id = "candidate-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        candidates.append({
            "candidate_id": candidate_id,
            "title": title,
            "source": source,
            "url": url,
            "published_at": published,
            "summary": summary,
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
