"""Local research library, idempotent imports and a localhost-only analysis workspace."""
from __future__ import annotations
import argparse
import os
import csv
import hashlib
import io
import json
import random
import re
import shutil
import sqlite3
import threading
import time
import webbrowser
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener

from analyze_posts import classify, csv_safe
from save_images import NoRedirect, allowed
from media_store import store_image

TOOL = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(os.environ.get('QIXIANG_DATA_ROOT') or TOOL.parent / '调研资料库').expanduser().resolve()
CATEGORIES = ['学习与课程', '校园办事', '生活服务', '二手与交易', '活动与招募', '休闲与表达', '商业推广', '其他', '待判断']
ANNOTATIONS = ['main_category', 'is_help', 'help_evidence', 'topic', 'source_evidence', 'case_candidate', 'notes', 'reviewer', 'second_category', 'second_reviewer']


def now():
    return datetime.now(timezone.utc).isoformat()


def fnv(value):
    h = 2166136261
    # Match the small browser fingerprint for observed image addresses.
    encoded = value.encode('utf-16-le')
    for offset in range(0, len(encoded), 2):
        h = ((h ^ int.from_bytes(encoded[offset:offset+2], 'little')) * 16777619) & 0xffffffff
    return format(h, 'x')


def clean_post(raw):
    if not isinstance(raw, dict): return None
    post_id = str(raw.get('id') or '')
    if not re.fullmatch(r'B_[A-Za-z0-9_]{1,150}', post_id):
        match = re.search(r'/post/(B_[A-Za-z0-9_]+)', str(raw.get('url') or ''))
        if not match: return None
        post_id = match.group(1)
    fields = ['title', 'text', 'url', 'board', 'created_at', 'displayed_date_label',
              'comment_count', 'comment_count_basis', 'comment_count_as_of',
              'captured_at', 'source_page', 'sampling_entry', 'text_source', 'text_truncated_by_tool',
              'author_avatar_url','created_at_estimated','created_at_earliest','created_at_latest',
              'time_method','time_precision','time_label_raw','page_age_seconds',
              'comments_scope','detail_selection','board_id','board_basis','sampling_frame']
    post = {key: raw.get(key) for key in fields if raw.get(key) is not None}
    native_id=parse_qs(urlsplit(str(post.get('url',''))).query).get('subc',[''])[0]
    if re.fullmatch(r'\d{1,15}',native_id):post['board_id']=native_id
    entry=post.get('sampling_entry')
    if entry:
        post['sampling_entries']=[str(entry)]
        post.setdefault('sampling_frame','primary_all' if entry=='全部' else 'section_supplement' if post.get('board_id') and entry!='热门' else 'other_entry')
    post['id'] = post_id
    post['preview_only'] = raw.get('preview_only', True) is not False
    post['text'] = str(post.get('text') or '')[:20000]
    post['title'] = str(post.get('title') or '')[:1000]
    post['images'] = []
    image_values = raw.get('images') or []
    for image in image_values[:24] if isinstance(image_values, list) else []:
        if isinstance(image, dict) and isinstance(image.get('url'), str) and allowed(image['url']):
            post['images'].append({key: image.get(key) for key in ('url', 'width', 'height')})
    post['visible_comments'] = []
    comments = raw.get('visible_comments') or []
    for comment in comments[:120] if isinstance(comments, list) else []:
        if isinstance(comment, dict) and comment.get('text'):
            post['visible_comments'].append({'text': str(comment['text'])[:1200],
                'displayed_time_label': str(comment.get('displayed_time_label') or '')[:80]})
    post['candidate_labels'] = classify(post['title'], post['text'])[0]
    if post.get('time_method'):
        post['time_observations'] = [{key:post[key] for key in ('captured_at','displayed_date_label','created_at','created_at_estimated','created_at_earliest','created_at_latest','time_method','time_precision','page_age_seconds') if key in post}]
    return post


