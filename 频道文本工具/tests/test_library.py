import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_library import Library
from media_store import store_image


class LibraryTests(unittest.TestCase):
    def test_cross_batch_dedup_enrichment_and_annotation(self):
        with tempfile.TemporaryDirectory() as folder:
            lib = Library(Path(folder))
            first = {'posts':[{'id':'B_one','text':'求助：怎样办理校园卡','preview_only':True,'captured_at':'2026-10-19T08:00:00Z'}]}
            payload = json.dumps(first).encode()
            self.assertEqual(lib.import_document(first,payload,'one.json','试采')['new_posts'],1)
            self.assertTrue(lib.import_document(first,json.dumps(first,indent=2).encode(),'copy.json')['already_imported'])
            lib.annotate({'post_id':'B_one','main_category':'校园办事','reviewer':'合成复核员','notes':'合成依据'})
            second={'posts':[{'id':'B_one','text':'求助：怎样办理校园卡，详情文字。','preview_only':False,'created_at':'2026-10-19','visible_comments':[{'text':'带证件到服务大厅'}]}, {'id':'B_two','text':'分享课程经验'}]}
            result=lib.import_document(second,json.dumps(second).encode(),'two.json')
            self.assertEqual(result['new_posts'],1)
            posts=lib.posts(limit=100)['posts'];self.assertEqual(len(posts),2)
            post=next(p for p in posts if p['id']=='B_one')
            self.assertEqual(post['stage'],'试采')
            self.assertFalse(post['preview_only'])
            self.assertEqual(post['annotation']['notes'],'合成依据')
            self.assertEqual(len(post['visible_comments']),1)
            self.assertEqual(lib.summary()['stages'],{'正式':1,'试采':1})
            csv_input='post_id,main_category,notes,reviewer\nB_two,学习与课程,合成复核依据,复核员\nB_missing,其他,合成,复核员\n'
            result=lib.import_reviews(csv_input)
            self.assertEqual(result,{'accepted':1,'skipped':1})
            self.assertEqual(lib.summary()['reviewed'],{'正式':1,'试采':1})

    def test_2000_post_import_and_repeated_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder))
            data={'posts':[{'id':f'B_fixture_{i}','text':'合成测试内容'} for i in range(2000)]}
            lib.import_document(data,json.dumps(data).encode(),'first.json')
            overlapping={'posts':data['posts'][1000:]+[{'id':'B_added','text':'合成新帖'}]}
            result=lib.import_document(overlapping,json.dumps(overlapping).encode(),'overlap.json')
            self.assertEqual(result['new_posts'],1)
            self.assertEqual(lib.summary()['total_posts'],2001)
            index=json.loads((Path(folder)/'索引/启翔湖畔去重索引.json').read_text(encoding='utf-8'))
            self.assertEqual(len(index['entries']),2001)
            csv_text=lib.csv_export(sample_size=200).decode('utf-8-sig')
            self.assertEqual(len(csv_text.splitlines()),201)

    def test_image_compression_dedup_and_hard_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Image.effect_noise((3000,3000),100).convert('RGB')
            original=io.BytesIO();image.save(original,format='PNG')
            saved=store_image(original.getvalue(),Path(folder))
            again=store_image(original.getvalue(),Path(folder))
            self.assertLessEqual(saved['bytes'],1_000_000)
            self.assertEqual(saved['relative_path'],again['relative_path'])
            self.assertEqual(len(list(Path(folder).glob('*.jpg'))),1)
            with Image.open(Path(folder)/saved['relative_path']) as decoded:
                self.assertEqual(decoded.format,'JPEG')
                self.assertLessEqual(max(decoded.size),4096)


if __name__=='__main__':unittest.main()
