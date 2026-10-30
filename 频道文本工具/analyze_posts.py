#!/usr/bin/env python3
"""Offline, standard-library-only snapshot analysis of supplied channel posts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APPLICATION_ID = 0x51585458
VERSION = "1.1"
CATEGORY_RULES = {
    "求助或咨询候选": ("求助", "请问", "有没有人", "怎么办", "想问", "求推荐", "求问"),
    "校园办事候选": ("教务", "选课", "补考", "校园卡", "学籍", "奖学金", "报销", "图书馆", "办事"),
    "学习经验候选": ("学习", "复习", "考试", "课程", "作业", "考研", "保研", "竞赛", "论文"),
    "生活服务候选": ("食堂", "宿舍", "快递", "校车", "维修", "失物", "招领", "二手", "租房"),
    "休闲交流候选": ("闲聊", "游戏", "电影", "音乐", "摄影", "运动", "跑步", "旅行"),
    "信息核实候选": ("来源", "核实", "辟谣", "原文", "官方通知", "更正", "确认消息"),
}
POST_FIELDS = [
    "record_key", "id", "title", "text", "created_at_raw", "created_at_iso",
    "date_status", "date_timezone_status", "comment_count", "comment_count_status",
    "comment_count_basis", "comment_count_as_of", "url", "board", "candidate_labels",
    "matched_keywords", "image_count", "images_json", "visible_comment_count",
    "visible_comments_json", "duplicate_records", "duplicate_conflicts",
]
REVIEW_FIELDS = POST_FIELDS + ["reviewed_labels", "review_notes", "reviewer_code"]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def parse_date(value: Any) -> tuple[str, str, str]:
    raw = as_text(value).strip()
    if not raw:
        return "", "missing", "not_applicable"
    try:
        if isinstance(value, bool):
            raise ValueError("boolean date")
        if re.fullmatch(r"\d{10}|\d{13}", raw):
            seconds = int(raw) / (1000 if len(raw) == 13 else 1)
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            normalized = raw.replace("/", "-")
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            dt = datetime.fromisoformat(normalized)
        return dt.isoformat(), "parsed", "explicit" if dt.tzinfo else "unspecified"
    except (ValueError, OverflowError, OSError):
        return "", "invalid", "not_applicable"


def parse_count(value: Any) -> tuple[int | None, str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    if isinstance(value, bool):
        return None, "invalid"
    raw = as_text(value).strip()
    if isinstance(value, float) and value.is_integer():
        raw = str(int(value))
    if not re.fullmatch(r"\d+", raw):
        return None, "invalid"
    number = int(raw)
    if number > 2**63 - 1:
        return None, "invalid"
    return number, "known_zero" if number == 0 else "known_positive"


def csv_safe(value: Any) -> Any:
    """Prevent spreadsheet formulas, including those hidden behind whitespace."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def classify(title: str, text: str) -> tuple[str, str]:
    corpus = title + "\n" + text
    matches = {label: [word for word in words if word in corpus]
               for label, words in CATEGORY_RULES.items()}
    matches = {key: words for key, words in matches.items() if words}
    return "；".join(matches), json.dumps(matches, ensure_ascii=False)


def content_images(value: Any) -> list[dict[str, Any]]:
    """Keep only HTTPS addresses of images already observed in a post DOM."""
    if not isinstance(value, list):
        return []
    images, seen = [], set()
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        url = as_text(item.get("url")).strip()
        try:
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.netloc or len(url) > 4096 or url in seen:
                continue
        except ValueError:
            continue
        seen.add(url)
        images.append({"url": url, "width": item.get("width"), "height": item.get("height")})
    return images


def rendered_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    comments, seen = [], set()
    for item in value[:30]:
        if not isinstance(item, dict):
            continue
        text = as_text(item.get("text")).strip()[:1200]
        label = as_text(item.get("displayed_time_label")).strip()[:80]
        if not text or (text, label) in seen:
            continue
        seen.add((text, label))
        comments.append({"text": text, "displayed_time_label": label or None})
    return comments


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    fields = {key: as_text(raw.get(key)).strip() for key in ("id", "title", "text", "url", "board")}
    date_iso, date_status, date_zone = parse_date(raw.get("created_at"))
    count, count_status = parse_count(raw.get("comment_count"))
    if fields["id"]:
        key = "id:" + fields["id"]
    elif fields["url"]:
        key = "url:" + hashlib.sha256(fields["url"].encode("utf-8")).hexdigest()
    else:
        identity = [fields[k] for k in ("title", "text", "board")] + [as_text(raw.get("created_at"))]
        key = "content:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    basis = as_text(raw.get("comment_count_basis") or raw.get("comment_count_type")).strip()
    images = content_images(raw.get("images"))
    comments = rendered_comments(raw.get("visible_comments"))
    result = dict(fields, record_key=key, created_at_raw=as_text(raw.get("created_at")),
                  created_at_iso=date_iso, date_status=date_status, date_timezone_status=date_zone,
                  comment_count=count, comment_count_status=count_status,
                  comment_count_basis=basis or "source_snapshot_unverified",
                  comment_count_as_of=as_text(raw.get("comment_count_as_of")),
                  image_count=len(images), images_json=json.dumps(images, ensure_ascii=False),
                  visible_comment_count=len(comments),
                  visible_comments_json=json.dumps(comments, ensure_ascii=False),
                  duplicate_records=0, duplicate_conflicts="")
    result["candidate_labels"], result["matched_keywords"] = classify(fields["title"], fields["text"])
    return result


