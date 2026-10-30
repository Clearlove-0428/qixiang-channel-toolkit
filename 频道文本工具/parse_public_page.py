"""Parse an already-saved public Tencent channel page; performs no network I/O.

Usage: py -X utf8 parse_public_page.py public-channel.html -o public-posts.json
Only post cards present in the DOM enter the output sample. Page-embedded Nuxt
metadata is matched by that card's post ID and is explicitly separated from DOM.
Author account identifiers, avatars, profile data and session fields are excluded.
"""
import argparse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse


VOID = set("area base br col embed hr img input link meta param source track wbr".split())
WRAPPERS = {"Ref", "ShallowRef", "Reactive", "ShallowReactive", "EmptyRef"}


class Node:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []

    def has_class(self, name):
        return name in (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in {"script", "style", "svg"}:
            return ""
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(s):
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


def redact_contact_details(text):
    """Minimal contact masking; does not claim full anonymization of prose."""
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系方式]", text or "")
    text = re.sub(r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", "[联系方式]", text)
    # Require an explicit QQ label; ordinary counts and unrelated IDs remain.
    text = re.sub(r"(?i)(?<![A-Za-z])QQ\s*(?:号码|号|群号|群)?\s*[:：=]?\s*[1-9]\d{4,11}(?!\d)", "[联系方式]", text)
    return text


def first_class(node, name):
    return next((n for n in node.walk() if n.has_class(name)), None)


def class_text(node, name):
    found = first_class(node, name)
    return clean(found.text()) if found else None


def count_value(text):
    if text and re.fullmatch(r"[\d,]+", text):
        return int(text.replace(",", ""))
    # Preserve abbreviated/empty labels without inventing exact counts.
    return None


def unpack(pool, reference, depth=0):
    """Resolve only selected Nuxt values, never execute JavaScript."""
    if depth > 80:
        raise ValueError("Nuxt value nesting exceeds parser bound")
    if not isinstance(reference, int) or reference < 0 or reference >= len(pool):
        return None
    obj = pool[reference]
    if isinstance(obj, dict):
        return {k: unpack(pool, v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if obj and isinstance(obj[0], str) and obj[0] in WRAPPERS:
            return unpack(pool, obj[1], depth + 1) if len(obj) > 1 else None
        return [unpack(pool, v, depth + 1) for v in obj]
    return obj


def rich_text(obj):
    """Read literal text/emoji strings only; skip mention/account metadata."""
    if not isinstance(obj, dict):
        return ""
    pieces = []
    for item in obj.get("contents") or []:
        if not isinstance(item, dict):
            continue
        tc = item.get("text_content") or {}
        if isinstance(tc, dict) and isinstance(tc.get("text"), str):
            pieces.append(tc["text"])
        ec = item.get("emoji_content") or {}
        if isinstance(ec, dict):
            value = ec.get("emoji_desc") or ec.get("text")
            if isinstance(value, str):
                pieces.append(value)
    if not pieces and isinstance(obj.get("source_markdown"), str):
        pieces.append(obj["source_markdown"])
    return "".join(pieces).strip()


def parse_html(html, source_url, html_sha256):
    parser = PageParser()
    parser.feed(html)
    root = parser.root
    canonical = next((n.attrs.get("href") for n in root.walk() if n.tag == "link"
                      and n.attrs.get("rel") == "canonical"), None)
    source_url = source_url or canonical or ""
    is_detail = bool(first_class(root, "feed-content") and "/post/" in source_url)
    cards = [n for n in root.walk() if n.tag == "a"
             and n.has_class("game-guild-main__short-content")
             and "/post/" in (n.attrs.get("href") or "")]
    posts = []
    for card in cards:
        url = card.attrs["href"]
        post_id = urlparse(url).path.rstrip("/").split("/")[-1]
        fragments = [redact_contact_details(clean(n.text())) for n in card.walk()
                     if n.has_class("feed-detail-text") and clean(n.text())]
        counts = {}
        for label in ("like", "comment", "share"):
            text = class_text(card, f"game-guild-main__short-content__{label}")
            counts[label] = {"displayed": text, "exact_if_integer": count_value(text)}
        posts.append({"post_id": post_id, "detail_url": url,
                      "page_kind": "list_preview",
                      "visible_dom": {"date_label": class_text(card, "edit-time"),
                                      "text_fragments": fragments,
                                      "text": "\n".join(fragments),
                                      "counts": counts,
                                      "preview_completeness": "unknown_from_card_alone"},
                      "page_embedded_data": None})

    # Detail pages expose a dedicated full-content container. This describes
    # saved HTML text, not image/video text or comments loaded at a later time.
    if is_detail:
        content_node = first_class(root, "feed-content")
        fragments = [redact_contact_details(clean(n.text())) for n in content_node.walk()
                     if n.has_class("feed-detail-text") and clean(n.text())]
        operations = first_class(root, "bottom-right") or root
        like_text = class_text(operations, "like-text")
        operation_comments = [clean(n.text()) for n in operations.walk() if n.has_class("comment-text")]
        comment_text = operation_comments[0] if operation_comments else None
        share_text = operation_comments[1] if len(operation_comments) > 1 else None
        read_text = class_text(root, "feed-info__detail__read-count")
        posts = [{
            "post_id": urlparse(source_url).path.rstrip("/").split("/")[-1],
            "detail_url": canonical or source_url,
            "page_kind": "detail_page",
            "visible_dom": {
                "date_label": class_text(root, "feed-info__detail__time"),
                "text_fragments": fragments,
                "text": "\n".join(fragments),
                "counts": {label: {"displayed": value, "exact_if_integer": count_value(value)}
                           for label, value in [("like", like_text), ("comment", comment_text), ("share", share_text)]},
                "read_count_label": read_text,
                "read_count": count_value(re.sub(r"^浏览", "", read_text or "")),
                "preview_completeness": "detail_content_container; media_text_and_later_dynamic_content_unverified",
            },
            "page_embedded_data": None,
        }]

    scripts = [n for n in root.walk() if n.tag == "script"
               and n.attrs.get("id") == "__NUXT_DATA__"]
    pool = []
    errors = []
    if scripts:
        try:
            pool = json.loads("".join(c for c in scripts[0].children if isinstance(c, str)))
            if not isinstance(pool, list):
                raise ValueError("Unexpected Nuxt payload type")
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))
            pool = []

    visible_by_id = {p["post_id"]: p for p in posts}
    embedded_feed_lists = []
    finish_flags = []
    comment_state = None
    for obj in pool:
        if not isinstance(obj, dict):
            continue
        if {"rankingType", "commentList", "commentCount"}.issubset(obj):
            comments = unpack(pool, obj["commentList"])
            comment_state = {
                "rankingType_raw": unpack(pool, obj["rankingType"]),
                "ranking_label": None,
                "commentList_items": len(comments) if isinstance(comments, list) else None,
                "store_commentCount_raw": unpack(pool, obj["commentCount"]),
                "state_interpretation": "client_store_snapshot; zero_may_be_initial_state",
            }
        if "vecFeed" in obj:
            raw_list = pool[obj["vecFeed"]]
            if isinstance(raw_list, list):
                embedded_feed_lists.append(len(raw_list))
        if "isFinish" in obj and ("items" in obj or "vecFeed" in obj):
            finish_flags.append(unpack(pool, obj["isFinish"]))
        if not {"id", "createTime", "contents", "commentCount"}.issubset(obj):
            continue
        post_id = unpack(pool, obj["id"])
        if post_id not in visible_by_id:
            continue
        raw_time = unpack(pool, obj["createTime"])
        iso_time = None
        try:
            iso_time = datetime.fromtimestamp(int(raw_time), timezone(timedelta(hours=8))).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            pass
        title = redact_contact_details(rich_text(unpack(pool, obj["title"]))) if "title" in obj else ""
        content = redact_contact_details(rich_text(unpack(pool, obj["contents"])))
        channel = unpack(pool, obj["channelInfo"]) if "channelInfo" in obj else {}
        def array_length(key):
            value = pool[obj[key]] if key in obj else None
            return len(value) if isinstance(value, list) else None
        visible_by_id[post_id]["page_embedded_data"] = {
            "source": "__NUXT_DATA__",
            "createTime_raw": raw_time,
            "published_at_utc8": iso_time,
            "title_text": title,
            "body_text": content,
            "text_scope": "text_strings_embedded_in_saved_list_page; full_post_completeness_unverified",
            "board_name": channel.get("name") if isinstance(channel, dict) else None,
            "comment_count": unpack(pool, obj["commentCount"]),
            "embedded_comment_items": array_length("vecComment"),
            "embedded_external_comment_items": array_length("external_comment_list"),
        }

    duplicate_count = len(posts) - len(visible_by_id)
    posts = list(visible_by_id.values())
    date_values = [p["page_embedded_data"]["published_at_utc8"] for p in posts
                   if p["page_embedded_data"] and p["page_embedded_data"]["published_at_utc8"]]
    embedded_chars = sum(len(p["page_embedded_data"]["body_text"]) for p in posts if p["page_embedded_data"])
    summary = {
        "post_cards": len(cards), "unique_visible_posts": len(posts),
        "duplicate_card_count": duplicate_count,
        "with_stable_id_and_detail_link": len(posts),
        "with_visible_text": sum(bool(p["visible_dom"]["text"]) for p in posts),
        "visible_text_chars": sum(len(p["visible_dom"]["text"]) for p in posts),
        "with_original_timestamp": len(date_values),
        "earliest_publication_utc8": min(date_values) if date_values else None,
        "latest_publication_utc8": max(date_values) if date_values else None,
        "embedded_body_text_chars": embedded_chars,
        "embedded_vecFeed_lengths": embedded_feed_lists,
        "page_isFinish_flags_raw": finish_flags,
        "embedded_comment_items": sum((p["page_embedded_data"]["embedded_comment_items"] or 0)
                                      for p in posts if p["page_embedded_data"]),
        "server_rendered_marker": bool(scripts and scripts[0].attrs.get("data-ssr") == "true"),
        "detail_page": is_detail,
        "errors": errors,
    }
    return {
        "source": {"url": source_url, "html_sha256": html_sha256,
                   "mode": "offline_saved_public_html", "network_requests_by_parser": 0},
        "summary": summary,
        "coverage": {
            "scope": "saved detail main post" if is_detail else "post cards present in this saved page",
            "sort_or_tab": "hot" if "subc=hot" in source_url else "unknown",
            "all_posts_in_time_window_proven": False,
            "comment_text_coverage": "page-embedded comment arrays only; actual detail pages untested",
            "card_text_may_be_excerpt": not is_detail,
            "personal_profile_fields_exported": False,
        },
        "comment_observation": {
            "client_state": comment_state,
            "comment_body_status": "absent_in_saved_payload" if comment_state and comment_state["commentList_items"] == 0 else "not_verified",
            "reply_body_status": "absent_in_saved_payload" if comment_state and comment_state["commentList_items"] == 0 else "not_verified",
            "sort_label_status": "not_visible_in_saved_page",
            "counts_are_snapshot_values": True,
        },
        "posts": posts,
    }


def to_analysis_document(parsed, captured_at=None):
    """Normalize to analyze_posts.py schema; missing date precision stays missing."""
    posts = []
    for post in parsed["posts"]:
        dom = post["visible_dom"]
        embedded = post["page_embedded_data"] or {}
        timestamp = embedded.get("published_at_utc8")
        date_label = dom.get("date_label") or ""
        # Only the full YYYY-MM-DD label can stand on its own; MM-DD is kept
        # separately so the year is never guessed from collection date.
        verified_date = date_label if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_label) else None
        counts = dom.get("counts", {})
        posts.append({
            "id": post["post_id"],
            "title": redact_contact_details(embedded.get("title_text") or ""),
            "text": redact_contact_details(dom.get("text") or ""),
            "created_at": timestamp or verified_date,
            "comment_count": counts.get("comment", {}).get("exact_if_integer"),
            "comment_count_basis": "visible_page_snapshot; includes_top_level_or_nested_unverified",
            "comment_count_as_of": captured_at,
            "url": post["detail_url"],
            "board": embedded.get("board_name") or "",
            "preview_only": post.get("page_kind") != "detail_page",
            "text_source": "visible_detail_dom" if post.get("page_kind") == "detail_page" else "visible_list_dom",
            "created_at_source": "page_embedded_createTime" if timestamp else ("visible_full_date" if verified_date else "missing_verified_year"),
            "displayed_date_label": date_label or None,
            "date_precision": "second" if timestamp else ("day" if verified_date else "unknown"),
            "contact_masking": "mainland_mobile_email_explicit_qq; personal_names_in_prose_require_manual_review",
        })
    return {
        "source": parsed["source"],
        "captured_at": captured_at,
        "scope": parsed["coverage"],
        "truncated": True if any(p["preview_only"] for p in posts) else None,
        "posts": posts,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--source-url", default="", help="Exact URL that supplied this saved HTML")
    ap.add_argument("--analysis-output", type=Path, help="Write normalized JSON for analyze_posts.py")
    ap.add_argument("--captured-at", help="Actual collection timestamp; omitted when unknown")
    args = ap.parse_args()
    raw = args.html.read_bytes()
    result = parse_html(raw.decode("utf-8-sig"), args.source_url, hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.analysis_output:
        args.analysis_output.parent.mkdir(parents=True, exist_ok=True)
        args.analysis_output.write_text(json.dumps(to_analysis_document(result, args.captured_at), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "summary": result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
