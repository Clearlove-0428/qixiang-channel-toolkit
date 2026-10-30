import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research_library import Library,clean_post,merge_post

class SectionTests(unittest.TestCase):
    def test_native_section_is_separate_from_sampling_entry_and_model_topic(self):
        raw={'id':'B_native','text':'合成选课咨询','url':'https://pd.qq.com/g/npu0lakeside/post/B_native?subc=225955741','sampling_entry':'全部'}
        p=clean_post(raw)
        self.assertEqual(p['board_id'],'225955741')
        self.assertEqual(p['sampling_frame'],'primary_all')
        later=clean_post({**raw,'sampling_entry':'翱翔峰会（学习论坛）','board':'翱翔峰会（学习论坛）'})
        merged=merge_post(p,later)
        self.assertEqual(merged['sampling_entry'],'全部')
        self.assertEqual(merged['sampling_frame'],'primary_all')
        self.assertEqual(merged['sampling_entries'],['全部','翱翔峰会（学习论坛）'])

    def test_catalog_backfill_preserves_post_count_and_has_visible_navigation_basis(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder));data={'posts':[{'id':'B_backfill','text':'合成材料','url':'https://pd.qq.com/g/npu0lakeside/post/B_backfill?subc=225955741','sampling_entry':'全部'}]}
            lib.import_document(data,json.dumps(data).encode(),'fixture.json')
            result=lib.save_sections([{'id':'225955741','name':'翱翔峰会（学习论坛）','url':'https://pd.qq.com/g/npu0lakeside?subc=225955741'}])
            self.assertEqual(result['posts_updated'],1)
            p=lib.posts()['posts'][0]
            self.assertEqual(p['board'],'翱翔峰会（学习论坛）')
            self.assertEqual(p['board_basis'],'visible_section_navigation')
            self.assertEqual(lib.summary()['total_posts'],1)
            self.assertEqual(lib.posts(board_id='225955741')['total'],1)

if __name__=='__main__':unittest.main()