def deduplicate(raw_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep first observation; fill missing fields from later duplicates, flag conflicts."""
    unique: dict[str, dict[str, Any]] = {}
    for raw in raw_posts:
        post = normalize(raw)
        key = post["record_key"]
        if key not in unique:
            unique[key] = post
            continue
        kept = unique[key]
        kept["duplicate_records"] += 1
        conflicts = set(filter(None, kept["duplicate_conflicts"].split("；")))
        for field in ("title", "text", "url", "board"):
            if kept[field] and post[field] and kept[field] != post[field]:
                conflicts.add(field)
            if not kept[field]:
                kept[field] = post[field]
        if kept["date_status"] != "parsed" and post["date_status"] == "parsed":
            for field in ("created_at_raw", "created_at_iso", "date_status", "date_timezone_status"):
                kept[field] = post[field]
        elif kept["date_status"] == post["date_status"] == "parsed" and kept["created_at_iso"] != post["created_at_iso"]:
            conflicts.add("created_at")
        if kept["comment_count"] is None and post["comment_count"] is not None:
            for field in ("comment_count", "comment_count_status", "comment_count_basis", "comment_count_as_of"):
                kept[field] = post[field]
        elif kept["comment_count"] is not None and post["comment_count"] is not None and kept["comment_count"] != post["comment_count"]:
            conflicts.add("comment_count")
        images = {item["url"]: item for item in json.loads(kept["images_json"])}
        images.update({item["url"]: item for item in json.loads(post["images_json"])})
        kept["images_json"] = json.dumps(list(images.values())[:12], ensure_ascii=False)
        kept["image_count"] = min(len(images), 12)
        comments = {(item["text"], item["displayed_time_label"]): item
                    for item in json.loads(kept["visible_comments_json"])}
        comments.update({(item["text"], item["displayed_time_label"]): item
                         for item in json.loads(post["visible_comments_json"])})
        kept["visible_comments_json"] = json.dumps(list(comments.values())[:30], ensure_ascii=False)
        kept["visible_comment_count"] = min(len(comments), 30)
        kept["duplicate_conflicts"] = "；".join(sorted(conflicts))
        kept["candidate_labels"], kept["matched_keywords"] = classify(kept["title"], kept["text"])
    return list(unique.values())


def read_input(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    posts = data.get("posts") if isinstance(data, dict) else data
    if not isinstance(posts, list):
        raise ValueError("输入须为JSON数组，或包含posts数组的JSON对象。")
    if any(not isinstance(p, dict) for p in posts):
        raise ValueError("posts中的每一项都须为对象。")
    # Copy only relevant collection metadata, never credentials or author profiles.
    metadata = {k: data[k] for k in ("source", "captured_at", "window_start", "window_end", "scope", "truncated") if isinstance(data, dict) and k in data}
    return posts, metadata


def write_csv(path: Path, posts: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for post in posts:
            writer.writerow({field: csv_safe(post.get(field, "")) for field in fields})


def make_summary(raw_count: int, posts: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    category_counts = {label: sum(label in post["candidate_labels"].split("；") for post in posts) for label in CATEGORY_RULES}
    count_status = Counter(post["comment_count_status"] for post in posts)
    date_status = Counter(post["date_status"] for post in posts)
    by_basis: dict[str, Counter] = {}
    for post in posts:
        by_basis.setdefault(post["comment_count_basis"], Counter())[post["comment_count_status"]] += 1
    return {
        "tool_version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "仅分析本次输入文件中的去重帖子；类别为词表候选，等待人工复核。",
        "source_metadata": metadata,
        "input_records": raw_count,
        "unique_posts": len(posts),
        "duplicate_records": raw_count - len(posts),
        "posts_with_duplicate_conflicts": sum(bool(p["duplicate_conflicts"]) for p in posts),
        "missing_id_posts": sum(not p["id"] for p in posts),
        "empty_content_posts": sum(not p["title"] and not p["text"] for p in posts),
        "posts_with_images": sum(p["image_count"] > 0 for p in posts),
        "observed_image_addresses": sum(p["image_count"] for p in posts),
        "posts_with_rendered_comments": sum(p["visible_comment_count"] > 0 for p in posts),
        "rendered_comment_texts": sum(p["visible_comment_count"] for p in posts),
        "media_note": "图片字段是采集时页面呈现的 HTTPS 地址及显示尺寸，原图文件未自动下载；评论正文仅为详情页当时呈现的部分，不能等同于全部评论。",
        "date_quality": {key: date_status[key] for key in ("parsed", "missing", "invalid")},
        "dates_with_unspecified_timezone": sum(p["date_timezone_status"] == "unspecified" for p in posts),
        "comment_count_quality": {key: count_status[key] for key in ("known_zero", "known_positive", "missing", "invalid")},
        "comment_count_by_source_basis": {basis: {key: counter[key] for key in ("known_zero", "known_positive", "missing", "invalid")} for basis, counter in by_basis.items()},
        "comment_count_note": "评论数为源文件携带的快照值。来源声明的实时性仅照录，工具未在线核验；空值、格式异常与明确0分别统计。该字段不能证明问题得到解决。",
        "candidate_category_counts": category_counts,
        "posts_without_keyword_match": sum(not p["candidate_labels"] for p in posts),
        "category_note": "词表按字面匹配，同一帖子可有多个候选；命中只提示人工查看，未命中也可能属于某类。人工复核结果由使用者另行整理，本脚本尚未纳入。",
        "deduplication_note": "依次使用id、url、内容指纹去重；保留首条信息，用后续重复记录补充缺失或解析异常字段；冲突单列，评论数冲突时保留首个有效值。",
        "date_note": "ISO日期及10/13位Unix时间戳可解析；时区缺失保留未指定状态。日期缺失和解析失败分别统计；采集窗口依据原始采集记录核对。",
        "inference_limits": "本工具仅整理内容候选和数据质量，未推断解决情况、情绪、态度、个体身份或频道总体特征。",
        "board_counts": dict(Counter(p["board"] or "（版块字段缺失）" for p in posts)),
        "csv_note": "CSV采用UTF-8 BOM；可能触发表格公式的文本加前导单引号。SQLite保存原文。",
    }


def write_database(path: Path, posts: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if path.exists():
        with closing(sqlite3.connect(path)) as old:
            if old.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError(f"目标数据库属于其他来源，请改用新的输出目录：{path}")
    handle, temp_name = tempfile.mkstemp(prefix=".posts-", suffix=".sqlite3", dir=path.parent)
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        with closing(sqlite3.connect(temp_path)) as connection, connection:
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            definitions = [f'"{field}" {"INTEGER" if field in ("comment_count", "image_count", "visible_comment_count", "duplicate_records") else "TEXT"}' for field in POST_FIELDS]
            definitions[0] += " PRIMARY KEY"
            connection.execute("CREATE TABLE posts (" + ",".join(definitions) + ")")
            connection.executemany("INSERT INTO posts VALUES (" + ",".join("?" for _ in POST_FIELDS) + ")", [[post[field] for field in POST_FIELDS] for post in posts])
            connection.execute("CREATE TABLE analysis_metadata (key TEXT PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO analysis_metadata VALUES (?,?)", [(key, json.dumps(value, ensure_ascii=False)) for key, value in summary.items()])
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_html(path: Path, posts: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    escape = lambda value: html.escape(as_text(value), quote=True)
    def rows(mapping: dict[str, Any]) -> str:
        return "".join(f"<tr><td>{escape(key)}</td><td>{escape(value)}</td></tr>" for key, value in mapping.items())
    quality = {
        "输入记录": summary["input_records"], "去重帖子": summary["unique_posts"],
        "合并的重复记录": summary["duplicate_records"], "重复字段冲突帖子": summary["posts_with_duplicate_conflicts"],
        "日期成功解析": summary["date_quality"]["parsed"], "日期缺失": summary["date_quality"]["missing"],
        "日期解析失败": summary["date_quality"]["invalid"], "日期时区待核对": summary["dates_with_unspecified_timezone"],
        "明确0条评论": summary["comment_count_quality"]["known_zero"],
        "评论数大于0": summary["comment_count_quality"]["known_positive"],
        "评论数字段缺失": summary["comment_count_quality"]["missing"],
        "评论数格式异常": summary["comment_count_quality"]["invalid"],
        "有图片地址的帖子": summary["posts_with_images"],
        "页面图片地址": summary["observed_image_addresses"],
        "有已呈现评论的帖子": summary["posts_with_rendered_comments"],
        "已呈现评论文字": summary["rendered_comment_texts"],
        "标题和正文均为空": summary["empty_content_posts"],
        "词表未命中的帖子": summary["posts_without_keyword_match"],
    }
    examples = []
    for post in posts[:30]:
        target = post["url"]
        try:
            safe_link = urlsplit(target).scheme in ("https", "http") and bool(urlsplit(target).netloc)
        except ValueError:
            safe_link = False
        link = f'<a href="{escape(target)}" rel="noreferrer noopener">原帖定位</a>' if safe_link else "定位链接待核对"
        examples.append(f'<tr><td>{escape(post["id"] or post["record_key"][:24])}</td><td>{escape(post["title"])}<p>{escape(post["text"][:200])}</p></td><td>{escape(post["candidate_labels"] or "待人工分类")}</td><td>{link}</td></tr>')
    rendered = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>频道文本质量摘要与待核对分类</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;max-width:1060px;margin:30px auto;padding:0 22px;color:#243241;line-height:1.65}}h1{{font-size:26px}}h2{{margin-top:32px;font-size:20px}}.note{{background:#eef4f8;padding:14px 18px;border-left:4px solid #377695}}table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border:1px solid #d2dbe2;padding:8px 12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#edf2f6}}td p{{font-size:14px;color:#54616d;white-space:pre-wrap}}a{{color:#23678e}}.small{{font-size:13px;color:#5f6d78}}</style></head><body>
<h1>频道文本质量摘要与待核对分类</h1>
<p class="note">本页说明输入资料质量和词表分类候选。实际报告请使用人工复核后的分类与案例。统计范围为本次输入文件中的去重帖子。</p>
<p class="small">生成时间（UTC）：{escape(summary['generated_at'])} · 离线工具 {VERSION}</p>
<h2>资料质量</h2><table><tr><th>项目</th><th>数量</th></tr>{rows(quality)}</table>
<p>{escape(summary['comment_count_note'])}</p><p>{escape(summary['date_note'])}</p><p>{escape(summary['media_note'])}</p>
<h2>评论数字段的来源标注</h2><pre>{escape(json.dumps(summary['comment_count_by_source_basis'], ensure_ascii=False, indent=2))}</pre>
<h2>类别候选数量</h2><p>{escape(summary['category_note'])}</p><table><tr><th>候选类别</th><th>命中帖子数</th></tr>{rows(summary['candidate_category_counts'])}</table>
<h2>版块字段分布</h2><table><tr><th>源文件中的版块</th><th>帖子数</th></tr>{rows(summary['board_counts'])}</table>
<h2>先核对这些内容</h2><p>以下按输入顺序展示前30条，便于检查解析效果。全部记录在 posts.csv，逐条复核填写 {escape(summary['human_review_file'])}。</p>
<table><tr><th>帖子编号</th><th>标题与正文节选</th><th>候选标签</th><th>定位</th></tr>{''.join(examples)}</table>
<h2>整理口径</h2><p>{escape(summary['deduplication_note'])}</p><p>{escape(summary['inference_limits'])}</p><p>{escape(summary['csv_note'])}</p>
</body></html>'''
    path.write_text(rendered, encoding="utf-8")


def analyze(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_posts, metadata = read_input(input_path)
    posts = deduplicate(raw_posts)
    summary = make_summary(len(raw_posts), posts, metadata)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Retain work by previous reviewers when rerunning the same output directory.
    review_path = output_dir / "human_review.csv"
    if review_path.exists():
        review_path = output_dir / ("human_review_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".csv")
    summary["human_review_file"] = review_path.name
    write_database(output_dir / "posts.sqlite3", posts, summary)
    write_csv(output_dir / "posts.csv", posts, POST_FIELDS)
    write_csv(review_path, posts, REVIEW_FIELDS)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(output_dir / "quality_report.html", posts, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="离线整理频道帖子，输出SQLite、CSV、人工复核表与HTML质量摘要。")
    parser.add_argument("input", type=Path, help="JSON数组或含posts数组的JSON文件")
    parser.add_argument("--output-dir", type=Path, help="输出目录；默认在输入文件旁创建“文件名_分析”")
    args = parser.parse_args()
    output_dir = args.output_dir or args.input.parent / (args.input.stem + "_分析")
    try:
        summary = analyze(args.input, output_dir)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output_dir": str(output_dir.resolve()), "input_records": summary["input_records"],
                      "unique_posts": summary["unique_posts"], "duplicate_records": summary["duplicate_records"],
                      "date_quality": summary["date_quality"], "comment_count_quality": summary["comment_count_quality"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
