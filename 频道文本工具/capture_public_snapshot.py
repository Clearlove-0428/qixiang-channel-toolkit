"""整理本地网页快照；可单次试读启翔湖畔公开热门页。

网络试读仅请求一页。若网页返回验证页面，保存原始响应并停止。
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse
import hashlib
import json
from urllib.request import Request, urlopen

from parse_public_page import parse_html, to_analysis_document


URL = "https://pd.qq.com/g/npu0lakeside?tab=1&subc=hot"
MAX_BYTES = 2 * 1024 * 1024
CHINA_TIME = timezone(timedelta(hours=8))


def capture(output_dir: Path, local_html: Path | None = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    if local_html:
        raw = local_html.read_bytes()
    else:
        request = Request(URL, headers={
            "User-Agent": "CampusCourseResearch/1.0 (one public page snapshot)",
            "Accept": "text/html",
        })
        with urlopen(request, timeout=25) as response:
            if response.status != 200:
                raise RuntimeError(f"网页返回状态 {response.status}")
            if "text/html" not in response.headers.get("Content-Type", ""):
                raise RuntimeError("页面返回了非 HTML 内容")
            if response.url.split("/")[2] != "pd.qq.com":
                raise RuntimeError("页面跳转到了其他域名")
            raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RuntimeError("网页超过 2 MiB；停止保存")
    captured_at = datetime.now(CHINA_TIME).isoformat()
    parsed = parse_html(raw.decode("utf-8-sig"), URL, hashlib.sha256(raw).hexdigest())
    normalized = to_analysis_document(parsed, captured_at)
    stamp = datetime.now(CHINA_TIME).strftime("%Y%m%dT%H%M%S%f")
    stem = f"公开热门页快照_{stamp}"
    html_path = output_dir / f"{stem}.html"
    parsed_path = output_dir / f"{stem}_解析.json"
    input_path = output_dir / f"{stem}_分析输入.json"
    html_path.write_bytes(raw)
    if not normalized["posts"]:
        return {"capture_time": captured_at, "visible_posts": 0,
                "saved_html": str(html_path.resolve()), "html_bytes": len(raw),
                "status": "页面没有帖子卡片，可能是验证页；已保存响应并停止，请勿自动重试"}
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    input_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"capture_time": captured_at, "visible_posts": len(normalized["posts"]),
            "analysis_input": str(input_path.resolve()), "saved_html": str(html_path.resolve()),
            "method": "本地保存的公开热门页快照" if local_html else "公开热门页一次网络试读",
            "coverage": "本页实际展示的卡片；时间段全量覆盖未验证"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "采集快照")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--html", type=Path, help="已保存的公开网页 HTML；全程离线")
    group.add_argument("--try-public-once", action="store_true", help="试读一页公开热门页；遇验证页即停止")
    args = ap.parse_args()
    print(json.dumps(capture(args.output_dir, args.html), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
