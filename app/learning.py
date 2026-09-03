from __future__ import annotations
import re
from datetime import date,timedelta
from urllib.parse import quote
import requests
from .settings import DATA
from .storage import append_rows,HEADERS,read_rows,replace_rows
CULTURE_TOPICS=["Indian classical music","Kathak","Bharatanatyam","Indian architecture","UNESCO Intangible Cultural Heritage","Indian textiles","Japanese tea ceremony","Persian literature","African traditional music","Greek theatre","Mughal architecture","Sanskrit literature","Indian folk art","World heritage sites"]
RELIGION_TOPICS=["Hinduism","Buddhism","Jainism","Sikhism","Islam","Christianity","Judaism","Zoroastrianism","Baháʼí Faith","Confucianism","Taoism","Shinto"]
STOP={"about","after","before","their","there","which","where","while","would","could","should","today","latest","india","from","that","this","with","have","been","will","into","than","they","were","said","over","amid","also","more","news","says"}
def wiki_summary(title):
    url="https://en.wikipedia.org/api/rest_v1/page/summary/"+quote(title.replace(" ","_"),safe="_")
    try:
        r=requests.get(url,headers={"User-Agent":"NewsKnowledgeBot/5.0"},timeout=10);r.raise_for_status();d=r.json();return {"title":d.get("title",title),"extract":d.get("extract","")[:1400],"url":d.get("content_urls",{}).get("desktop",{}).get("page","")}
    except Exception:return {"title":title,"extract":"","url":""}
def daily_learning():
    day=date.today().toordinal();culture=wiki_summary(CULTURE_TOPICS[day%len(CULTURE_TOPICS)]);religion=wiki_summary(RELIGION_TOPICS[day%len(RELIGION_TOPICS)])
    if culture["extract"]:append_rows(DATA/"culture.csv",[{"date":str(date.today()),"topic":culture["title"],"type":"culture","explanation":culture["extract"],"origin":"","significance":"","source_url":culture["url"]}],HEADERS["culture.csv"])
    if religion["extract"]:append_rows(DATA/"religion.csv",[{"date":str(date.today()),"tradition":religion["title"],"topic":religion["title"],"explanation":religion["extract"],"historical_context":"","source_url":religion["url"]}],HEADERS["religion.csv"])
    return {"culture":culture,"religion":religion}
def _candidate_words(stories):
    found=[]
    for s in stories:
        text=f"{s.get('headline','')} {s.get('what','')} {s.get('why','')} {s.get('background','')} {s.get('why_important','')}"
        for w in re.findall(r"\b[A-Za-z][A-Za-z-]{6,}\b",text):
            lw=w.lower().strip("-")
            if lw not in STOP and len(set(lw))>=4:found.append((lw,w,s))
    return found
def extract_vocabulary(stories,today):
    known={str(r.get("word","")).lower() for r in read_rows(DATA/"vocabulary.csv")};new=[]
    for lw,w,s in _candidate_words(stories):
        if lw in known:continue
        new.append({"word":w,"meaning":"","simple_meaning":"","hindi":"","example":s.get("what","")[:250],"first_seen":today,"review_count":0,"next_review":today,"last_seen":today,"mastery":0});known.add(lw)
        if len(new)>=12:break
    return new
def due_items(today=None):
    today=today or str(date.today());items=[r for r in read_rows(DATA/"learning_progress.csv") if str(r.get("next_review",today))<=today];items += [r for r in read_rows(DATA/"vocabulary.csv") if str(r.get("next_review",today))<=today];items.sort(key=lambda r:(float(r.get("mastery",0) or 0),str(r.get("last_seen",r.get("first_seen","")))));return items
def update_review(topic_id,correct,today=None):
    today=today or str(date.today());rows=read_rows(DATA/"learning_progress.csv")
    for r in rows:
        if r.get("topic_id")==topic_id:
            mastery=float(r.get("mastery",0) or 0);reviews=int(r.get("review_count",0) or 0)+1;mastery=min(100,mastery+12 if correct else max(0,mastery-15));interval=1 if not correct else (3 if mastery<50 else 7 if mastery<80 else 21);r.update({"review_count":reviews,"last_seen":today,"next_review":str(date.fromisoformat(today)+timedelta(days=interval)),"mastery":round(mastery,1),"priority":"high" if mastery<50 else "normal"})
    replace_rows(DATA/"learning_progress.csv",rows,HEADERS["learning_progress.csv"])
def persist_daily_learning(stories,today):
    rows=extract_vocabulary(stories,today)
    if rows:append_rows(DATA/"vocabulary.csv",rows,HEADERS["vocabulary.csv"])
    return len(rows)
