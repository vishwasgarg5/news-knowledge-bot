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
from .storage import HEADERS,append_rows,ensure_data,read_rows,replace_rows
from .telegram import send_text
IST=ZoneInfo("Asia/Kolkata"); RUN_SLOT=os.environ.get("RUN_SLOT","morning").lower()
STOP=set("about after before their there which where while would could should today latest india from that this with have been will into than they were said over amid also more news says government development according following between including international situation background provided sources".split())
def log(stage,status,message): print(f"[{status}] {stage}: {message}",flush=True)
def load_sources():
    with CONFIG.open(encoding="utf-8") as f:return yaml.safe_load(f)
def history_snapshot():return {name[:-4]:read_rows(DATA/name)[-1500:] for name in HEADERS}
def _tokens(text):return set(w for w in re.findall(r"[a-z]{4,}",str(text).lower()) if w not in STOP)
def _sim(a,b):
    x,y=_tokens(a),_tokens(b);return len(x&y)/max(1,len(x|y))
def topic_id(headline):
    words=[w for w in re.findall(r"[A-Za-z]{4,}",str(headline).lower()) if w not in STOP];return hashlib.sha1((" ".join(words[:12]) or str(headline).lower()).encode()).hexdigest()[:16]
def yesterday_changes(stories,history,today):
    yesterday=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat();prev=[r.get("headline","") for r in history if str(r.get("date",""))==yesterday]
    for s in stories:s["change_since_yesterday"]= "Continuing story" if any(_sim(s.get("headline",""),h)>=.48 for h in prev) else "New topic today"
    return stories
def build_messages(result,today,stats):
    stories=result.get("top_stories",[]);label="MORNING" if RUN_SLOT=="morning" else "AFTERNOON";msgs=[]
    india=sum(1 for s in stories if s.get("region")=="india"); world=sum(1 for s in stories if s.get("region")=="world")
    for i,s in enumerate(stories,1):
        region="🇮🇳 INDIA" if s.get("region")=="india" else "🌍 WORLD"
        text=f"🧠 <b>{region} — {label} {i}/{len(stories)}</b>\n{today}\n\n<b>{s.get('headline','')}</b> — {s.get('importance',0)}/100\n\n<b>🔴 EVENT:</b> {s.get('what','')}\n<b>👤 WHO:</b> {s.get('who','')}\n<b>📅 WHEN:</b> {s.get('when','')}\n<b>📍 WHERE:</b> {s.get('where','')}\n\n<b>❓ WHY:</b> {s.get('why','')}\n<b>💡 IMPACT:</b> {s.get('why_important','')}\n<b>🔄 CHANGE:</b> {s.get('change_since_yesterday','')}\n<b>🔮 NEXT:</b> {s.get('next','')}\n\n<b>🔗 CONNECTION:</b> {s.get('connection','')}\n<b>🧠 REMEMBER:</b> {s.get('memory_hook','')}\n<b>📚 LEARN:</b> {s.get('learn','')}\n<b>👥 ENTITIES:</b> {s.get('entities','')}\n<b>📖 VOCAB:</b> {s.get('vocabulary','')}\n"
        if s.get("background"):text+=f"<b>Background:</b> {s['background']}\n"
        ver=s.get("verification") or {};text+=f"\n<b>🔎 Verification:</b> {ver.get('verification','not checked')} | Confidence: {ver.get('confidence','n/a')}% | Sources: {ver.get('source_count',0)}\n"
        if s.get("sources"):text+="🔗 "+" | ".join(s["sources"][:3])
        msgs.append(text)
    msgs.append(f"📊 <b>{label} RUN STATUS</b>\n🇮🇳 India stories: {india}\n🌍 World stories: {world}\nArticles scanned: {stats['articles']}\nRejected duplicates: {stats['duplicates']}\nStories delivered: {stats['stories']}\nMulti/single-source verified: {stats['research_ok']}/{stats['research_total']}\nNew current-affairs entries: {stats['current_affairs']}\nNew vocabulary: {stats['vocabulary']}\nKnowledge connections: {stats['connections']}\nRuntime: {stats['runtime']}\nStatus: {'✅ SUCCESS' if stats['stories']==12 and india>=5 and world>=5 else '⚠️ PARTIAL — source balance/quality limited'}")
    return msgs

def _vocab_words(story):
    text=f"{story.get('what','')} {story.get('why','')} {story.get('background','')}";words=re.findall(r"\b[A-Za-z]{7,}\b",text);return list(dict.fromkeys(w.lower() for w in words if w.lower() not in STOP))[:2]
def _upsert(path,rows,key,fields):
    existing=read_rows(path);by={str(r.get(key,"")):r for r in existing}
    for r in rows:by[str(r.get(key,""))]=r
    replace_rows(path,list(by.values()),fields)
