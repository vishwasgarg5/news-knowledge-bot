from __future__ import annotations
import csv
import sqlite3
import os
import tempfile
from pathlib import Path

HEADERS={
 "news_history.csv":["date","story_id","event_id","headline","source","url","category","importance","region","verification","confidence","event_status","source_count"],
 "story_timeline.csv":["story_id","event_id","date","headline","event","importance","source","url","change_type","event_status"],
 "news_learning_daily.csv":["date","evaluated","selected_evaluated","misses","false_positives","success_rate","false_positive_rate","miss_rate"],
 "news_learning.csv":["run_date","event_id","story_id","headline","source","category","initial_score","selected","seen_again_24h","seen_again_48h","seen_again_7d","missed","false_positive","learning_value","outcome_score"],
 "news_feedback.csv":["date","story_id","event_id","feedback","note"],
 "entity_memory.csv":["date","entity","type","current_mentions","historical_mentions"],
 "event_memory.csv":["date","event_id","headline","status","story_count","source_count"],
 "knowledge_edges.csv":["date","from_node","to_node","edge_type"],
 "research_reports.csv":["date","headline","priority","finding"],
 "knowledge_daily.csv":["date","stories","high_impact","new_events","developing_events","confirmed_events","contradictions","research_items"],
 "knowledge_weekly.csv":["week","stories","top_categories","top_entities","new_events","developing_events","confirmed_events","anomalies","research_items"],
}

def _write(path,rows,fields):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():
            tmp.unlink()

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


def validate_data(root: Path):
    """Validate persisted CSV schemas and required SQLite tables."""
    root=Path(root); issues=[]
    for name,fields in HEADERS.items():
        path=root/name
        if not path.exists(): issues.append(f"missing:{name}"); continue
        try:
            with path.open(newline="",encoding="utf-8") as f:
                if (csv.DictReader(f).fieldnames or []) != fields: issues.append(f"schema:{name}")
        except Exception as exc: issues.append(f"read:{name}:{exc}")
    db=root/"news_knowledge.db"
    if db.exists():
        try:
            with sqlite3.connect(db) as con:
                tables={x[0] for x in con.execute("select name from sqlite_master where type='table'")}
            for table in ("events","articles","event_sources","learning_outcomes"):
                if table not in tables: issues.append(f"sqlite_table:{table}")
        except Exception as exc: issues.append(f"sqlite:{exc}")
    return {"ok":not issues,"issues":issues}
def sync_sqlite(root: Path):
    db = root / "news_knowledge.db"
    with sqlite3.connect(db) as con:
        con.executescript(SQL_SCHEMA)
        for r in read_rows(root / "news_history.csv"):
            event_id=r.get("event_id","")
            article_id=r.get("story_id","")
            if article_id:
                con.execute("INSERT OR REPLACE INTO articles VALUES (?,?,?,?,?,?,?,?)", (article_id,event_id,r.get("date",""),r.get("headline",""),r.get("source",""),r.get("url",""),r.get("category",""),float(r.get("importance") or 0)))
            if event_id:
                con.execute("""INSERT INTO events(event_id,first_seen,last_seen,headline,category,region,importance,status,source_count)
                               VALUES (?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(event_id) DO UPDATE SET
                                 first_seen=MIN(events.first_seen,excluded.first_seen),
                                 last_seen=MAX(events.last_seen,excluded.last_seen),
                                 headline=excluded.headline,category=excluded.category,region=excluded.region,
                                 importance=excluded.importance,status=excluded.status,source_count=MAX(events.source_count,excluded.source_count)""",
                            (event_id,r.get("date",""),r.get("date",""),r.get("headline",""),r.get("category",""),r.get("region",""),float(r.get("importance") or 0),r.get("event_status") or "NEW",int(float(r.get("source_count") or 0))))
                con.execute("INSERT OR IGNORE INTO event_sources VALUES (?,?,?,?)", (event_id,r.get("source",""),r.get("url",""),r.get("date","")))
        for r in read_rows(root / "news_learning.csv"):
            event_id=r.get("event_id","")
            if not event_id: continue
            con.execute("""INSERT OR REPLACE INTO learning_outcomes
                (run_date,event_id,story_id,source,category,initial_score,selected,outcome_score,seen_24h,seen_48h,seen_7d,missed,false_positive)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r.get("run_date",""),event_id,r.get("story_id",""),r.get("source",""),r.get("category",""),float(r.get("initial_score") or 0),
                 1 if str(r.get("selected","")).lower() in {"true","1","yes"} else 0,
                 float(r.get("outcome_score") or r.get("learning_value") or 0),
                 1 if r.get("seen_again_24h")=="1" else 0,1 if r.get("seen_again_48h")=="1" else 0,1 if r.get("seen_again_7d")=="1" else 0,
                 1 if r.get("missed")=="1" else 0,1 if r.get("false_positive")=="1" else 0))
        con.commit()
    return db