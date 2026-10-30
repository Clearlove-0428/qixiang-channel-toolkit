"""Exercise fresh-library exports and disabled optional-model configuration."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from research_library import Library
from local_model import LocalModel


class DistributionTests(unittest.TestCase):
    def export_catalog(self, lib, output):
        subprocess.run([sys.executable, '-X', 'utf8', str(TOOL / 'build_handoff_catalog.py'),
                        '--database', str(lib.db), '--library-root', str(lib.root),
                        '--output', str(output)], check=True, capture_output=True, text=True, encoding='utf-8')
        return json.loads((output / '数据入口核验.json').read_text(encoding='utf-8'))

    def test_catalog_from_empty_library_without_optional_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            lib = Library(Path(folder) / 'data')
            output = Path(folder) / 'catalog'
            receipt = self.export_catalog(lib, output)
            self.assertEqual(receipt['formal_posts'], 0)
            self.assertEqual(receipt['media_associations'], 0)
            self.assertEqual((output / '帖子完整资料.jsonl').read_text(encoding='utf-8'), '')
            self.assertTrue((output / '逐帖浏览.html').is_file())

    def test_catalog_preserves_actual_human_annotation_with_no_media(self):
        with tempfile.TemporaryDirectory() as folder:
            lib = Library(Path(folder) / 'data')
            data = {'posts': [{'id': 'B_distribution', 'text': '【虚构】校园卡咨询'}]}
            lib.import_document(data, json.dumps(data).encode(), 'synthetic.json')
            lib.annotate({'post_id': 'B_distribution', 'main_category': '校园办事', 'reviewer': '虚构测试员'})
            output = Path(folder) / 'catalog'
            receipt = self.export_catalog(lib, output)
            self.assertEqual(receipt['manual_reviewed'], 1)
            self.assertEqual(receipt['visible_comment_records'], 0)
            record = json.loads((output / '帖子完整资料.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(record['human_review']['main_category'], '校园办事')

    def test_model_is_optional_and_explains_missing_configuration(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'QIXIANG_MODEL_PATH': '', 'QIXIANG_LLAMA_SERVER': ''}):
            model = LocalModel(Library(Path(folder)))
            model.request = lambda *args, **kwargs: (_ for _ in ()).throw(OSError('mock offline'))
            self.assertFalse(model.status()['weights_found'])
            with self.assertRaisesRegex(ValueError, 'QIXIANG_MODEL_PATH'):
                model.ensure()


if __name__ == '__main__':
    unittest.main()
