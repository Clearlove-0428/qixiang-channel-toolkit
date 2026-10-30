"""Targeted tests for privacy and missing-date boundaries; zero network I/O."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("public_page_parser", Path(__file__).parents[1] / "parse_public_page.py")
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)


class PublicParserTests(unittest.TestCase):
    def test_contact_masking(self):
        source = "手机13800138000 邮箱abc.def+club@example.edu.cn QQ号：12345678 qq 12345 QQ群号=87654321"
        self.assertEqual(PARSER.redact_contact_details(source), "手机[联系方式] 邮箱[联系方式] [联系方式] [联系方式] [联系方式]")

    def test_plain_numbers_are_preserved(self):
        source = "浏览7011，评论33，编号12345678，样本130，日期2026-10-14，136000000000"
        self.assertEqual(PARSER.redact_contact_details(source), source)

    def test_unknown_year_and_known_zero(self):
        html = ('<a class="game-guild-main__short-content" href="https://pd.qq.com/g/x/post/A">'
                '<h3 class="nick">作者昵称</h3><h3 class="edit-time">10-14</h3>'
                '<span class="feed-detail-text">联系13800138000</span>'
                '<div class="game-guild-main__short-content__comment">0</div></a>')
        parsed = PARSER.parse_html(html, "https://pd.qq.com/g/x", "test")
        post = PARSER.to_analysis_document(parsed)["posts"][0]
        self.assertIsNone(post["created_at"])
        self.assertEqual(post["comment_count"], 0)
        self.assertTrue(post["preview_only"])
        self.assertEqual(post["text"], "联系[联系方式]")
        self.assertNotIn("作者昵称", str(parsed))
        self.assertNotIn("13800138000", str(parsed))

    def test_title_and_text_are_masked_at_normalization_boundary(self):
        parsed = {
            "source": {}, "coverage": {},
            "posts": [{"post_id": "A", "detail_url": "https://pd.qq.com/g/x/post/A", "page_kind": "detail_page",
                       "visible_dom": {"text": "QQ:12345678", "date_label": "2026-10-14", "counts": {}},
                       "page_embedded_data": {"title_text": "abc@example.com"}}],
        }
        post = PARSER.to_analysis_document(parsed)["posts"][0]
        self.assertEqual(post["title"], "[联系方式]")
        self.assertEqual(post["text"], "[联系方式]")
        self.assertEqual(post["created_at"], "2026-10-14")


if __name__ == "__main__":
    unittest.main()