def persist(result,today):
    stories=result.get("top_stories",[]);history=read_rows(DATA/"news_history.csv");existing={r.get("story_id") for r in history};timeline=read_rows(DATA/"story_timeline.csv");timeline_keys={(r.get("story_id"),r.get("date")) for r in timeline};affairs=read_rows(DATA/"current_affairs.csv");affair_keys={(r.get("topic"),r.get("date")) for r in affairs};quizzes=read_rows(DATA/"quiz_history.csv");quiz_keys={r.get("question") for r in quizzes};vocab=read_rows(DATA/"vocabulary.csv");vocab_keys={r.get("word","").lower() for r in vocab};progress=read_rows(DATA/"learning_progress.csv");pmap={r.get("topic_id"):r for r in progress};graph=read_rows(DATA/"knowledge_graph.csv");graph_keys={(r.get("source_topic"),r.get("relation"),r.get("target_topic")) for r in graph};ca_new=v_new=connections=0
    for s in stories:
        sid=s.get("story_id");url=(s.get("sources") or [s.get("url","")])[0];headline=s.get("headline","");tid=topic_id(headline);region=s.get("region","world")
        if sid and sid not in existing:append_rows(DATA/"news_history.csv",[{"date":today,"story_id":sid,"headline":headline,"source":"","url":url,"category":s.get("category"),"importance":s.get("importance",0),"region":region,"verification":(s.get("verification") or {}).get("verification",""),"confidence":(s.get("verification") or {}).get("confidence","")}],HEADERS["news_history.csv"]);existing.add(sid)
        if (sid,today) not in timeline_keys:append_rows(DATA/"story_timeline.csv",[{"story_id":sid,"date":today,"headline":headline,"event":s.get("latest_update",s.get("what","")),"importance":s.get("importance",0),"source":"","url":url,"change_type":s.get("change_since_yesterday","")}],HEADERS["story_timeline.csv"]);timeline_keys.add((sid,today))
        if (headline,today) not in affair_keys:append_rows(DATA/"current_affairs.csv",[{"date":today,"topic":headline,"category":s.get("category",""),"summary":s.get("what",s.get("latest_update","")),"why_important":s.get("why_important",""),"source_url":url,"region":region,"memory_hook":s.get("memory_hook","")}],HEADERS["current_affairs.csv"]);affair_keys.add((headline,today));ca_new+=1
        old=pmap.get(tid,{});pmap[tid]={"topic_id":tid,"topic":headline,"region":region,"first_seen":old.get("first_seen",today),"last_seen":today,"exposure_count":int(old.get("exposure_count",0) or 0)+1,"review_count":int(old.get("review_count",0) or 0),"next_review":today,"mastery":old.get("mastery","0"),"priority":"high" if float(s.get("importance",0))>=80 else "normal"}
        q=f"Why is this news important: {headline}?";answer=s.get("why_important","") or s.get("what","")
        if q not in quiz_keys:append_rows(DATA/"quiz_history.csv",[{"date":today,"question":q,"answer":answer,"topic":headline,"difficulty":"easy","region":region,"review_due":today}],HEADERS["quiz_history.csv"]);quiz_keys.add(q)
        for word in _vocab_words(s):
            if word not in vocab_keys:append_rows(DATA/"vocabulary.csv",[{"word":word,"meaning":"","simple_meaning":"","hindi":"","example":s.get("what","")[:250],"first_seen":today,"review_count":0,"next_review":today,"last_seen":today,"mastery":0}],HEADERS["vocabulary.csv"]);vocab_keys.add(word);v_new+=1
        for relation,target in (("causes",s.get("why","")),("impacts",s.get("why_important","")),("connects",s.get("connection",""))):
            if target and (headline,relation,target) not in graph_keys:append_rows(DATA/"knowledge_graph.csv",[{"date":today,"source_topic":headline,"relation":relation,"target_topic":target[:300],"region":region,"confidence":(s.get("verification") or {}).get("confidence",50)}],HEADERS["knowledge_graph.csv"]);graph_keys.add((headline,relation,target));connections+=1
    replace_rows(DATA/"learning_progress.csv",list(pmap.values()),HEADERS["learning_progress.csv"])
    return ca_new,v_new,connections
def main():
    started=time.monotonic();print("="*60);print(f"🧠 STAGE 5 NEWS KNOWLEDGE ENGINE — {RUN_SLOT.upper()}");print("="*60);log("AI provider","INFO",f"Local Ollama; model={configured_model()}");tg=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID);ensure_data(DATA);cfg=load_sources();limits=cfg.get("limits",{});articles=collect(cfg.get("sources",{}),limits.get("max_articles_per_source",30),limits.get("max_total_articles",700));log("News collection","PASS" if articles else "FAIL",f"Collected {len(articles)} articles");today=datetime.now(IST).date().isoformat();previous=history_snapshot();daily_learning();today_history=previous.get("news_history",[]);delivered_today=[r.get("headline","") for r in today_history if str(r.get("date",""))==today];all_articles=[a.__dict__ for a in articles];selected=select_stories(all_articles,top_n=12,excluded_headlines=delivered_today);selected=yesterday_changes(selected,today_history,today);duplicates=max(0,len(all_articles)-len(selected));log("Balanced selection","PASS" if len(selected)==12 else "WARN",f"Selected {len(selected)}/12 with India/World balance");historical=research_stories(selected,today_history,all_articles);research_stats=historical.pop("_stats",{"ok":0,"failed":len(selected),"total":len(selected)});result=generate_briefing(selected,all_articles,previous,today,historical);result["research_stats"]=research_stats
    byid=historical
    for s in result.get("top_stories",[]):
        s["verification"]=byid.get(s.get("story_id"),{});s["sources"]= [s.get("url","")]+[x.get("url","") for x in s["verification"].get("evidence",[]) if x.get("url")]
    ca,vocab,connections=persist(result,today);runtime=f"{time.monotonic()-started:.1f}s";stats={'articles':len(articles),'duplicates':duplicates,'stories':len(result.get('top_stories',[])),'research_ok':research_stats.get('ok',0),'research_total':research_stats.get('total',len(selected)),'current_affairs':ca,'vocabulary':vocab,'connections':connections,'runtime':runtime};log("Knowledge persistence","PASS",f"Current affairs +{ca}; vocabulary +{vocab}; graph +{connections}")
    if tg:
        for message in build_messages(result,today,stats):send_text(message)
        log("Telegram delivery","PASS",f"Sent {len(result.get('top_stories',[]))} story messages + status")
    log("FINAL","PASS",f"Stage 5 run completed in {runtime}")
if __name__=="__main__":main()
