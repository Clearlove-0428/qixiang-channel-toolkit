"""Freeze a reproducible local corpus and export evidence tables for the course report."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import shutil
import sqlite3
from collections import Counter,defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from analyze_posts import csv_safe


def table(path,fields,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({key:csv_safe(row.get(key,'')) for key in fields})


def chart(path,title,counts,caption):
    width=1000;height=160+len(counts)*48;maximum=max([1,*counts.values()])
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#fafcfb"/>',
           '<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" fill="#203d47">',
           f'<text x="30" y="45" font-size="25" font-weight="bold">{escape(title)}</text>']
    for index,(label,count) in enumerate(counts.items()):
        y=78+index*48;bar=round(count/maximum*620)
        parts.extend([f'<text x="30" y="{y+22}" font-size="19">{escape(str(label))}</text>',
                      f'<rect x="220" y="{y}" width="{bar}" height="30" rx="4" fill="#247f78"/>',
                      f'<text x="{235+bar}" y="{y+22}" font-size="19">{count}</text>'])
    parts.extend([f'<text x="30" y="{height-25}" font-size="16">{escape(caption)}</text>','</g></svg>'])
    path.write_text('\n'.join(parts),encoding='utf-8')


def build_exports(library):
    from research_library import Library,now
    if shutil.disk_usage(library.root).free<250_000_000:raise ValueError('请先为分析版本安排250MB可用空间。')
    folder=library.root/'分析导出'/('资料版本_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir(parents=True)
    snapshot=folder/'资料快照.sqlite3'
    with closing(library.connect()) as source,closing(sqlite3.connect(snapshot)) as target:source.backup(target)
    frozen=Library.__new__(Library);frozen.root=library.root;frozen.db=snapshot
    with closing(frozen.connect()) as con:
        tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows=con.execute('SELECT p.*,a.data_json AS annotation FROM posts p LEFT JOIN annotations a ON p.id=a.post_id WHERE p.stage=? ORDER BY p.first_seen,p.id',('正式',)).fetchall()
        labels={r[0]:json.loads(r[1]) for r in con.execute('SELECT post_id,data_json FROM model_labels')} if 'model_labels' in tables else {}
        runs=[dict(r) for r in con.execute('SELECT * FROM capture_runs ORDER BY started_at')] if 'capture_runs' in tables else []
        shots=[dict(r) for r in con.execute('SELECT post_id,scope,relative_path,bytes,info_json FROM screenshots')] if 'screenshots' in tables else []
        stages=dict(con.execute('SELECT stage,count(*) FROM posts GROUP BY stage'))
    posts=[]
    for row in rows:
        p=json.loads(row['data_json']);p.update(annotation=json.loads(row['annotation'] or '{}'),first_seen=row['first_seen'],last_seen=row['last_seen']);posts.append(p)
    count=len(posts);ids={p['id'] for p in posts};model=Counter();human=Counter();topics=defaultdict(list);entry=Counter();times=Counter();comments=[];sections=Counter();frames=Counter()
    detail_count=comment_posts=comment_snapshots=image_posts=relative_count=0
    for post in posts:
        label=labels.get(post['id']);annotation=post['annotation'];entry[post.get('sampling_entry') or '入口待核实']+=1
        sections[post.get('board') or '页面分区编号'+str(post.get('board_id') or '缺省')]+=1
        frames[post.get('sampling_frame') or '按原始记录']+=1
        if label:model[label.get('category','待判断')]+=1;topics[label.get('topic','待复核')].append(post['id'])
        if annotation.get('main_category'):human[annotation['main_category']]+=1
        times[post.get('time_precision') or ('页面日期' if post.get('created_at') else '时间待核实')]+=1
        detail_count+=post.get('preview_only') is False;comment_posts+=bool(post['visible_comments']);image_posts+=bool(post['images'])
        relative_count+=post.get('time_method')=='relative_estimate'
        for index,comment in enumerate(post['visible_comments']):comments.append({'post_id':post['id'],'order_in_saved_record':index+1,'text':comment['text'],'displayed_time_label':comment.get('displayed_time_label',''),'captured_at':post.get('captured_at',''),'scope':post.get('comments_scope','按当时页面可见范围记录')})
        if isinstance(post.get('comment_count'),int):comment_snapshots+=1
    shot_ids={r['post_id'] for r in shots if r['post_id'] in ids};detail_shots={r['post_id'] for r in shots if r['post_id'] in ids and r['scope']=='detail'}
    agreement=Counter()
    for post in posts:
        annotation=post['annotation'];label=labels.get(post['id'])
        if label and annotation.get('main_category'):
            agreement['可比较帖子']+=1;agreement['类别一致']+=annotation['main_category']==label.get('category')
    coverage={'正式去重帖子':count,'取得主帖详情':detail_count,'含图片地址':image_posts,'取得至少一种截图':len(shot_ids),'取得详情截图':len(detail_shots),'取得可见评论文字':comment_posts,'已保存评论文字条数':len(comments),'取得数值评论快照':comment_snapshots,'保留相对时间估计':relative_count,'取得本地模型候选':sum(model.values()),'已人工分类':sum(human.values())}
    files={}
    (folder/'帖子分析表.csv').write_bytes(frozen.csv_export(stage='正式'))
    with (folder/'正式帖子.jsonl').open('w',encoding='utf-8') as stream:
        for p in posts:stream.write(json.dumps({**p,'model_label':labels.get(p['id'])},ensure_ascii=False)+'\n')
    table(folder/'材料覆盖.csv',['指标','数量'],[{'指标':k,'数量':v} for k,v in coverage.items()])
    table(folder/'模型候选类别.csv',['类别','帖子数','性质'],[{'类别':k,'帖子数':v,'性质':'本机模型候选，待抽样核对'} for k,v in model.most_common()])
    table(folder/'人工复核类别.csv',['类别','帖子数','分母'],[{'类别':k,'帖子数':v,'分母':sum(human.values())} for k,v in human.most_common()])
    table(folder/'时间精度.csv',['时间记录方式','帖子数'],[{'时间记录方式':k,'帖子数':v} for k,v in times.items()])
    table(folder/'入口覆盖.csv',['入口','帖子数'],[{'入口':k,'帖子数':v} for k,v in entry.items()])
    table(folder/'原生分区覆盖.csv',['分区','帖子数','范围'],[{'分区':k,'帖子数':v,'范围':'实际采集材料，含按分区观察上限取得的补充资料'} for k,v in sections.most_common()])
    table(folder/'采集来源.csv',['来源','帖子数'],[{'来源':k,'帖子数':v} for k,v in frames.items()])
    table(folder/'重复主题候选.csv',['模型主题原词','帖子数','帖子ID','性质'],[{'模型主题原词':k,'帖子数':len(v),'帖子ID':' | '.join(v),'性质':'相近主题合并与事件去重由人工完成'} for k,v in sorted(topics.items(),key=lambda item:-len(item[1]))])
    table(folder/'可见评论复核.csv',['post_id','order_in_saved_record','text','displayed_time_label','captured_at','scope'],comments)
    table(folder/'截图映射.csv',['post_id','scope','relative_path','bytes','info_json'],[r for r in shots if r['post_id'] in ids])
    chart(folder/'人工类别图.svg','人工复核帖子的主类别',dict(human.most_common()),f'分母为完成人工分类的 {sum(human.values())} 帖；抽样范围见版本说明。')
    chart(folder/'模型候选类别图.svg','本地模型给出的候选类别',dict(model.most_common()),f'模型已处理 {sum(model.values())} 帖；人工复核情况单独记录。')
    for path in folder.iterdir():
        if path.is_file():files[path.name]={'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest={'created_at':now(),'source_database':str(library.db),'snapshot_database':snapshot.name,'stages':stages,'analysis_stage':'正式','frame_posts':count,'sorted_post_ids_sha256':hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest(),'coverage':coverage,'model_human_agreement_counts':dict(agreement),'capture_runs':runs,'files':files,'scope':'实际页面取得并按帖子ID去重的观察材料；平台呈现顺序与实际入口见运行记录。','images':'图片、头像、截图沿用资料库原目录，映射按文件名查找。'}
    (folder/'采集版本说明.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    notes=f'''# 本次分析版本

导出时间：{manifest['created_at']}

正式材料共 {count} 个去重帖子，人工分类 {sum(human.values())} 帖，本地模型候选 {sum(model.values())} 帖。

## 文件用途

- 帖子分析表.csv：正文、时间及精度、评论覆盖、截图路径、模型候选与人工结果，适合 Excel 筛选。
- 正式帖子.jsonl、资料快照.sqlite3：本次固定资料，供复现分析。头像和原图沿用资料库现有目录。
- 材料覆盖.csv、入口覆盖.csv、时间精度.csv：用于报告的方法与材料说明。
- 人工复核类别.csv、人工类别图.svg：使用已完成人工判断的实际分母。抽样方案与抽样ID配套保留。
- 模型候选类别.csv、模型候选类别图.svg：呈现机器初筛范围，名称中保留“候选”。
- 重复主题候选.csv：按模型主题原词汇总；人工合并近义词，核对帖子ID和实际事件后形成研究发现。
- 可见评论复核.csv：逐帖查看已取得的回应内容，结合主帖及求助者后续说明判断具体帮助。
- 截图映射.csv：查找原样证据，覆盖比例与裁剪方式保存在info_json中。

## 写作口径

帖子数表示发帖内容，问卷人数表示本次作答者，访谈人数表示实际受访者。分类图说明本次材料的内容分布。关于信息查找体验、帮助效果和具体建议，使用访谈、讨论过程观察和问卷共同说明。发布时间按页面明示日期及相对时间估计分别记录。头像用于本机核对，展示截图先遮盖个人信息。

模型与人工一致情况以采集版本说明.json中的实际核对数为准，抽样复核按固定资料开展。采集仍在进行时，版本说明记录本次导出时点；结题前再保存一次最终分析版本。
'''
    (folder/'文件说明.md').write_text(notes,encoding='utf-8')
    return {'ok':True,'folder':str(folder),'formal_posts':count,'manual_posts':sum(human.values()),'model_posts':sum(model.values()),'message':'分析版本已写入资料库的分析导出目录。'}


if __name__=='__main__':
    from research_library import Library
    print(json.dumps(build_exports(Library()),ensure_ascii=False,indent=2))
