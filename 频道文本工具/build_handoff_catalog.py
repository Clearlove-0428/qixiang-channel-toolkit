"""Expose existing post-media relationships as reproducible, usable local files."""
from __future__ import annotations
import csv
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / '调研资料库'
OUT = ROOT / '协作交接/数据入口'


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def safe_cell(value):
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    value = str(value if value is not None else '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def save_table(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: safe_cell(row.get(field)) for field in fields})


def main():
    global ROOT, LIBRARY, OUT
    parser = argparse.ArgumentParser(description='把本地资料库或分析快照导出为逐帖浏览页面与对应表。')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--library-root', type=Path, default=LIBRARY)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    database = args.database.expanduser().resolve(strict=True)
    LIBRARY = args.library_root.expanduser().resolve()
    ROOT = LIBRARY.parent
    OUT = (args.output or LIBRARY / '逐帖资料').expanduser().resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM posts WHERE stage='正式' ORDER BY first_seen,id").fetchall()
        media = {r['url_hash']: dict(r) for r in connection.execute('SELECT * FROM media')}
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        avatars = {r['url_hash']: dict(r) for r in connection.execute('SELECT * FROM avatars')} if 'avatars' in tables else {}
        labels = {r['post_id']: json.loads(r['data_json']) for r in connection.execute('SELECT * FROM model_labels')} if 'model_labels' in tables else {}
        reviews = {r['post_id']: json.loads(r['data_json']) for r in connection.execute('SELECT * FROM annotations')} if 'annotations' in tables else {}
        image_links = defaultdict(list)
        shots = defaultdict(list)
        for row in connection.execute('SELECT * FROM post_images'):
            image_links[row['post_id']].append(row['url_hash'])
        for row in (connection.execute('SELECT * FROM screenshots') if 'screenshots' in tables else []):
            shots[row['post_id']].append(dict(row))
    assets, flat_posts, comments, catalog, all_posts = [], [], [], [], []
    statistics = Counter()
    categories = Counter()

    def asset(post_id, research_id, role, item, order, info=None):
        folder = {'正文图片': '图片', '头像': '头像', '列表截图': '截图', '详情截图': '截图'}[role]
        name = item.get('relative_path')
        absolute = LIBRARY / folder / name if name else None
        present = bool(absolute and absolute.is_file())
        relative = absolute.relative_to(ROOT).as_posix() if absolute else ''
        result = {'role': role, 'order': order, 'project_path': relative,
            'browser_path': Path(os.path.relpath(absolute, OUT)).as_posix() if absolute else '',
            'exists': present, 'saved_status': item.get('status', '已保存' if name else '待保存'),
            'bytes': item.get('bytes', 0), 'capture_info': info or {},
            'meaning_status': '待按研究需要解析' if role == '正文图片' else '原样证据'}
        assets.append({'研究编号': research_id, '帖子ID': post_id, '媒体角色': role,
            '顺序': order, '项目内路径': relative, '文件存在': int(present),
            '保存状态': result['saved_status'], '文件字节': result['bytes'],
            '语义状态': result['meaning_status']})
        statistics[role + '关联记录'] += 1
        if name and not present:
            statistics['有路径但文件缺失'] += 1
        if not name:
            statistics['媒体关联待保存'] += 1
        return result

    for number, row in enumerate(rows, 1):
        p = json.loads(row['data_json'])
        pid = p['id']
        rid = f'P{number:05d}'
        linked = []
        # Original image order follows the source post; all stored links remain available.
        ordered_hashes = [hashlib.sha256(i['url'].encode()).hexdigest() for i in p.get('images', [])]
        ordered_hashes = list(dict.fromkeys(ordered_hashes + image_links[pid]))
        for order, digest in enumerate(ordered_hashes, 1):
            item = media.get(digest)
            if item:
                linked.append(asset(pid, rid, '正文图片', item, order))
        url = p.get('author_avatar_url')
        if url:
            item = avatars.get(hashlib.sha256(url.encode()).hexdigest())
            if item:
                linked.append(asset(pid, rid, '头像', item, 1))
        for order, item in enumerate(shots[pid], 1):
            linked.append(asset(pid, rid, '详情截图' if item['scope'] == 'detail' else '列表截图',
                item, order, json.loads(item['info_json'] or '{}')))
        label = labels.get(pid, {})
        categories[label.get('category', '待标注')] += 1
        board = p.get('board') or '页面分区编号' + str(p.get('board_id') or '待核实')
        record = {'schema_version': 'post-research-handoff.v1', 'research_id': rid,
            'post_id': pid, 'stage': '正式', 'original_url': p.get('url', ''),
            'native_section': {'id': p.get('board_id', ''), 'name': board, 'basis': p.get('board_basis', '')},
            'sampling': {key: p.get(key) for key in ('sampling_entry', 'sampling_entries', 'sampling_frame')},
            'text': p.get('text', ''), 'title': p.get('title', ''),
            'content_scope': {key: p.get(key) for key in ('preview_only', 'text_source', 'text_truncated_by_tool', 'comments_scope', 'detail_selection')},
            'time': {key: p.get(key) for key in ('captured_at', 'created_at', 'displayed_date_label', 'created_at_estimated', 'created_at_earliest', 'created_at_latest', 'time_method', 'time_precision', 'time_observations')},
            'visible_comments': p.get('visible_comments', []), 'displayed_comment_count': p.get('comment_count'),
            'assets': linked, 'model_candidate': label, 'human_review': reviews.get(pid),
            'original_post': p, 'first_seen': row['first_seen'], 'last_seen': row['last_seen'],
            'image_analysis': {'status': '待按研究需要处理', 'ocr_text': None, 'visual_summary': None,
                'instruction': '图片含义与文件对应关系分开记录；头像仅供本机核对。'}}
        all_posts.append(record)
        image_paths = [a['project_path'] for a in linked if a['role'] == '正文图片' and a['project_path']]
        shot_paths = [a['project_path'] for a in linked if a['role'].endswith('截图') and a['project_path']]
        avatar_paths = [a['project_path'] for a in linked if a['role'] == '头像' and a['project_path']]
        flat_posts.append({'研究编号': rid, '帖子ID': pid, '原生分区': board, '分区编号': p.get('board_id'),
            '首次入口': p.get('sampling_entry'), '采集来源': p.get('sampling_frame'), '正文': p.get('text'),
            '正文范围': '列表预览' if p.get('preview_only', True) else '详情正文',
            '观察时刻': p.get('captured_at'), '页面时间标签': p.get('displayed_date_label'),
            '时间精度': p.get('time_precision'), '原帖链接': p.get('url'),
            '正文图片路径': image_paths, '头像路径': avatar_paths, '截图路径': shot_paths,
            '已保存评论文字条数': len(p.get('visible_comments', [])), '页面评论数快照': p.get('comment_count'),
            '模型候选类别': label.get('category'), '模型候选主题': label.get('topic'),
            '模型原文依据': label.get('evidence'), '人工复核状态': '已填写主类别' if reviews.get(pid, {}).get('main_category') else '待复核', '图片解析状态': '待按研究需要处理'})
        for order, comment in enumerate(p.get('visible_comments', []), 1):
            comments.append({'研究编号': rid, '帖子ID': pid, '保存顺序': order, '评论文字': comment.get('text'),
                '页面时间标签': comment.get('displayed_time_label'), '观察时刻': p.get('captured_at'),
                '取得范围': p.get('comments_scope')})
        catalog.append({'id': rid, 'post_id': pid, 'board': board, 'text': p.get('text', ''),
            'url': p.get('url', ''), 'time_label': p.get('displayed_date_label', ''),
            'preview': p.get('preview_only', True), 'category': label.get('category', ''),
            'topic': label.get('topic', ''), 'comments': p.get('visible_comments', []), 'assets': linked})
    with (OUT / '帖子完整资料.jsonl').open('w', encoding='utf-8') as stream:
        for post in all_posts:
            stream.write(json.dumps(post, ensure_ascii=False) + '\n')
    save_table(OUT / '帖子总表.csv', flat_posts, list(flat_posts[0]) if flat_posts else ['研究编号', '帖子ID', '正文'])
    save_table(OUT / '媒体与帖子对应表.csv', assets, list(assets[0]) if assets else ['研究编号', '帖子ID', '媒体角色'])
    save_table(OUT / '评论对应表.csv', comments, list(comments[0]) if comments else ['研究编号', '帖子ID', '评论文字'])
    (OUT / '帖子目录数据.js').write_text('window.POST_CATALOG=' + json.dumps(catalog, ensure_ascii=False).replace('<', '\\u003c') + ';', encoding='utf-8')
    template = Path(__file__).with_name('handoff_catalog.html')
    shutil.copy2(template, OUT / '逐帖浏览.html')
    metadata = {'generated_at': datetime.now().astimezone().isoformat(), 'source_database': str(database),
        'source_database_sha256': hashlib.sha256(database.read_bytes()).hexdigest(), 'formal_posts': len(rows),
        'visible_comment_records': len(comments), 'media_associations': len(assets),
        'linkage_audit': {**dict(statistics), '有路径但文件缺失': statistics['有路径但文件缺失'],
            '媒体关联待保存': statistics['媒体关联待保存']}, 'candidate_categories': dict(categories),
        'manual_reviewed': sum(bool(reviews.get(row['id'], {}).get('main_category')) for row in rows), 'ocr_processed': None, 'image_meanings_reviewed': None,
        'scope': '本次输入资料的可读导出；原文件沿用既有路径。此工具未读取OCR和图像语义结果，相应数量未知。'}
    save_json(OUT / '数据入口核验.json', metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
