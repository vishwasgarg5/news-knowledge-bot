from __future__ import annotations
import os,re,hashlib,time
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
STOP=set("about after before their there which where while would could should today latest india from that this with have been will into than they were said over amid also more news says government development according following between including international situation background provided sources".split())
def log(stage,status,message): print(f"[{status}] {stage}: {message}",flush=True)
def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)
def history_snapshot():return {name[:-4]:read_rows(DATA/name)[-1000:] for name in HEADERS}
def topic_id(headline):
    words=[w for w in re.findall(r"[A-Za-z]{4,}",str(headline).lower()) if w not in STOP];return hashlib.sha1((" ".join(words[:12]) or str(headline).lower()).encode()).hexdigest()[:16]
def _norm(text):return re.sub(r"\W+"," ",str(text).lower()).strip()
def _tokens(text):return set(w for w in re.findall(r"[a-z]{4,}",_norm(text)) if w not in STOP)
def _sim(a,b):
    x,y=_tokens(a),_tokens(b);return len(x&y)/max(1,len(x|y))
def yesterday_changes(stories,history,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat();prev=[r.get("headline","") for r in history if str(r.get("date",""))==yesterday]
    for s in stories:s["change_since_yesterday"]="Continuing story" if any(_sim(s.get("headline",""),h)>=.48 for h in prev) else "New topic today"
    return stories
def build_messages(result,today,stats):
    stories=result.get("top_stories",[]);label="MORNING" if RUN_SLOT=="morning" else "AFTERNOON";msgs=[]
    for i,s in enumerate(stories,1):
        text=f"🧠 <b>DAILY NEWS + KNOWLEDGE BRIEF — {label} {i}/{len(stories)}</b>\n{today}\n\n<b>{s.get('headline','')}</b> — {s.get('importance',0)}/100\n\n<b>What:</b> {s.get('what','')}\n<b>Who:</b> {s.get('who','')}\n<b>When:</b> {s.get('when','')}\n<b>Where:</b> {s.get('where','')}\n<b>Why:</b> {s.get('why','')}\n<b>Why important:</b> {s.get('why_important','')}\n<b>Latest:</b> {s.get('latest_update','')}\n<b>Change:</b> {s.get('change_since_yesterday','')}\n"
        for k,label2 in (("background","Background"),("perspective","Perspective"),("next","Next"),("entities","Entities")):
            if s.get(k):text+=f"<b>{label2}:</b> {s[k]}\n"
        if s.get("timeline"):
            past=[x.get("title") or x.get("headline") or x.get("event","") for x in s["timeline"][:3] if x.get("title") or x.get("headline") or x.get("event")];text+=("<b>Past:</b> "+" | ".join(past)+"\n") if past else ""
        if s.get("sources"):text+="\n🔗 "+" | ".join(s["sources"][:3])
        msgs.append(text)
    msgs.append(f"📊 <b>{label} RUN STATUS</b>\nArticles scanned: {stats['articles']}\nDuplicate/same-topic stories rejected: {stats['duplicates']}\nStories delivered: {stats['stories']}\nResearch verified: {stats['research_ok']}/{stats['research_total']}\nNew current-affairs entries: {stats['current_affairs']}\nNew vocabulary: {stats['vocabulary']}\nRuntime: {stats['runtime']}\nStatus: {'✅ SUCCESS' if stats['stories']==12 else '⚠️ PARTIAL — fewer than 12 quality stories available'}")
    return msgs
def _vocab_words(story):
    text=f"{story.get('what','')} {story.get('why','')} {story.get('background','')}";words=re.findall(r"\b[A-Za-z]{7,}\b",text);return list(dict.fromkeys(w.lower() for w in words if w.lower() not in STOP))[:3]
def persist(result,today):
    stories=result.get("top_stories",[]);history=read_rows(DATA/"news_history.csv");existing={r.get("story_id") for r in history};cards=read_rows(DATA/"knowledge_cards.csv");cardmap={r.get("topic_id"):r for r in cards};timeline=read_rows(DATA/"story_timeline.csv");timeline_keys={(r.get("story_id"),r.get("date")) for r in timeline};affairs=read_rows(DATA/"current_affairs.csv");affair_keys={(r.get("topic"),r.get("date")) for r in affairs};quizzes=read_rows(DATA/"quiz_history.csv");quiz_keys={r.get("question") for r in quizzes};vocab=read_rows(DATA/"vocabulary.csv");vocab_keys={r.get("word","").lower() for r in vocab};ca_new=v_new=0
    for s in stories:
        sid=s.get("story_id");url=(s.get("sources") or [""])[0];headline=s.get("headline","");tid=topic_id(headline);old=cardmap.get(tid);first=old.get("first_seen",today) if old else today;count=int(old.get("review_count",0) or 0) if old else 0
        if sid and sid not in existing:append_rows(DATA/"news_history.csv",[{"date":today,"story_id":sid,"headline":headline,"source":"","url":url,"category":s.get("category"),"importance":s.get("importance",0)}],HEADERS["news_history.csv"]);existing.add(sid)
        if (sid,today) not in timeline_keys:append_rows(DATA/"story_timeline.csv",[{"story_id":sid,"date":today,"headline":headline,"event":s.get("latest_update",s.get("what","")),"importance":s.get("importance",0),"source":"","url":url}],HEADERS["story_timeline.csv"]);timeline_keys.add((sid,today))
        if (headline,today) not in affair_keys:append_rows(DATA/"current_affairs.csv",[{"date":today,"topic":headline,"category":s.get("category",""),"summary":s.get("what",s.get("latest_update","")),"why_important":s.get("why_important",""),"source_url":url}],HEADERS["current_affairs.csv"]);affair_keys.add((headline,today));ca_new+=1
        append_rows(DATA/"knowledge_cards.csv",[{"topic_id":tid,"topic":headline,"category":s.get("category",""),"explanation":s.get("learn",s.get("what","")),"related_topics":"","first_seen":first,"last_reviewed":today,"review_count":count+1}],HEADERS["knowledge_cards.csv"])
        q=f"Why is this news important: {headline}?";answer=s.get("why_important","") or s.get("what","")
        if q not in quiz_keys:append_rows(DATA/"quiz_history.csv",[{"date":today,"question":q,"answer":answer,"topic":headline,"difficulty":"easy"}],HEADERS["quiz_history.csv"]);quiz_keys.add(q)
        for word in _vocab_words(s):
            if word not in vocab_keys:append_rows(DATA/"vocabulary.csv",[{"word":word,"meaning":f"Used in the context of: {headline}","simple_meaning":s.get("learn",s.get("what",""))[:300],"hindi":"","example":s.get("what","")[:300],"first_seen":today,"review_count":0,"next_review":today}],HEADERS["vocabulary.csv"]);vocab_keys.add(word);v_new+=1
    return ca_new,v_new
def main():
    started=time.monotonic();print("="*60);print(f"🧠 NEWS KNOWLEDGE BOT — {RUN_SLOT.upper()} RUN");print("="*60);log("AI provider","INFO",f"Local Ollama; model={configured_model()}");tg=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID);ensure_data(DATA);cfg=load_sources();limits=cfg.get("limits",{});articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",500));log("News collection","PASS" if articles else "FAIL",f"Collected {len(articles)} articles");today=datetime.now(IST).date().isoformat();previous=history_snapshot();daily_learning();today_history=previous.get("news_history",[]);delivered_today=[r.get("headline","") for r in today_history if str(r.get("date",""))==today];all_articles=[a.__dict__ for a in articles];selected=select_stories(all_articles,top_n=12,excluded_headlines=delivered_today);selected=yesterday_changes(selected,today_history,today);duplicates=max(0,len(all_articles)-len(selected));log("Story selection","PASS" if len(selected)==12 else "WARN",f"Selected {len(selected)}/12; excluded {duplicates} same-topic/already-used candidates");historical=research_stories(selected,today_history);research_stats=historical.pop("_stats",{"ok":0,"memory_ok":0,"failed":len(selected),"total":len(selected),"status":"FAIL"});result=generate_briefing(selected,all_articles,previous,today,historical);result["research_stats"]=research_stats;ca,vocab=persist(result,today);runtime=f"{time.monotonic()-started:.1f}s";stats={'articles':len(articles),'duplicates':duplicates,'stories':len(result.get('top_stories',[])),'research_ok':research_stats.get('ok',0),'research_total':research_stats.get('total',len(selected)),'current_affairs':ca,'vocabulary':vocab,'runtime':runtime};log("Knowledge persistence","PASS",f"Current affairs +{ca}; vocabulary +{vocab}")
    if tg:
        for message in build_messages(result,today,stats):send_text(message)
        log("Telegram delivery","PASS",f"Sent {len(result.get('top_stories',[]))} individual story messages + 1 run-status message")
    log("FINAL","PASS",f"{RUN_SLOT.title()} run completed in {runtime}")
if __name__=="__main__":main()
