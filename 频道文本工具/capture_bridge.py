"""Streaming browser capture with durable receipts, compressed evidence and bounded workers."""
from __future__ import annotations
import base64
import hashlib
import io
import json
import queue
import re
import secrets
import shutil
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from PIL import Image
from media_store import compress_image, store_image
from save_images import NoRedirect, allowed

AVATAR_HOSTS = {'qqchannel-profile-1251316161.file.myqcloud.com','thirdqq.qlogo.cn','q1.qlogo.cn','q2.qlogo.cn'}


def valid_avatar(url):
    try:
        p=urlsplit(url)
        return p.scheme=='https' and p.hostname in AVATAR_HOSTS and p.port in (None,443)
    except (ValueError,TypeError): return False


def intervals(values):
    merged=[]
    for lo,hi in sorted(values):
        if hi<=lo:continue
        if merged and lo<=merged[-1][1]+2:merged[-1][1]=max(hi,merged[-1][1])
        else:merged.append([lo,hi])
    return merged


class CaptureBridge:
    def __init__(self,library,write_connection=True,start_workers=True,base_url='http://127.0.0.1:8765'):
        self.library=library
        self.root=library.root
        for name in ('截图','头像','采集日志','运行日志'): (self.root/name).mkdir(exist_ok=True)
        key_file=self.root/'索引/采集连接.json'
        if key_file.exists():self.connection=json.loads(key_file.read_text(encoding='utf-8'))
        else:
            self.connection={'base_url':'http://127.0.0.1:8765','token':secrets.token_urlsafe(32)}
            key_file.write_text(json.dumps(self.connection),encoding='utf-8')
        if self.connection['base_url'] != base_url:
            self.connection['base_url'] = base_url
            key_file.write_text(json.dumps(self.connection), encoding='utf-8')
        if write_connection:
            local_file=Path(__file__).parent/'浏览器手动采集/local_connection.json'
            local_file.write_text(json.dumps(self.connection),encoding='utf-8')
        self.write_lock=threading.RLock()
        self.tasks=queue.Queue(maxsize=3000)
        self.pending=set();self.pending_lock=threading.Lock()
        self.budget=1_200_000_000;self.reserve=1_500_000_000
        with closing(library.connect()) as con,con:
            con.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS capture_runs(run_id TEXT PRIMARY KEY,started_at TEXT,updated_at TEXT,config_json TEXT,state_json TEXT);
            CREATE TABLE IF NOT EXISTS stream_receipts(receipt TEXT PRIMARY KEY,run_id TEXT,result_json TEXT);
            CREATE TABLE IF NOT EXISTS run_posts(run_id TEXT,post_id TEXT,PRIMARY KEY(run_id,post_id));
            CREATE TABLE IF NOT EXISTS avatars(url_hash TEXT PRIMARY KEY,url TEXT,relative_path TEXT,bytes INTEGER,status TEXT);
            CREATE TABLE IF NOT EXISTS screenshots(capture_id TEXT PRIMARY KEY,post_id TEXT,scope TEXT,relative_path TEXT,bytes INTEGER,info_json TEXT,updated_at TEXT);
            CREATE INDEX IF NOT EXISTS screenshots_post ON screenshots(post_id);
            ''')
        if start_workers:
            for _ in range(2):threading.Thread(target=self.media_worker,daemon=True).start()

    def authorized(self,headers):
        return secrets.compare_digest(headers.get('Authorization',''),'Bearer '+self.connection['token'])

    def used_bytes(self):
        with closing(self.library.connect()) as con:
            photos=con.execute("SELECT coalesce(sum(n),0) FROM (SELECT max(bytes) n FROM media WHERE status='已保存' GROUP BY relative_path)").fetchone()[0]
            extras=sum(con.execute(f'SELECT coalesce(sum(bytes),0) FROM {table}').fetchone()[0] for table in ('screenshots','avatars'))
        return photos+extras

    def capacity(self,extra=350_000):
        return self.used_bytes()+extra<=self.budget and shutil.disk_usage(self.root).free>=self.reserve+extra

    def status(self):
        with closing(self.library.connect()) as con:
            run=con.execute('SELECT * FROM capture_runs ORDER BY started_at DESC LIMIT 1').fetchone()
            shots=con.execute('SELECT count(*) FROM screenshots').fetchone()[0]
            avatars=con.execute("SELECT count(*) FROM avatars WHERE status='已保存'").fetchone()[0]
            formal=con.execute("SELECT count(*) FROM posts WHERE stage='正式'").fetchone()[0]
        return {'run':dict(run) if run else None,'screenshots':shots,'saved_avatars':avatars,
                'formal_posts':formal,'target':10000,'used_evidence_bytes':self.used_bytes(),
                'budget_bytes':self.budget,'reserve_bytes':self.reserve,'queued_images':self.tasks.qsize()}

    def start(self,config):
        from research_library import now
        run_id=now().replace(':','-').replace('+','_')+'_'+secrets.token_hex(3)
        with closing(self.library.connect()) as con,con:
            con.execute('INSERT INTO capture_runs VALUES(?,?,?,?,?)',(run_id,now(),now(),json.dumps(config,ensure_ascii=False),json.dumps({'running':True,'message':'已连接浏览器，等待页面记录'},ensure_ascii=False)))
        return {'run_id':run_id,'index':self.index(),'status':self.status()}

    def index(self):
        with closing(self.library.connect()) as con:
            shots={row[0] for row in con.execute("SELECT post_id FROM screenshots WHERE scope='list' AND json_extract(info_json,'$.coverage')>=0.98")}
            data={}
            for row in con.execute('SELECT id,data_json FROM posts'):
                post=json.loads(row['data_json']);data[row['id']]={'detail':post.get('preview_only') is False,'shot':row['id'] in shots}
        return data

    def update(self,run_id,state):
        from research_library import now
        with closing(self.library.connect()) as con,con:
            old=con.execute('SELECT state_json FROM capture_runs WHERE run_id=?',(run_id,)).fetchone()
            stop=bool(old and json.loads(old[0]).get('stop_requested'))
            if stop:state['stop_requested']=True
            con.execute('UPDATE capture_runs SET updated_at=?,state_json=? WHERE run_id=?',(now(),json.dumps(state,ensure_ascii=False),run_id))
        if not state.get('running',False):self.library.write_index()
        return {'ok':True,'stop_requested':stop}

    def stop(self):
        with closing(self.library.connect()) as con,con:
            row=con.execute('SELECT run_id,state_json FROM capture_runs ORDER BY started_at DESC LIMIT 1').fetchone()
            if row:
                state=json.loads(row['state_json']);state['stop_requested']=True
                con.execute('UPDATE capture_runs SET state_json=? WHERE run_id=?',(json.dumps(state,ensure_ascii=False),row['run_id']))
        return {'ok':True}

    def enqueue(self,kind,url):
        if not ((kind=='avatar' and valid_avatar(url)) or (kind=='photo' and allowed(url))):return
        key=(kind,url)
        with self.pending_lock:
            if key in self.pending:return
            self.pending.add(key)
        try:self.tasks.put_nowait(key)
        except queue.Full:
            with self.pending_lock:self.pending.discard(key)

    def resume_media(self):
        with closing(self.library.connect()) as con:
            photos=[row[0] for row in con.execute("SELECT url FROM media WHERE status IN ('待保存','请求失败') LIMIT 2000")]
            avatars=[row[0] for row in con.execute("SELECT url FROM avatars WHERE status IN ('待保存','请求失败') LIMIT 500")]
        for kind,urls in (('photo',photos),('avatar',avatars)):
            for url in urls:self.enqueue(kind,url)
        return {'ok':True,'queued':self.tasks.qsize(),'message':'已将待保存图像加入本机队列。'}

    def ingest(self,data):
        from research_library import clean_post,merge_post,now
        run_id=str(data.get('run_id',''));posts=data.get('posts',[])
        if not isinstance(posts,list) or len(posts)>150:raise ValueError('单次记录上限150帖。')
        receipt=hashlib.sha256(json.dumps([run_id,data.get('sequence'),posts],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        added=updated=skipped=0;kept=[]
        with self.write_lock,closing(self.library.connect()) as con,con:
            if not con.execute('SELECT 1 FROM capture_runs WHERE run_id=?',(run_id,)).fetchone():raise ValueError('采集任务尚未连接。')
            old_receipt=con.execute('SELECT result_json FROM stream_receipts WHERE receipt=?',(receipt,)).fetchone()
            if old_receipt:return json.loads(old_receipt[0])
            for raw in posts:
                post=clean_post(raw)
                if not post:continue
                self.library.enrich_section(post,con)
                row=con.execute('SELECT data_json FROM posts WHERE id=?',(post['id'],)).fetchone()
                if row:
                    old=json.loads(row['data_json']);combined=merge_post(old,post)
                    substantive=lambda p:{k:v for k,v in p.items() if k not in {'captured_at','comment_count_as_of','page_age_seconds','created_at_estimated','created_at_earliest','created_at_latest','time_observations'}}
                    if substantive(combined)!=substantive(old):
                        con.execute('UPDATE posts SET data_json=?,last_seen=? WHERE id=?',(json.dumps(combined,ensure_ascii=False),now(),post['id']));updated+=1
                    else:skipped+=1
                else:
                    con.execute('INSERT INTO posts VALUES(?,?,?,?,?)',(post['id'],json.dumps(post,ensure_ascii=False),post.get('captured_at') or now(),now(),'正式'));added+=1
                con.execute('INSERT OR IGNORE INTO run_posts VALUES(?,?)',(run_id,post['id']))
                for image in post['images']:
                    url=image['url'];digest=hashlib.sha256(url.encode()).hexdigest()
                    con.execute('INSERT OR IGNORE INTO media VALUES(?,?,?,?,?,?)',(digest,url,None,0,'待保存','{}'))
                    con.execute('INSERT OR IGNORE INTO post_images VALUES(?,?)',(post['id'],digest))
                avatar=post.get('author_avatar_url')
                if avatar and valid_avatar(avatar):
                    digest=hashlib.sha256(avatar.encode()).hexdigest()
                    con.execute('INSERT OR IGNORE INTO avatars VALUES(?,?,?,?,?)',(digest,avatar,None,0,'待保存'))
                kept.append(post)
            result={'added':added,'updated':updated,'skipped':skipped,'accepted_ids':[p['id'] for p in kept]}
            con.execute('INSERT INTO stream_receipts VALUES(?,?,?)',(receipt,run_id,json.dumps(result)))
        if added or updated:
            with (self.root/'采集日志'/(run_id+'.jsonl')).open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'captured_at':now(),'sequence':data.get('sequence'),'posts':kept},ensure_ascii=False)+'\n')
        for post in kept:
            for image in post['images']:self.enqueue('photo',image['url'])
            if post.get('author_avatar_url'):self.enqueue('avatar',post['author_avatar_url'])
        return result

    def media_worker(self):
        opener=build_opener(NoRedirect())
        while True:
            kind,url=self.tasks.get()
            try:
                table='avatars' if kind=='avatar' else 'media';digest=hashlib.sha256(url.encode()).hexdigest()
                with closing(self.library.connect()) as con:
                    row=con.execute(f'SELECT status FROM {table} WHERE url_hash=?',(digest,)).fetchone()
                if row and row[0]=='已保存':continue
                if not self.capacity():continue
                with opener.open(Request(url,headers={'User-Agent':'Mozilla/5.0 (local campus research archive)'}),timeout=12) as response:
                    if not response.headers.get('Content-Type','').startswith('image/'):raise ValueError('image_response_required')
                    payload=response.read(12*1024*1024+1)
                    if len(payload)>12*1024*1024:raise ValueError('image_download_limit')
                folder=self.root/('头像' if kind=='avatar' else '图片')
                with self.write_lock:
                    if not self.capacity():continue
                    info=store_image(payload,folder,20_000 if kind=='avatar' else 350_000,128 if kind=='avatar' else 3200)
                    with closing(self.library.connect()) as con,con:
                        if kind=='avatar':con.execute('UPDATE avatars SET relative_path=?,bytes=?,status=? WHERE url_hash=?',(info['relative_path'],info['bytes'],'已保存',digest))
                        else:con.execute('UPDATE media SET relative_path=?,bytes=?,status=?,info_json=? WHERE url_hash=?',(info['relative_path'],info['bytes'],'已保存',json.dumps(info),digest))
            except Exception:
                with closing(self.library.connect()) as con,con:
                    con.execute(f'UPDATE {"avatars" if kind=="avatar" else "media"} SET status=? WHERE url_hash=?',('请求失败',hashlib.sha256(url.encode()).hexdigest()))
            finally:
                with self.pending_lock:self.pending.discard((kind,url))
                self.tasks.task_done();time.sleep(.3)

    def screenshot(self,data):
        from research_library import now
        if not self.capacity():return {'saved':0,'reason':'图片与截图预算或保留空间达到阈值，文字采集继续'}
        image_data=str(data.get('data_url',''))
        if not image_data.startswith(('data:image/jpeg;base64,','data:image/png;base64,')):raise ValueError('截图格式需要JPEG或PNG。')
        binary=base64.b64decode(image_data.split(',',1)[1],validate=True)
        if len(binary)>6*1024*1024:raise ValueError('单屏截图超出上限。')
        viewport=Image.open(io.BytesIO(binary)).convert('RGB')
        vw=float(data.get('viewport_width',0));vh=float(data.get('viewport_height',0))
        if vw<=0 or vh<=0:raise ValueError('截图视口信息缺失。')
        sx=viewport.width/vw;sy=viewport.height/vh;saved=0
        with self.write_lock,closing(self.library.connect()) as con,con:
            for fragment in data.get('fragments',[])[:12]:
                post_id=str(fragment.get('post_id',''))
                if not re.fullmatch(r'B_[A-Za-z0-9_]{1,150}',post_id):continue
                if not con.execute('SELECT 1 FROM posts WHERE id=?',(post_id,)).fetchone():continue
                x=max(0,float(fragment['x']));y=max(0,float(fragment['y']));width=max(1,min(vw-x,float(fragment['width'])));height=max(1,min(vh-y,float(fragment['height'])))
                offset=max(0,float(fragment.get('offset',0)));total=max(height,float(fragment.get('total_height',height)))
                scope='detail' if fragment.get('scope')=='detail' else 'list'
                capture_id=hashlib.sha256((post_id+'|'+scope).encode()).hexdigest();filename=capture_id+'.jpg';target=self.root/'截图'/filename
                canvas_width=max(1,min(1400,round(width*sx)));canvas_height=max(1,round(total*sy*canvas_width/(width*sx)))
                if canvas_height>8000:canvas_width=max(1,round(canvas_width*8000/canvas_height));canvas_height=8000
                previous=con.execute('SELECT info_json FROM screenshots WHERE capture_id=?',(capture_id,)).fetchone()
                old=json.loads(previous[0]) if previous else {}
                same=abs(old.get('total_height',total)-total)<10 and abs(old.get('css_width',width)-width)<10
                if same and target.exists():
                    with Image.open(target) as im:canvas=im.convert('RGB').resize((canvas_width,canvas_height))
                    ranges=old.get('ranges',[])
                else:canvas=Image.new('RGB',(canvas_width,canvas_height),'white');ranges=[]
                crop=viewport.crop((round(x*sx),round(y*sy),round((x+width)*sx),round((y+height)*sy)))
                part_height=max(1,round(height/total*canvas_height));crop=crop.resize((canvas_width,part_height),Image.Resampling.LANCZOS)
                canvas.paste(crop,(0,round(offset/total*canvas_height)))
                ranges=intervals(ranges+[[offset,min(total,offset+height)]])
                coverage=min(1,sum(b-a for a,b in ranges)/total)
                info={'ranges':ranges,'total_height':total,'css_width':width,'coverage':coverage,'scope':scope,
                      'captured_at':data.get('captured_at') or now(),'method':'headless_rendered_pixels' if data.get('capture_method')=='headless_rendered_pixels' else 'browser_visible_pixels_stitched','contains_author_avatar':True}
                buffer=io.BytesIO();canvas.save(buffer,format='JPEG',quality=90)
                payload,dimensions=compress_image(buffer.getvalue(),300_000,4096);info.update(dimensions)
                temporary=target.with_suffix('.tmp');temporary.write_bytes(payload);temporary.replace(target)
                con.execute('INSERT INTO screenshots VALUES(?,?,?,?,?,?,?) ON CONFLICT(capture_id) DO UPDATE SET relative_path=excluded.relative_path,bytes=excluded.bytes,info_json=excluded.info_json,updated_at=excluded.updated_at',(capture_id,post_id,scope,filename,len(payload),json.dumps(info),now()))
                saved+=1
        return {'saved':saved}

    def evidence(self,post_id):
        with closing(self.library.connect()) as con:
            shots=[dict(row) for row in con.execute('SELECT scope,relative_path,bytes,info_json FROM screenshots WHERE post_id=?',(post_id,))]
            post=con.execute('SELECT data_json FROM posts WHERE id=?',(post_id,)).fetchone()
            avatar=None
            if post:
                url=json.loads(post[0]).get('author_avatar_url')
                if url:
                    row=con.execute('SELECT relative_path,status FROM avatars WHERE url_hash=?',(hashlib.sha256(url.encode()).hexdigest(),)).fetchone()
                    if row:avatar=dict(row)
        return {'screenshots':shots,'avatar':avatar}
