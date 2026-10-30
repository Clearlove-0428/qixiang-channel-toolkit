#!/usr/bin/env python3
"""Save already-observed post images from a browser export, without QQ credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                 "image/gif": ".gif", "image/avif": ".avif"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return parts.scheme == "https" and parts.port in (None, 443) and (
            host == "qpic.cn" or host.endswith(".qpic.cn")) and len(url) <= 4096
    except ValueError:
        return False


def candidates(data: dict, limit: int) -> list[tuple[str, str]]:
    posts = data.get("posts", [])
    if not isinstance(posts, list):
        raise ValueError("输入文件缺少 posts 数组。")
    result, seen = [], set()
    for post in posts:
        if not isinstance(post, dict):
            continue
        for image in post.get("images", [])[:12]:
            if not isinstance(image, dict):
                continue
            url = image.get("url")
            if not isinstance(url, str) or not allowed(url) or url in seen:
                continue
            seen.add(url)
            result.append((str(post.get("id", "")), url))
            if len(result) >= limit:
                return result
    return result


def save(source: Path, folder: Path, max_images: int, max_file_bytes: int,
         max_total_bytes: int, delay: float) -> dict:
    from media_store import store_image
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("请输入浏览器导出的 JSON 对象。")
    folder.mkdir(parents=True, exist_ok=True)
    opener = build_opener(NoRedirect())
    entries, total = [], 0
    for post_id, url in candidates(data, max_images):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        entry = {"post_id": post_id, "source_url": url, "saved_file": None, "status": "skipped"}
        if total + 1_000_000 > max_total_bytes:
            entry["status"] = "total_limit_reached"
            entries.append(entry)
            break
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 (local research image archive)"})
            with opener.open(request, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                extension = ALLOWED_TYPES.get(content_type)
                content_length = response.headers.get("Content-Length", "")
                if not extension:
                    entry["status"] = "unsupported_content_type"
                elif content_length.isdigit() and int(content_length) > 16 * 1024 * 1024:
                    entry["status"] = "file_too_large"
                else:
                    chunks, size = [], 0
                    while True:
                        chunk = response.read(min(64 * 1024, 16 * 1024 * 1024 - size + 1))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 16 * 1024 * 1024:
                            entry["status"] = "size_limit_reached"
                            break
                        chunks.append(chunk)
                    if entry["status"] == "skipped":
                        info = store_image(b"".join(chunks), folder)
                        if total + info['bytes'] > max_total_bytes:
                            entry['status'] = 'total_limit_reached'
                        else:
                            total += info['bytes']
                            entry.update(saved_file=info['relative_path'], status="saved", bytes=info['bytes'],
                                         content_type='image/jpeg', compression=info)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            entry["status"] = "request_failed"
            entry["error_type"] = type(error).__name__
        entries.append(entry)
        if delay:
            time.sleep(delay)
    result = {"source_file": source.name, "attempted": len(entries),
              "saved": sum(entry["status"] == "saved" for entry in entries),
              "saved_bytes": total, "entries": entries,
              "note": "仅下载导出文件中已观察到的 qpic.cn 图片地址；不发送 QQ 凭据，不访问帖子接口。"}
    (folder / "image_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="把频道页面已观察到的图片地址保存为本地文件。")
    parser.add_argument("input", type=Path, help="浏览器扩展导出的 JSON 文件")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-images", type=int, default=30)
    parser.add_argument("--max-file-mb", type=int, default=8)
    parser.add_argument("--max-total-mb", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()
    result = save(args.input, args.output_dir, max(1, min(args.max_images, 200)),
                  max(1, args.max_file_mb) * 1024 * 1024,
                  max(1, args.max_total_mb) * 1024 * 1024,
                  max(0.0, args.delay))
    print(json.dumps({key: result[key] for key in ("attempted", "saved", "saved_bytes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
