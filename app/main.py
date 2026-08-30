from __future__ import annotations
import os,re,hashlib
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import yaml
from .ai import configured_model,generate_briefing,select_stories
from .learning import daily_learning
from .news import collect
from .research import research_stories
from .settings import CONFIG,DATA,TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID
from .storage import HEADERS,append_rows,ensure_data,read_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata"); TEST_MODE=os.environ.get("TEST_MODE","0").lower() in {"1","true","yes"}; RUN_SLOT=os.environ.get("RUN_SLOT","morning").lower()
def log(stage,status,message): print(f"[{status}] {stage}: {message}",flush=True)
def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)
def history_snapshot():return {name[:-4]:read_rows(DATA/name)[-500:] for name in HEADERS}
def topic_id(headline):
    words=[w for w in re.findall(r"[A-Za-z]{4,}",str(headline).lower()) if w not in {"today","latest","says","after","amid","over","news","india"}]
    return hashlib.sha1((" ".join(words[:10]) or str(headline).lower()).encode()).hexdigest()[:16]
def yesterday_changes(stories,history,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat();prev={re.sub(r"\W+"," ",str(r.get("headline","")).lower()).strip() for r in history if str(r.get("date",""))==yesterday}
    for s in stories:
        h=re.sub(r"\W+"," ",str(s.get("headline","")).lower()).strip();s["change_since_yesterday"]="New topic today" if h not in prev else "Continuing story"
    return stories
def build_messages(result,today):
    stories=result.get("top_stories",[]);label="MORNING" if RUN_SLOT=="morning" else "AFTERNOON";msgs=[f"🧠 <b>DAILY NEWS + KNOWLEDGE BRIEF — {label}</b>\n{today}\n\nAutomatic briefing • {len(stories)} unique stories"]
    for i,s in enumerate(stories,1):
        text=f"🔥 <b>STORY {i}/{len(stories)}</b>\n\n<b>{s.get('headline','')}</b> — {s.get('importance',0)}/100\n\n<b>What:</b> {s.get('what','')}\n<b>Who:</b> {s.get('who','')}\n<b>When:</b> {s.get('when','')}\n<b>Where:</b> {s.get('where','')}\n<b>Why:</b> {s.get('why','')}\n<b>Why important:</b> {s.get('why_important','')}\n<b>Latest:</b> {s.get('latest_update','')}\n<b>Change:</b> {s.get('change_since_yesterday','')}\n"
        for k,label2 in (("background","Background"),("perspective","Perspective"),("next","Next"),("entities","Entities")):
            if s.get(k):text+=f"<b>{label2}:</b> {s[k]}\n"
        if s.get("timeline"):
            past=[x.get("title") or x.get("headline") or x.get("event","") for x in s["timeline"][:3]];past=[x for x in past if x]
            if past:text+="<b>Past:</b> "+" | ".join(past)+"\n"
        if s.get("sources"):text+="\n🔗 "+" | ".join(s["sources"][:3])
        msgs.append(text)
    rh=result.get("research_stats",{});msgs.append(f"📚 <b>HISTORICAL CONTEXT</b>\nEvidence: {rh.get('ok',0)}/{rh.get('total',0)} stories\nGitHub memory matches: {rh.get('memory_ok',0)}\nStatus: {rh.get('status','UNKNOWN')}")
    return msgs
def _vocab_words(story):
    text=f"{story.get('what','')} {story.get('why','')} {story.get('background','')}"; words=re.findall(r"\b[A-Za-z]{7,}\b",text)
    stop={"because","important","government","development","according","following","between","including","international","situation","background","provided","sources"};return list(dict.fromkeys(w.lower() for w in words if w.lower() not in stop))[:3]
def persist(result,today):
    ensure_data(DATA);stories=result.get("top_stories",[]);history=read_rows(DATA/"news_history.csv");existing={r.get("story_id") for r in history};cards=read_rows(DATA/"knowledge_cards.csv");cardmap={r.get("topic_id"):r for r in cards};timeline=read_rows(DATA/"story_timeline.csv");timeline_keys={(r.get("story_id"),r.get("date")) for r in timeline};affairs=read_rows(DATA/"current_affairs.csv");affair_keys={(r.get("topic"),r.get("date")) for r in affairs};quizzes=read_rows(DATA/"quiz_history.csv");quiz_keys={r.get("question") for r in quizzes};vocab=read_rows(DATA/"vocabulary.csv");vocab_keys={r.get("word","").lower() for r in vocab}
    for s in stories:
        sid=s.get("story_id");url=(s.get("sources") or [""])[0];headline=s.get("headline","");tid=topic_id(headline);old=cardmap.get(tid);first=old.get("first_seen",today) if old else today;count=int(old.get("review_count",0) or 0) if old else 0
        if sid and sid not in existing:append_rows(DATA/"news_history.csv",[{"date":today,"story_id":sid,"headline":headline,"source":"","url":url,"category":s.get("category"),"importance":s.get("importance",0)}],HEADERS["news_history.csv"]);existing.add(sid)
        if (sid,today) not in timeline_keys:append_rows(DATA/"story_timeline.csv",[{"story_id":sid,"date":today,"headline":headline,"event":s.get("latest_update",s.get("what","")),"importance":s.get("importance",0),"source":"","url":url}],HEADERS["story_timeline.csv"]);timeline_keys.add((sid,today))
        if (headline,today) not in affair_keys:append_rows(DATA/"current_affairs.csv",[{"date":today,"topic":headline,"category":s.get("category",""),"summary":s.get("what",s.get("latest_update","")),"why_important":s.get("why_important",""),"source_url":url}],HEADERS["current_affairs.csv"]);affair_keys.add((headline,today))
        append_rows(DATA/"knowledge_cards.csv",[{"topic_id":tid,"topic":headline,"category":s.get("category",""),"explanation":s.get("learn",s.get("what","")),"related_topics":"","first_seen":first,"last_reviewed":today,"review_count":count+1}],HEADERS["knowledge_cards.csv"])
        q=f"Why is this news important: {headline}?";answer=s.get("why_important","") or s.get("what","")
        if q not in quiz_keys:append_rows(DATA/"quiz_history.csv",[{"date":today,"question":q,"answer":answer,"topic":headline,"difficulty":"easy"}],HEADERS["quiz_history.csv"]);quiz_keys.add(q)
        for word in _vocab_words(s):
            if word not in vocab_keys:append_rows(DATA/"vocabulary.csv",[{"word":word,"meaning":f"Used in the context of: {headline}","simple_meaning":s.get("learn",s.get("what",""))[:300],"hindi":"","example":s.get("what","")[:300],"first_seen":today,"review_count":0,"next_review":today}],HEADERS["vocabulary.csv"]);vocab_keys.add(word)
def main():
    print("="*60);print(f"🧠 NEWS KNOWLEDGE BOT — {RUN_SLOT.upper()} RUN");print("="*60);log("Environment","PASS",f"Python runtime ready; slot={RUN_SLOT}; test_mode={TEST_MODE}");log("AI provider","INFO",f"Local Ollama; model={configured_model()}");tg=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID);ensure_data(DATA);cfg=load_sources();limits=cfg.get("limits",{});articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",500));log("News collection","PASS" if articles else "FAIL",f"Collected {len(articles)} articles");today=datetime.now(IST).date().isoformat();previous=history_snapshot();daily_learning();today_history=previous.get("news_history",[]);delivered_today=[r.get("headline","") for r in today_history if str(r.get("date",""))==today];selected=select_stories([a.__dict__ for a in articles],top_n=12,excluded_headlines=delivered_today);selected=yesterday_changes(selected,today_history,today);log("Story selection","PASS",f"Selected {len(selected)} NEW stories; excluded {len(delivered_today)} already delivered today");historical=research_stories(selected,today_history);stats=historical.pop("_stats",{"ok":0,"memory_ok":0,"failed":len(selected),"total":len(selected),"status":"FAIL"});result=generate_briefing(selected,[a.__dict__ for a in articles],previous,today,historical);result["research_stats"]=stats;persist(result,today);log("Knowledge persistence","PASS",f"Updated current affairs, knowledge cards, vocabulary and quiz memory for {len(result.get('top_stories',[]))} stories")
    if tg:
        messages=build_messages(result,today)
        for message in messages:send_text(message)
        log("Telegram delivery","PASS",f"Sent {len(result.get('top_stories',[]))} story messages individually")
if __name__=="__main__":main()
