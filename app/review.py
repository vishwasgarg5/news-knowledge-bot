from __future__ import annotations
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from .ai import generate_text
from .learning import due_items
from .settings import DATA
from .storage import read_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata")
def _chunks(text,limit=3900):
    parts=[]
    while len(text)>limit:
        cut=text.rfind("\n\n",0,limit);cut=cut if cut>=500 else text.rfind("\n",0,limit);cut=cut if cut>=500 else limit;parts.append(text[:cut].strip());text=text[cut:].strip()
    if text:parts.append(text)
    return parts
def run_review(kind:str):
    today=datetime.now(IST).date();start=today-timedelta(days=7 if kind=="weekly" else 31)
    due=due_items(str(today))[:25]
    payload={"news":read_rows(DATA/"news_history.csv")[-700:],"knowledge":read_rows(DATA/"knowledge_cards.csv")[-400:],"vocabulary":read_rows(DATA/"vocabulary.csv")[-400:],"current_affairs":read_rows(DATA/"current_affairs.csv")[-400:],"quiz":read_rows(DATA/"quiz_history.csv")[-150:],"graph":read_rows(DATA/"knowledge_graph.csv")[-300:],"due_revision":due}
    prompt=f"""Create a {kind} adaptive knowledge review for {start} to {today}. Use ONLY supplied data; never invent. Prioritize weak/overdue topics and durable knowledge. Return Telegram-ready text. Structure as a flowchart/memory map. Include: 1) INDIA recall, 2) WORLD recall, 3) 5 questions with ANSWER immediately after each and WHY IT MATTERS, 4) overdue/weak topics, 5) vocabulary revision with simple meaning and example, 6) 5 connect-the-dots relationships, 7) key people/places/concepts, 8) final QUICK MEMORY map. Difficulty should rise for mastered topics and fall for weak topics. Data: {json.dumps(payload,ensure_ascii=False)[:100000]}"""
    text=generate_text(prompt)
    header="📚 WEEKLY ADAPTIVE KNOWLEDGE REVIEW" if kind=="weekly" else "📚 MONTHLY ADAPTIVE KNOWLEDGE REVIEW"
    for part in _chunks(header+"\n\n"+text):send_text(part)
if __name__=="__main__":
    import sys
    run_review(sys.argv[1] if len(sys.argv)>1 else "weekly")
