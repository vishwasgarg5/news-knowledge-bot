from __future__ import annotations
import re
from datetime import date
from urllib.parse import quote
import requests
from .settings import DATA
from .storage import append_rows, HEADERS, read_rows
CULTURE_TOPICS=["Indian classical music","Kathak","Bharatanatyam","Indian architecture","UNESCO Intangible Cultural Heritage","Indian textiles","Japanese tea ceremony","Persian literature","African traditional music","Greek theatre","Mughal architecture","Sanskrit literature","Indian folk art","World heritage sites"]
RELIGION_TOPICS=["Hinduism","Buddhism","Jainism","Sikhism","Islam","Christianity","Judaism","Zoroastrianism","Baháʼí Faith","Confucianism","Taoism","Shinto"]
STOP={"about","after","before","their","there","which","where","while","would","could","should","today","latest","india","from","that","this","with","have","been","will","into","than","they","were","said","over","amid","also","more","news","says"}
def wiki_summary(title):
    url="https://en.wikipedia.org/api/rest_v1/page/summary/"+quote(title.replace(" ","_"),safe="_")
    try:
        r=requests.get(url,headers={"User-Agent":"NewsKnowledgeBot/2.0"},timeout=10); r.raise_for_status(); d=r.json()
        return {"title":d.get("title",title),"extract":d.get("extract","")[:1200],"url":d.get("content_urls",{}).get("desktop",{}).get("page","")}
    except Exception: return {"title":title,"extract":"","url":""}
def daily_learning():
    day=date.today().toordinal(); culture=wiki_summary(CULTURE_TOPICS[day%len(CULTURE_TOPICS)]); religion=wiki_summary(RELIGION_TOPICS[day%len(RELIGION_TOPICS)])
    if culture["extract"]: append_rows(DATA/"culture.csv",[{"date":str(date.today()),"topic":culture["title"],"type":"culture","explanation":culture["extract"],"origin":"","significance":"","source_url":culture["url"]}],HEADERS["culture.csv"])
    if religion["extract"]: append_rows(DATA/"religion.csv",[{"date":str(date.today()),"tradition":religion["title"],"topic":religion["title"],"explanation":religion["extract"],"historical_context":"","source_url":religion["url"]}],HEADERS["religion.csv"])
    return {"culture":culture,"religion":religion}
def extract_vocabulary(stories,today):
    rows=read_rows(DATA/"vocabulary.csv"); known={str(r.get("word","")).lower() for r in rows}; new=[]
    for s in stories:
        text=f"{s.get('headline','')} {s.get('what','')} {s.get('background','')} {s.get('why_important','')}"; words=re.findall(r"\b[A-Za-z][A-Za-z-]{6,}\b",text)
        for w in words:
            lw=w.lower().strip("-")
            if lw in STOP or lw in known or len(lw)<7 or len(set(lw))<4: continue
            new.append({"word":w,"meaning":f"News-context meaning: {w}","simple_meaning":"Meaning should be explained during review","hindi":"","example":text[:180],"first_seen":today,"review_count":0,"next_review":today}); known.add(lw)
            if len(new)>=30: return new
    return new
def persist_daily_learning(stories,today):
    rows=extract_vocabulary(stories,today)
    if rows: append_rows(DATA/"vocabulary.csv",rows,HEADERS["vocabulary.csv"])
    return len(rows)
