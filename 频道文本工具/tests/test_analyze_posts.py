"""Synthetic fixtures live only in temporary directories during these tests."""
import csv
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "analyze_posts.py"
SPEC = importlib.util.spec_from_file_location("analyze_posts", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OfflineAnalysisTests(unittest.TestCase):
    def test_dedup_date_count_and_database(self):
        records = [
            {"id": "fixture-1", "title": "合成测试：求助", "text": "测试正文", "created_at": "2026-10-14T10:00:00+08:00", "comment_count": 0},
            {"id": "fixture-1", "title": "合成测试：求助", "text": "测试正文", "created_at": "2026-10-14T10:00:00+08:00", "comment_count": 3},
            {"id": "fixture-2", "title": "合成测试", "comment_count": None},
            {"id": "fixture-3", "created_at": "昨天", "comment_count": "1万"},
            {"url": "https://example.invalid/test", "created_at": "2026-10-13", "comment_count": "2"},
            {"url": "https://example.invalid/test", "created_at": "2026-10-13", "comment_count": "2"},
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "fixtures.json"
            source.write_text(json.dumps({"posts": records}, ensure_ascii=False), encoding="utf-8")
            result = MODULE.analyze(source, root / "output")
            self.assertEqual(result["unique_posts"], 4)
            self.assertEqual(result["duplicate_records"], 2)
            self.assertEqual(result["date_quality"], {"parsed": 2, "missing": 1, "invalid": 1})
            self.assertEqual(result["comment_count_quality"], {"known_zero": 1, "known_positive": 1, "missing": 1, "invalid": 1})
            self.assertEqual(result["posts_with_duplicate_conflicts"], 1)
            with closing(sqlite3.connect(root / "output" / "posts.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT count(*) FROM posts").fetchone()[0], 4)
                self.assertEqual(database.execute("SELECT comment_count FROM posts WHERE id='fixture-1'").fetchone()[0], 0)
                self.assertIsNone(database.execute("SELECT comment_count FROM posts WHERE id='fixture-2'").fetchone()[0])

    def test_csv_formula_protection_html_escaping_and_identity_omission(self):
        title = '=HYPERLINK("https://example.invalid","fixture")'
        body = '<script>alert("synthetic")</script>&<img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "fixtures.json"
            source.write_text(json.dumps([{"id": "=1+1", "title": title, "text": body, "url": "javascript:alert(1)", "board": " \t@SUM(1)", "nickname": "SHOULD_NOT_BE_STORED", "avatar": "SHOULD_NOT_BE_STORED"}]), encoding="utf-8")
            MODULE.analyze(source, root / "output")
            with (root / "output" / "posts.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertTrue(row["title"].startswith("'="))
            self.assertTrue(row["id"].startswith("'="))
            self.assertTrue(row["board"].startswith("'@"))
            report = (root / "output" / "quality_report.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", report)
            self.assertIn("&lt;script&gt;", report)
            self.assertNotIn('href="javascript:', report)
            self.assertNotIn("SHOULD_NOT_BE_STORED", report)
            with closing(sqlite3.connect(root / "output" / "posts.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT title FROM posts").fetchone()[0], title)

    def test_repeat_run_preserves_human_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "fixtures.json"
            source.write_text("[]", encoding="utf-8")
            MODULE.analyze(source, root / "output")
            original = root / "output" / "human_review.csv"
            original.write_text("人工已核对记录", encoding="utf-8")
            result = MODULE.analyze(source, root / "output")
            self.assertEqual(original.read_text(encoding="utf-8"), "人工已核对记录")
            self.assertNotEqual(result["human_review_file"], "human_review.csv")

    def test_image_and_visible_comment_survive_deduplication(self):
        records = [
            {"id": "media-post", "text": "列表预览", "images": [{"url": "https://channel.qpic.cn/one.jpg", "width": 640}]},
            {"id": "media-post", "text": "详情", "images": [{"url": "https://channel.qpic.cn/two.jpg", "height": 800}],
             "visible_comments": [{"text": "页面当前显示的评论", "displayed_time_label": "昨天"}]},
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "media.json"
            source.write_text(json.dumps({"posts": records}, ensure_ascii=False), encoding="utf-8")
            result = MODULE.analyze(source, root / "output")
            self.assertEqual(result["unique_posts"], 1)
            self.assertEqual(result["observed_image_addresses"], 2)
            self.assertEqual(result["rendered_comment_texts"], 1)
            with closing(sqlite3.connect(root / "output" / "posts.sqlite3")) as database:
                image_count, comments_json = database.execute(
                    "SELECT image_count, visible_comments_json FROM posts WHERE id='media-post'").fetchone()
            self.assertEqual(image_count, 2)
            self.assertEqual(json.loads(comments_json)[0]["text"], "页面当前显示的评论")

    def test_invalid_input_and_count(self):
        self.assertEqual(MODULE.parse_count(True), (None, "invalid"))
        self.assertEqual(MODULE.parse_count(-1), (None, "invalid"))
        self.assertEqual(MODULE.parse_count(""), (None, "missing"))
        self.assertEqual(MODULE.parse_date("2026-99-14")[1], "invalid")
        self.assertEqual(MODULE.parse_date(1791936000000)[1], "parsed")
        for value in ("=1+1", " +SUM(1)", "\t@formula", "\r=1", "\n-1"):
            self.assertTrue(MODULE.csv_safe(value).startswith("'"))


if __name__ == "__main__":
    unittest.main()