def merge_post(old, incoming):
    result = dict(old)
    richer = (old.get('preview_only', True) and not incoming.get('preview_only', True)) or (
        old.get('preview_only', True) == incoming.get('preview_only', True) and len(incoming.get('text', '')) > len(old.get('text', '')))
    for key, value in incoming.items():
        if key in ('images', 'visible_comments', 'text', 'preview_only', 'text_source', 'text_truncated_by_tool', 'candidate_labels','sampling_entry','sampling_frame','sampling_entries'): continue
        if value not in (None, ''): result[key] = value
    for key in ('sampling_entry','sampling_frame'):
        if not result.get(key) and incoming.get(key):result[key]=incoming[key]
    entries=old.get('sampling_entries',[old.get('sampling_entry')])+incoming.get('sampling_entries',[incoming.get('sampling_entry')])
    result['sampling_entries']=list(dict.fromkeys(value for value in entries if value))
    # A detail page's date-only label complements the list's minute estimate.
    # Keep both observations and retain the more precise relative estimate.
    if old.get('time_method') == 'relative_estimate' and incoming.get('time_method') == 'displayed_calendar' and len(str(incoming.get('created_at',''))) == 10:
        for key in ('created_at_estimated','created_at_earliest','created_at_latest','time_method','time_precision','time_label_raw','page_age_seconds'):
            if key in old: result[key] = old[key]
    observations=old.get('time_observations',[])+incoming.get('time_observations',[])
    result['time_observations']=list({json.dumps(item,sort_keys=True):item for item in observations}.values())[-6:]
    if richer:
        for key in ('text', 'preview_only', 'text_source', 'text_truncated_by_tool'):
            if key in incoming: result[key] = incoming[key]
    images = {item['url']: item for item in old.get('images', [])}
    images.update({item['url']: item for item in incoming.get('images', [])})
    comments = {item['text']: item for item in old.get('visible_comments', [])}
    comments.update({item['text']: item for item in incoming.get('visible_comments', [])})
    result['images'] = list(images.values())[:24]
    result['visible_comments'] = list(comments.values())[:120]
    result['candidate_labels'] = classify(result.get('title', ''), result.get('text', ''))[0]
    return result


