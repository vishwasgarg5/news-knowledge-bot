from __future__ import annotations
import csv
import sqlite3\nimport os\nimport tempfile
from pathlib import Path

HEADERS={
 "news_history.csv":["date","story_id","event_id","headline","source","url","category","importance","region","verification","confidence","event_status","source_count"],
 "story_timeline.csv":["story_id","event_id","date","headline","event","importance","source","url","change_type","event_status"],
 "news_learning_daily.csv":["date","evaluated","selected_evaluated","misses","false_positives","success_rate","false_positive_rate","miss_rate"],
 "news_learning.csv":["run_date","event_id","story_id","headline","source","category","initial_score","selected","seen_again_24h","seen_again_48h","seen_again_7d","missed","false_positive","learning_value","outcome_score"],
}

def _write(path,rows,fields):
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def ensure_data(root:Path):
    root.mkdir(parents=True,exist_ok=True)
    for name,fields in HEADERS.items():
        path=root/name
        if not path.exists(): _write(path,[],fields)
        else:
            try:
                with path.open(newline="",encoding="utf-8") as f:
                    r=csv.DictReader(f);old=r.fieldnames or [];rows=list(r)
                if old!=fields:_write(path,rows,fields)
            except Exception as exc: print(f"[WARN] storage check failed for {name}: {exc}",flush=True)

def read_rows(path:Path)->list[dict]:
    if not path.exists():return []
    with path.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))

def append_rows(path:Path,rows:list[dict],fields:list[str]):
    if not rows:return
    header=not path.exists() or path.stat().st_size==0
    with path.open("a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        if header:w.writeheader()
        w.writerows(rows)

def replace_rows(path:Path,rows:list[dict],fields:list[str]):_write(path,rows,fields)


SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, headline TEXT, category TEXT, region TEXT, importance REAL, status TEXT, source_count INTEGER);
CREATE TABLE IF NOT EXISTS articles (article_id TEXT PRIMARY KEY, event_id TEXT, date TEXT, headline TEXT, source TEXT, url TEXT UNIQUE, category TEXT, importance REAL);
CREATE TABLE IF NOT EXISTS event_sources (event_id TEXT, source TEXT, url TEXT, date TEXT, PRIMARY KEY(event_id, source, url));
CREATE TABLE IF NOT EXISTS learning_outcomes (run_date TEXT, event_id TEXT, story_id TEXT, source TEXT, category TEXT, initial_score REAL, selected INTEGER, outcome_score REAL, seen_24h INTEGER, seen_48h INTEGER, seen_7d INTEGER, missed INTEGER, false_positive INTEGER, PRIMARY KEY(run_date,event_id));
CREATE INDEX IF NOT EXISTS idx_articles_event ON articles(event_id);
CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date);
"""

def sync_sqlite(root: Path):
    db = root / "news_knowledge.db"
    with sqlite3.connect(db) as con:
        con.executescript(SQL_SCHEMA)
        for r in read_rows(root / "news_history.csv"):
            con.execute("INSERT OR REPLACE INTO articles VALUES (?,?,?,?,?,?,?,?)", (r.get("story_id",""),r.get("event_id",""),r.get("date",""),r.get("headline",""),r.get("source",""),r.get("url",""),r.get("category",""),float(r.get("importance") or 0)))
            con.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?)", (r.get("event_id",""),r.get("date",""),r.get("date",""),r.get("headline",""),r.get("category",""),r.get("region",""),float(r.get("importance") or 0),r.get("event_status") or "NEW",int(float(r.get("source_count") or 0))))
            con.execute("INSERT OR IGNORE INTO event_sources VALUES (?,?,?,?)", (r.get("event_id",""),r.get("source",""),r.get("url",""),r.get("date","")))
        con.commit()
    return db