from __future__ import annotations
import csv
from pathlib import Path

HEADERS={
 "news_history.csv":["date","story_id","headline","source","url","category","importance","region","verification","confidence"],
 "story_timeline.csv":["story_id","date","headline","event","importance","source","url","change_type"],
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