class Library:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        for folder in ('批次', '图片', '分析导出', '索引'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.db = self.root / '资料库.sqlite3'
        with closing(self.connect()) as con, con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, data_json TEXT NOT NULL, first_seen TEXT, last_seen TEXT, stage TEXT);
            CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY, filename TEXT, imported_at TEXT, stage TEXT, source_path TEXT, bytes INTEGER, new_posts INTEGER, enriched INTEGER, skipped INTEGER, input_records INTEGER);
            CREATE TABLE IF NOT EXISTS media(url_hash TEXT PRIMARY KEY,url TEXT,relative_path TEXT,bytes INTEGER,status TEXT,info_json TEXT);
            CREATE TABLE IF NOT EXISTS post_images(post_id TEXT,url_hash TEXT,PRIMARY KEY(post_id,url_hash));
            CREATE TABLE IF NOT EXISTS annotations(post_id TEXT PRIMARY KEY,data_json TEXT,reviewed_at TEXT);
            CREATE INDEX IF NOT EXISTS posts_stage_seen ON posts(stage,first_seen,id);
            CREATE INDEX IF NOT EXISTS post_images_post ON post_images(post_id);
            CREATE TABLE IF NOT EXISTS sections(id TEXT PRIMARY KEY,name TEXT,observed_at TEXT,basis TEXT);
            ''')

    def connect(self):
        con = sqlite3.connect(self.db, timeout=20)
        con.row_factory = sqlite3.Row
        return con

    def enrich_section(self,post,con):
        native_id=post.get('board_id')
        if native_id:
            row=con.execute('SELECT name,basis FROM sections WHERE id=?',(native_id,)).fetchone()
            if row:post.update(board=row['name'],board_basis=row['basis'])
        return post

    def save_sections(self,items):
        if not isinstance(items,list) or len(items)>100:raise ValueError('分区目录需要100条以内的列表。')
        updated=0
        with closing(self.connect()) as con,con:
            for item in items:
                section_id=str(item.get('id',''));name=str(item.get('name','')).strip()[:100]
                if not re.fullmatch(r'\d{1,15}',section_id) or not name or name in ('全部','热门'):continue
                url=urlsplit(str(item.get('url','')))
                if url.hostname!='pd.qq.com' or url.path!='/g/npu0lakeside' or parse_qs(url.query).get('subc',[''])[0]!=section_id:continue
                con.execute('INSERT INTO sections VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,observed_at=excluded.observed_at,basis=excluded.basis',(section_id,name,now(),'visible_section_navigation'))
            for row in con.execute('SELECT id,data_json FROM posts').fetchall():
                original=json.loads(row['data_json']);post=dict(original)
                native_id=parse_qs(urlsplit(str(post.get('url',''))).query).get('subc',[''])[0]
                if re.fullmatch(r'\d{1,15}',native_id):post['board_id']=native_id
                entry=post.get('sampling_entry')
                if entry:
                    post.setdefault('sampling_entries',[entry]);post.setdefault('sampling_frame','primary_all' if entry=='全部' else 'section_supplement' if post.get('board_id') and entry!='热门' else 'other_entry')
                self.enrich_section(post,con)
                if post!=original:con.execute('UPDATE posts SET data_json=? WHERE id=?',(json.dumps(post,ensure_ascii=False),row['id']));updated+=1
            catalog=[dict(row) for row in con.execute('SELECT * FROM sections ORDER BY name')]
        (self.root/'索引/分区目录.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'ok':True,'sections':catalog,'posts_updated':updated}

    def import_document(self, data, payload, filename, stage='正式', archive=True):
        if not isinstance(data, dict) or not isinstance(data.get('posts'), list): raise ValueError('请选择页面观察 JSON。')
        if stage not in ('正式', '试采'): raise ValueError('请选择正式或试采。')
        digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()
        added = enriched = skipped = invalid = 0
        with closing(self.connect()) as con, con:
            existing = con.execute('SELECT * FROM batches WHERE batch_id=?', (digest,)).fetchone()
            if existing: return {'already_imported': True, 'new_posts': 0, 'enriched': 0, 'skipped': existing['input_records'], 'batch_id': digest}
            for raw in sorted(data['posts'], key=lambda p: p.get('preview_only', True) if isinstance(p, dict) else True):
                post = clean_post(raw)
                if not post: invalid += 1; continue
                self.enrich_section(post,con)
                row = con.execute('SELECT data_json,first_seen FROM posts WHERE id=?', (post['id'],)).fetchone()
                if row:
                    old = json.loads(row['data_json']); combined = merge_post(old, post)
                    volatile = {'captured_at','comment_count_as_of','displayed_date_label','source_page'}
                    if {k:v for k,v in combined.items() if k not in volatile} != {k:v for k,v in old.items() if k not in volatile}:
                        enriched += 1
                        con.execute('UPDATE posts SET data_json=?,last_seen=? WHERE id=?', (json.dumps(combined, ensure_ascii=False), now(), post['id']))
                    else: skipped += 1
                else:
                    added += 1
                    con.execute('INSERT INTO posts VALUES(?,?,?,?,?)', (post['id'], json.dumps(post, ensure_ascii=False), post.get('captured_at') or data.get('captured_at') or now(), now(), stage))
                for image in post['images']:
                    url_hash = hashlib.sha256(image['url'].encode()).hexdigest()
                    con.execute('INSERT OR IGNORE INTO media VALUES(?,?,?,?,?,?)', (url_hash, image['url'], None, 0, '待保存', '{}'))
                    con.execute('INSERT OR IGNORE INTO post_images VALUES(?,?)', (post['id'], url_hash))
            if archive:
                target = self.root / '批次' / (digest[:20] + '.json')
                if not target.exists(): target.write_bytes(payload)
                source_path = str(target.relative_to(self.root))
            else: source_path = str(filename)
            con.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?,?)', (digest, Path(filename).name, now(), stage, source_path, len(payload), added, enriched, skipped, len(data['posts'])))
        self.write_index()
        return {'already_imported': False, 'new_posts': added, 'enriched': enriched, 'skipped': skipped, 'invalid': invalid, 'batch_id': digest}

    def write_index(self):
        entries = {}
        with closing(self.connect()) as con:
            for row in con.execute('SELECT * FROM posts'):
                post = json.loads(row['data_json'])
                entries[row['id']] = {'first_seen': row['first_seen'], 'has_detail': post.get('preview_only') is False,
                    'images': [fnv(image['url']) for image in post.get('images', [])], 'detail_hash': None}
        target = self.root / '索引' / '启翔湖畔去重索引.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps({'schema': 'qixiang_seen_index_v2', 'entries': entries}, ensure_ascii=False), encoding='utf-8')
        temp.replace(target)

    def media_totals(self):
        with closing(self.connect()) as con:
            rows = con.execute("SELECT relative_path,max(bytes) AS bytes FROM media WHERE status='已保存' GROUP BY relative_path").fetchall()
        return len(rows), sum(row['bytes'] or 0 for row in rows)

    def download_media(self, progress=lambda text: None, max_images=5000, budget=2_000_000_000):
        opener = build_opener(NoRedirect())
        saved_count, saved_bytes = self.media_totals()
        with closing(self.connect()) as con:
            rows = con.execute("SELECT * FROM media WHERE status='待保存' LIMIT ?", (max_images,)).fetchall()
        for index, row in enumerate(rows):
            progress(f'保存图片 {index + 1}/{len(rows)}，已用 {saved_bytes / 1_000_000:.1f} MB')
            if saved_bytes + 1_000_000 > budget or shutil.disk_usage(self.root).free < 2_000_000_000:
                progress('达到图片预算或磁盘保留空间，已保存的资料保持可用'); break
            status, info = '请求失败', {}
            try:
                request = Request(row['url'], headers={'User-Agent': 'Mozilla/5.0 (local research image archive)'})
                with opener.open(request, timeout=15) as response:
                    if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                        raise ValueError('image_response_required')
                    payload = response.read(16 * 1024 * 1024 + 1)
                    if len(payload) > 16 * 1024 * 1024: raise ValueError('download_size_limit')
                info = store_image(payload, self.root / '图片'); status = '已保存'
                saved_bytes = self.media_totals()[1] + info['bytes']
            except Exception as error:
                info = {'error_type': type(error).__name__}
            with closing(self.connect()) as con, con:
                con.execute('UPDATE media SET relative_path=?,bytes=?,status=?,info_json=? WHERE url_hash=?', (info.get('relative_path'), info.get('bytes', 0), status, json.dumps(info, ensure_ascii=False), row['url_hash']))
            time.sleep(.4)
        return self.media_totals()

    def import_saved_images(self, manifest):
        data = json.loads(manifest.read_text(encoding='utf-8'))
        count = 0
        with closing(self.connect()) as con, con:
            for entry in data.get('entries', []):
                if entry.get('status') != 'saved' or not entry.get('saved_file'): continue
                local = (manifest.parent / entry['saved_file']).resolve()
                if local.parent != manifest.parent.resolve() or not local.is_file(): continue
                digest = hashlib.sha256(str(entry.get('source_url', '')).encode()).hexdigest()
                row = con.execute('SELECT status FROM media WHERE url_hash=?', (digest,)).fetchone()
                if not row or row['status'] == '已保存': continue
                info = store_image(local.read_bytes(), self.root / '图片')
                con.execute('UPDATE media SET relative_path=?,bytes=?,status=?,info_json=? WHERE url_hash=?', (info['relative_path'], info['bytes'], '已保存', json.dumps(info, ensure_ascii=False), digest))
                count += 1
        return count

    def posts(self, stage='', search='', category='', reviewed='', page=1, limit=30,board_id=''):
        conditions, args = [], []
        if stage: conditions.append('p.stage=?'); args.append(stage)
        if board_id:conditions.append("json_extract(p.data_json,'$.board_id')=?");args.append(board_id)
        if search: conditions.append('p.data_json LIKE ?'); args.append('%' + search + '%')
        if category: conditions.append("json_extract(a.data_json,'$.main_category')=?"); args.append(category)
        if reviewed == '待复核': conditions.append('a.post_id IS NULL')
        if reviewed == '已复核': conditions.append('a.post_id IS NOT NULL')
        clause = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with closing(self.connect()) as con:
            count = con.execute('SELECT count(*) FROM posts p LEFT JOIN annotations a ON p.id=a.post_id' + clause, args).fetchone()[0]
            rows = con.execute('SELECT p.*,a.data_json AS annotation FROM posts p LEFT JOIN annotations a ON p.id=a.post_id' + clause + ' ORDER BY p.first_seen,p.id LIMIT ? OFFSET ?', args + [limit, (max(1, page)-1)*limit]).fetchall()
            result = []
            for row in rows:
                post = json.loads(row['data_json']); post.update(stage=row['stage'], first_seen=row['first_seen'], annotation=json.loads(row['annotation'] or '{}'))
                post['local_images'] = [dict(image) for image in con.execute('SELECT m.relative_path,m.bytes,m.status FROM media m JOIN post_images pi ON m.url_hash=pi.url_hash WHERE pi.post_id=?', (row['id'],))]
                if hasattr(self,'bridge'):post['evidence']=self.bridge.evidence(row['id'])
                if hasattr(self,'local_model'):
                    label=con.execute('SELECT data_json FROM model_labels WHERE post_id=?',(row['id'],)).fetchone()
                    post['model_label']=json.loads(label[0]) if label else None
                result.append(post)
        return {'total': count, 'page': page, 'posts': result}

    def annotate(self, data):
        post_id = data.get('post_id')
        with closing(self.connect()) as con, con:
            if not con.execute('SELECT 1 FROM posts WHERE id=?', (post_id,)).fetchone(): raise ValueError('帖子ID未找到。')
            annotation = {key: str(data.get(key) or '')[:2000] for key in ANNOTATIONS}
            if annotation['main_category'] not in CATEGORIES: raise ValueError('请选择主类别。')
            con.execute('INSERT INTO annotations VALUES(?,?,?) ON CONFLICT(post_id) DO UPDATE SET data_json=excluded.data_json,reviewed_at=excluded.reviewed_at', (post_id, json.dumps(annotation, ensure_ascii=False), now()))

    def import_reviews(self, text):
        accepted = skipped = 0
        rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
        if len(rows) > 5000: raise ValueError('复核表每批上限5000行。')
        for row in rows:
            if row.get('main_category') not in CATEGORIES: skipped += 1; continue
            with closing(self.connect()) as con:
                existing = con.execute('SELECT data_json FROM annotations WHERE post_id=?',(row.get('post_id'),)).fetchone()
            data = json.loads(existing['data_json']) if existing else {}
            data.update({key: row[key] for key in ANNOTATIONS if row.get(key)})
            data['post_id'] = row.get('post_id')
            try: self.annotate(data); accepted += 1
            except ValueError: skipped += 1
        return {'accepted': accepted, 'skipped': skipped}

    def summary(self):
        with closing(self.connect()) as con:
            stages = dict(con.execute('SELECT stage,count(*) FROM posts GROUP BY stage').fetchall())
            reviewed = dict(con.execute('SELECT p.stage,count(*) FROM annotations a JOIN posts p ON p.id=a.post_id GROUP BY p.stage').fetchall())
            types = [dict(row) for row in con.execute("SELECT p.stage,json_extract(a.data_json,'$.main_category') AS category,count(*) AS count FROM annotations a JOIN posts p ON p.id=a.post_id GROUP BY p.stage,category")]
            batches = [dict(row) for row in con.execute('SELECT * FROM batches ORDER BY imported_at DESC LIMIT 30')]
            media_status = dict(con.execute('SELECT status,count(*) FROM media GROUP BY status').fetchall())
            sections=[dict(row) for row in con.execute("SELECT s.id,s.name,count(p.id) AS posts FROM sections s LEFT JOIN posts p ON json_extract(p.data_json,'$.board_id')=s.id AND p.stage='正式' GROUP BY s.id ORDER BY posts DESC,s.name")]
            coverage=dict(con.execute("""SELECT coalesce(sum(json_array_length(data_json,'$.images')>0),0) AS images,
                coalesce(sum(json_extract(data_json,'$.preview_only')=0),0) AS details,
                coalesce(sum(length(json_extract(data_json,'$.created_at'))>0),0) AS dates,
                coalesce(sum(json_array_length(data_json,'$.visible_comments')>0),0) AS comments,
                coalesce(sum(length(json_extract(data_json,'$.created_at_estimated'))>0),0) AS estimated_dates
                FROM posts""").fetchone())
        files, image_bytes = self.media_totals()
        return {'app': 'qixiang_research_library_v2', 'stages': stages, 'reviewed': reviewed, 'categories': CATEGORIES,
            'reviewed_types': types, 'batches': batches, 'coverage': coverage, 'image_files': files,
            'image_bytes': image_bytes, 'media_status': media_status, 'free_bytes': shutil.disk_usage(self.root).free,
            'total_posts': sum(stages.values()), 'formal_target': 10000, 'library_root': str(self.root),'sections':sections}

    def csv_export(self, sample_size=0, stage='正式'):
        if stage == 'all': stage = ''
        with closing(self.connect()) as con:
            rows=con.execute('SELECT p.*,a.data_json AS annotation FROM posts p LEFT JOIN annotations a ON p.id=a.post_id'+(' WHERE p.stage=?' if stage else '')+' ORDER BY p.first_seen,p.id',([stage] if stage else [])).fetchall()
            tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            labels={row[0]:json.loads(row[1]) for row in con.execute('SELECT post_id,data_json FROM model_labels')} if 'model_labels' in tables else {}
            shots={}
            if 'screenshots' in tables:
                for row in con.execute('SELECT post_id,scope,relative_path FROM screenshots'):shots.setdefault(row[0],{})[row[1]]=row[2]
        posts=[]
        for row in rows:
            post=json.loads(row['data_json']);post.update(stage=row['stage'],first_seen=row['first_seen'],last_seen=row['last_seen'],annotation=json.loads(row['annotation'] or '{}'))
            post['model_label']=labels.get(row['id'],{});post['shots']=shots.get(row['id'],{});posts.append(post)
        frame_count = len(posts)
        if sample_size and not posts: raise ValueError('当前来源的材料等待导入，之后可抽样。')
        if sample_size and posts:
            posts = random.Random(20261019).sample(sorted(posts, key=lambda p: p['id']), min(sample_size, len(posts)))
        time_fields=['created_at','created_at_estimated','created_at_earliest','created_at_latest','time_method','time_precision','displayed_date_label','time_label_raw','page_age_seconds']
        output = io.StringIO(newline=''); fields = ['post_id','stage','text','preview_only','url','captured_at','first_seen','last_seen']+time_fields+['board_id','board','board_basis','sampling_entry','sampling_entries','sampling_frame','comments_scope','detail_selection','comment_count','image_count','visible_comment_count','list_screenshot','detail_screenshot','model_category','model_topic','model_evidence','candidate_labels'] + ANNOTATIONS
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for post in posts:
            row={key:post.get(key,'') for key in fields}
            label=post['model_label'];row.update(post_id=post['id'],image_count=len(post['images']),visible_comment_count=len(post['visible_comments']),list_screenshot=post['shots'].get('list',''),detail_screenshot=post['shots'].get('detail',''),model_category=label.get('category',''),model_topic=label.get('topic',''),model_evidence=label.get('evidence',''))
            row.update(post['annotation']); writer.writerow({key: csv_safe(row.get(key, '')) for key in fields})
        payload = ('\ufeff' + output.getvalue()).encode('utf-8')
        if sample_size:
            stem = '人工复核抽样_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            (self.root/'分析导出'/(stem+'.csv')).write_bytes(payload)
            (self.root/'分析导出'/(stem+'.json')).write_text(json.dumps({'created_at':now(),'source_stage':stage,
                'frame_posts':frame_count,'sample_posts':len(posts),'seed':20261019,
                'sample_post_ids':[post['id'] for post in posts]},ensure_ascii=False,indent=2),encoding='utf-8')
        return payload


def serve(library, port, open_browser=True):
    from capture_bridge import CaptureBridge
    bridge = CaptureBridge(library,write_connection=(port==8765 and library.root.resolve()==DEFAULT_ROOT.resolve()),base_url=f'http://127.0.0.1:{port}')
    library.bridge=bridge
    from local_model import LocalModel
    local_model=LocalModel(library);library.local_model=local_model
    from background_manager import BackgroundManager
    background=BackgroundManager(library)
    job = {'running': False, 'message': '等待导入', 'result': None}
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, data, status=200, content_type='application/json; charset=utf-8', name=None):
            if not isinstance(data, bytes): data = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if name: self.send_header('Content-Disposition', 'attachment; filename="' + name + '"')
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}': self.send({'error':'local_host_required'},403); return
            parsed = urlsplit(self.path); query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            try:
                if parsed.path == '/api/health': self.send({'app':'qixiang_research_library_v2','ready':True,'version':'3.1'})
                elif parsed.path == '/api/state': self.send({**library.summary(), 'collector':bridge.status()})
                elif parsed.path == '/api/collector/state': self.send(bridge.status())
                elif parsed.path == '/api/model/state': self.send(local_model.status())
                elif parsed.path == '/api/background/state': self.send(background.status())
                elif parsed.path == '/api/job': self.send(dict(job))
                elif parsed.path == '/api/posts': self.send(library.posts(stage=query.get('stage',''), search=query.get('search','')[:200], category=query.get('category',''), reviewed=query.get('reviewed',''), page=max(1,int(query.get('page',1))),board_id=query.get('board_id','')))
                elif parsed.path == '/api/index':
                    library.write_index(); self.send((library.root/'索引/启翔湖畔去重索引.json').read_bytes(), name='qixiang_seen_index.json')
                elif parsed.path == '/api/export': self.send(library.csv_export(min(10000,int(query.get('sample',0))), query.get('stage','正式')), content_type='text/csv; charset=utf-8', name='qixiang_review.csv')
                elif parsed.path.startswith('/evidence/'):
                    pieces=parsed.path.split('/')
                    if len(pieces)!=4 or pieces[2] not in ('shots','avatars') or not re.fullmatch(r'[a-f0-9]{64}\.jpg',pieces[3]): raise ValueError('invalid_evidence_path')
                    folder='截图' if pieces[2]=='shots' else '头像'
                    self.send((library.root/folder/pieces[3]).read_bytes(),content_type='image/jpeg')
                elif parsed.path.startswith('/media/'):
                    name = parsed.path.removeprefix('/media/')
                    if not re.fullmatch(r'[a-f0-9]{64}\.jpg',name): raise ValueError('image_path')
                    self.send((library.root/'图片'/name).read_bytes(), content_type='image/jpeg')
                elif parsed.path in ('/','/dashboard.js','/style.css'):
                    file = {'/':'index.html','/dashboard.js':'dashboard.js','/style.css':'style.css'}[parsed.path]
                    kind = {'/':'text/html','/dashboard.js':'text/javascript','/style.css':'text/css'}[parsed.path]
                    self.send((TOOL/'workspace_ui'/file).read_bytes(), content_type=kind+'; charset=utf-8')
                else: self.send({'error':'not_found'},404)
            except Exception as error: self.send({'error': str(error)},400)
        def do_OPTIONS(self):
            origin=self.headers.get('Origin','')
            if self.headers.get('Host')!=f'127.0.0.1:{port}' or not re.fullmatch(r'chrome-extension://[a-p]{32}',origin): self.send({'error':'local_extension_required'},403); return
            self.send_response(204);self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            self.send_header('Access-Control-Allow-Methods','GET, POST');self.end_headers()
        def do_POST(self):
            expected = f'http://127.0.0.1:{port}'
            from_extension=bridge.authorized(self.headers)
            if self.headers.get('Host') != f'127.0.0.1:{port}' or (self.headers.get('Origin') != expected and not from_extension) or not self.headers.get('Content-Type','').startswith('application/json'):
                self.send({'error':'请从本地资料管理页面操作。'},403); return
            length = int(self.headers.get('Content-Length',0))
            if length <= 0 or length > 35*1024*1024: self.send({'error':'文件大小上限35MB。'},400); return
            try:
                data = json.loads(self.rfile.read(length))
                if self.path.startswith('/api/collector/'):
                    if not from_extension: self.send({'error':'采集连接需要本机扩展令牌。'},403);return
                    if self.path=='/api/collector/start': self.send(bridge.start(data))
                    elif self.path=='/api/collector/ingest': self.send(bridge.ingest(data))
                    elif self.path=='/api/collector/screenshot': self.send(bridge.screenshot(data))
                    elif self.path=='/api/collector/update': self.send(bridge.update(str(data.get('run_id','')),data.get('state',{})))
                    elif self.path=='/api/collector/status': self.send(bridge.status())
                    elif self.path=='/api/collector/sections': self.send(library.save_sections(data.get('sections',[])))
                    else:self.send({'error':'not_found'},404)
                elif self.path == '/api/capture-stop': self.send(bridge.stop())
                elif self.path == '/api/background/login': self.send(background.command('login'))
                elif self.path == '/api/background/start': self.send(background.command('collect',data))
                elif self.path == '/api/background/stop': self.send(background.command('stop'))
                elif self.path == '/api/media/resume': self.send(bridge.resume_media())
                elif self.path == '/api/model/start': self.send(local_model.start(int(data.get('limit',100)),str(data.get('stage','正式'))))
                elif self.path == '/api/model/stop': self.send(local_model.stop())
                elif self.path == '/api/analysis/export':
                    from research_exports import build_exports
                    self.send(build_exports(library))
                elif self.path == '/api/annotate': library.annotate(data); self.send({'ok':True})
                elif self.path == '/api/reviews': self.send(library.import_reviews(str(data.get('csv_text',''))))
                elif self.path == '/api/import':
                    if not lock.acquire(blocking=False): self.send({'error':'当前导入仍在处理，请稍候。'},409); return
                    def worker():
                        try:
                            job.update(running=True,message='导入并核对帖子ID',result=None)
                            source = data['document']; payload = json.dumps(source,ensure_ascii=False).encode()
                            result = library.import_document(source,payload,str(data.get('filename','页面观察.json')),str(data.get('stage','正式')))
                            if data.get('download_images'): library.download_media(lambda message: job.update(message=message))
                            job.update(result=result,message='本批导入完成，资料已合并保存')
                        except Exception as error: job.update(message='导入遇到问题：'+str(error))
                        finally: job['running']=False; lock.release()
                    job['running']=True; threading.Thread(target=worker,daemon=True).start(); self.send({'ok':True})
                else: self.send({'error':'not_found'},404)
            except Exception as error: self.send({'error':str(error)},400)
    library.write_index()
    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    if open_browser: threading.Timer(.5,lambda:webbrowser.open(f'http://127.0.0.1:{port}')).start()
    print(f'Local research workspace: http://127.0.0.1:{port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def main():
    parser=argparse.ArgumentParser(description='启翔湖畔本地资料管理')
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    sub=parser.add_subparsers(dest='command',required=True)
    item=sub.add_parser('import');item.add_argument('input',type=Path);item.add_argument('--stage',choices=['正式','试采'],default='正式');item.add_argument('--images',action='store_true')
    item=sub.add_parser('serve');item.add_argument('--port',type=int,default=8765);item.add_argument('--no-browser',action='store_true')
    sub.add_parser('status')
    args=parser.parse_args();library=Library(args.root)
    if args.command=='serve': serve(library,args.port,not args.no_browser)
    elif args.command=='import':
        payload=args.input.read_bytes();print(json.dumps(library.import_document(json.loads(payload.decode('utf-8-sig')),payload,args.input.name,args.stage),ensure_ascii=False))
        if args.images: library.download_media(print)
    else: print(json.dumps(library.summary(),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
