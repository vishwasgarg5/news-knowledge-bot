from __future__ import annotations
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .ai import generate_text
from .settings import DATA
from .storage import read_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata")

def _chunks(text,limit=3900):
    parts=[]
    while len(text)>limit:
        cut=text.rfind("\n\n",0,limit)
        if cut<500: cut=text.rfind("\n",0,limit)
        if cut<500: cut=limit
        parts.append(text[:cut].strip()); text=text[cut:].strip()
    if text: parts.append(text)
    return parts

def run_review(kind:str):
    today=datetime.now(IST).date(); start=today-timedelta(days=7 if kind=="weekly" else 31)
    payload={"news":read_rows(DATA/"news_history.csv")[-500:],"knowledge":read_rows(DATA/"knowledge_cards.csv")[-300:],"vocabulary":read_rows(DATA/"vocabulary.csv")[-300:],"current_affairs":read_rows(DATA/"current_affairs.csv")[-300:],"quiz":read_rows(DATA/"quiz_history.csv")[-100:]}
    prompt=f"""Create a {kind} knowledge review for {start} to {today}. Use ONLY supplied data; never invent. Return Telegram-ready plain text. Include 5 high-value questions and put the ANSWER immediately after every question, followed by WHY IT MATTERS. Also include: top stories with key facts, important current-affairs facts, concepts learned, people/places, vocabulary revision, 5 connect-the-dots relationships, and a final QUICK MEMORY section. Prefer durable knowledge and connections over repeating headlines. Format each quiz item exactly: Q1: ...\nANSWER: ...\nWHY IT MATTERS: ... Data: {json.dumps(payload,ensure_ascii=False)[:80000]}"""
    text=generate_text(prompt)
    header="📚 WEEKLY KNOWLEDGE REVIEW" if kind=="weekly" else "📚 MONTHLY KNOWLEDGE REVIEW"
    for part in _chunks(header+"\n\n"+text): send_text(part)

if __name__=="__main__":
    import sys
    run_review(sys.argv[1] if len(sys.argv)>1 else "weekly")
