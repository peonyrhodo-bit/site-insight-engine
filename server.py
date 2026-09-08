import os, json, sqlite3, math
from pathlib import Path
from datetime import datetime, timezone
import aiofiles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

app = FastAPI(title='AI Full-Cycle YouTube System')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
MCP_URL = os.environ.get('MCP_URL','https://youtube-mcp-u39z.onrender.com/mcp')
FREE_MODE = os.environ.get('FREE_MODE','true').lower() == 'true'
AUTONOMOUS = os.environ.get('AUTONOMOUS','false').lower() == 'true'
DATA_DIR = Path(__file__).parent/'data'; DATA_DIR.mkdir(parents=True,exist_ok=True); DB_PATH=DATA_DIR/'youtube.db'

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def db(): c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS videos(video_id TEXT PRIMARY KEY,channel_id TEXT,title TEXT,channel_title TEXT,published_at TEXT,language TEXT,first_seen_at TEXT);
    CREATE TABLE IF NOT EXISTS video_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,video_id TEXT NOT NULL,observed_at TEXT NOT NULL,views INTEGER,likes INTEGER,comments INTEGER,age_hours REAL,views_per_hour REAL);
    CREATE INDEX IF NOT EXISTS idx_snap_video ON video_snapshots(video_id);
    CREATE INDEX IF NOT EXISTS idx_snap_time ON video_snapshots(observed_at);
    CREATE TABLE IF NOT EXISTS director_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,language TEXT,region_code TEXT,mode TEXT,status TEXT,hypothesis TEXT,reasoning TEXT,data_json TEXT);
    CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,run_id INTEGER,decision_type TEXT,status TEXT,user_note TEXT);
    CREATE TABLE IF NOT EXISTS system_events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,event_type TEXT,message TEXT,data_json TEXT);
    '''); c.commit(); c.close()
init_db()

async def mcp_call(name,args):
    async with streamablehttp_client(MCP_URL) as (r,w,_):
        async with ClientSession(r,w) as s:
            await s.initialize(); result=await s.call_tool(name,args)
            if not result.content: raise RuntimeError('MCP вернул пустой ответ')
            text=getattr(result.content[0],'text',None)
            if text is None: raise RuntimeError('MCP вернул не текст')
            return json.loads(text)

def event(kind,msg,data=None):
    c=db(); c.execute('INSERT INTO system_events(created_at,event_type,message,data_json) VALUES(?,?,?,?)',(now(),kind,msg,json.dumps(data or {},ensure_ascii=False))); c.commit(); c.close()

def save_snapshot(videos,language):
    t=now(); c=db(); n=0
    for v in videos:
        vid=v.get('video_id')
        if not vid: continue
        c.execute('INSERT OR IGNORE INTO videos VALUES(?,?,?,?,?,?,?)',(vid,v.get('channel_id'),v.get('title'),v.get('channel_title'),v.get('published_at'),language,t))
        c.execute('INSERT INTO video_snapshots(video_id,observed_at,views,likes,comments,age_hours,views_per_hour) VALUES(?,?,?,?,?,?,?)',(vid,t,int(v.get('views') or 0),int(v.get('likes') or 0),int(v.get('comments') or 0),v.get('age_hours'),v.get('views_per_hour'))); n+=1
    c.commit(); c.close(); return {'saved_count':n,'observed_at':t}

def score(v):
    views=float(v.get('views') or 0); speed=float(v.get('views_per_hour') or 0); likes=float(v.get('likes') or 0); comments=float(v.get('comments') or 0)
    eng=((likes+comments*3)/views) if views else 0
    return math.log1p(speed)*.65+math.log1p(views)*.15+min(eng*1000,20)*.20

def make_hypothesis(videos,lang,region):
    ranked=sorted(videos,key=score,reverse=True)[:10]
    if not ranked: return {'hypothesis':'Недостаточно данных для гипотезы.','reasoning':'Радар не вернул подходящих видео.','top_videos':[]}
    names=[v.get('title','') for v in ranked[:5]]
    return {'hypothesis':f'В сегменте {lang} стоит проверить темы и форматы, представленные наиболее быстрорастущими видео.','reasoning':f'Проанализировано {len(videos)} видео. Ранжирование учитывает скорость просмотров, общий объём просмотров и относительную вовлечённость. Это гипотеза для эксперимента, а не прогноз успеха. Регион: {region}. Сильнейшие сигналы: ' + '; '.join(names),'top_videos':[dict(v, director_score=round(score(v),4)) for v in ranked]}

@app.get('/')
async def home():
    async with aiofiles.open(Path(__file__).parent/'index.html','r',encoding='utf-8') as f: return HTMLResponse(await f.read())
@app.get('/health')
def health(): return {'status':'ok','free_mode':FREE_MODE,'autonomous':AUTONOMOUS,'mcp_url':MCP_URL}
@app.get('/system/status')
def status(): return {'system':'AI Full-Cycle YouTube System','phase':'free-working-model','free_mode':FREE_MODE,'autonomous':AUTONOMOUS,'wallet_balance':0,'paid_tools_enabled':False,'website_code_modification_by_ai':False,'youtube_channel_deletion_by_ai':False,'published_video_deletion_by_ai':False}
@app.get('/search-channels')
async def search_channels(query:str,max_results:int=20):
    try:return await mcp_call('search_channels',{'query':query,'max_results':max_results})
    except Exception as e:return JSONResponse({'error':str(e)},500)
@app.get('/search-videos')
async def search_videos(query:str,max_results:int=20,published_after:str|None=None,published_before:str|None=None,region_code:str|None=None,relevance_language:str|None=None,order:str='viewCount'):
    try:return await mcp_call('search_videos',{'query':query,'max_results':max_results,'published_after':published_after,'published_before':published_before,'region_code':region_code,'relevance_language':relevance_language,'order':order})
    except Exception as e:return JSONResponse({'error':str(e)},500)
@app.get('/trending-videos')
async def trending_videos(max_results:int=50,region_code:str='US'):
    try:return await mcp_call('search_trending_videos',{'max_results':max_results,'region_code':region_code})
    except Exception as e:return JSONResponse({'error':str(e)},500)
@app.get('/radar-videos')
async def radar_videos(max_results:int=50,language:str='ru',hours_back:int=72):
    try:return await mcp_call('search_radar_videos',{'max_results':min(max_results,50),'language':language,'hours_back':min(max(hours_back,1),168)})
    except Exception as e:return JSONResponse({'error':str(e)},500)
@app.post('/radar-save')
async def radar_save(payload:dict):
    videos=payload.get('videos',[])
    if not videos:return JSONResponse({'error':'Нет видео для сохранения'},400)
    r=save_snapshot(videos,payload.get('language','unknown')); event('radar_saved','Сохранено наблюдение радара',r); return {'status':'ok',**r}
@app.get('/radar-history')
def radar_history(limit:int=100):
    c=db(); rows=c.execute('SELECT v.video_id,v.title,v.channel_title,v.published_at,v.language,s.observed_at,s.views,s.likes,s.comments,s.age_hours,s.views_per_hour FROM video_snapshots s JOIN videos v ON v.video_id=s.video_id ORDER BY s.observed_at DESC LIMIT ?',(min(max(limit,1),500),)).fetchall(); c.close(); return {'count':len(rows),'snapshots':[dict(x) for x in rows]}
@app.get('/database-status')
def database_status():
    c=db(); out={'status':'ok','database':str(DB_PATH),'videos':c.execute('SELECT COUNT(*) FROM videos').fetchone()[0],'snapshots':c.execute('SELECT COUNT(*) FROM video_snapshots').fetchone()[0],'director_runs':c.execute('SELECT COUNT(*) FROM director_runs').fetchone()[0]}; c.close(); return out
@app.get('/analyze')
async def analyze(channel_id:str):
    try:return await mcp_call('get_channel_stats',{'channel_id':channel_id})
    except Exception as e:return JSONResponse({'error':str(e)},500)
@app.post('/director/run')
async def director_run(language:str='ru',region_code:str='RU',hours_back:int=72,max_results:int=50):
    try:
        radar=await mcp_call('search_radar_videos',{'max_results':min(max_results,50),'language':language,'hours_back':min(max(hours_back,1),168)})
        videos=radar.get('videos',[]); save_snapshot(videos,language)
        trends=await mcp_call('search_trending_videos',{'max_results':25,'region_code':region_code})
        h=make_hypothesis(videos,language,region_code); c=db(); cur=c.execute('INSERT INTO director_runs(created_at,language,region_code,mode,status,hypothesis,reasoning,data_json) VALUES(?,?,?,?,?,?,?,?)',(now(),language,region_code,'FREE_ONLY','completed',h['hypothesis'],h['reasoning'],json.dumps({'radar_count':len(videos),'trends_count':len(trends.get('videos',[])),'top_videos':h['top_videos']},ensure_ascii=False))); run_id=cur.lastrowid; c.commit(); c.close(); event('director_run','AI Director завершил аналитический цикл',{'run_id':run_id})
        return {'status':'completed','run_id':run_id,'mode':'FREE_ONLY','hypothesis':h['hypothesis'],'reasoning':h['reasoning'],'top_videos':h['top_videos'],'trends':trends.get('videos',[])[:10],'next_action':'Ожидается решение пользователя' if not AUTONOMOUS else 'Сформировать контент по гипотезе'}
    except Exception as e: event('director_error',str(e)); return JSONResponse({'status':'error','error':str(e)},500)
@app.get('/director/history')
def director_history(limit:int=20):
    c=db(); rows=c.execute('SELECT id,created_at,language,region_code,mode,status,hypothesis,reasoning FROM director_runs ORDER BY id DESC LIMIT ?',(min(max(limit,1),100),)).fetchall(); c.close(); return {'count':len(rows),'runs':[dict(x) for x in rows]}
@app.post('/director/decision')
def director_decision(payload:dict):
    decision=payload.get('decision');
    if decision not in {'approve','discuss','leave_as_is'}: return JSONResponse({'error':'Недопустимое решение'},400)
    c=db(); c.execute('INSERT INTO decisions(created_at,run_id,decision_type,status,user_note) VALUES(?,?,?,?,?)',(now(),payload.get('run_id'),decision,'accepted',payload.get('note'))); c.commit(); c.close(); event('decision','Пользователь принял решение',{'run_id':payload.get('run_id'),'decision':decision}); return {'status':'ok','run_id':payload.get('run_id'),'decision':decision}
@app.get('/events')
def events(limit:int=50):
    c=db(); rows=c.execute('SELECT id,created_at,event_type,message,data_json FROM system_events ORDER BY id DESC LIMIT ?',(min(max(limit,1),200),)).fetchall(); c.close(); return {'events':[dict(x) for x in rows]}
if __name__=='__main__':
    import uvicorn; uvicorn.run(app,host='0.0.0.0',port=int(os.environ.get('PORT','10000')))
