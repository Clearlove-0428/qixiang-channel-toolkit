import base64,io,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research_library import Library
from capture_bridge import CaptureBridge
from research_library import clean_post,merge_post
from research_exports import build_exports


class CaptureV3Tests(unittest.TestCase):
    def test_detail_date_preserves_list_estimate_and_export_separates_sources(self):
        list_post=clean_post({'id':'B_time','text':'合成课程咨询','time_method':'relative_estimate','created_at_estimated':'2026-10-26T05:00:00Z','time_precision':'分钟级估计','displayed_date_label':'5分钟前','captured_at':'2026-10-26T05:05:00Z'})
        detail=clean_post({'id':'B_time','text':'合成课程咨询详情','preview_only':False,'created_at':'2026-10-26','time_method':'displayed_calendar','created_at_estimated':'2026-10-25T16:00:00Z','comments_scope':'detail_rendered_initial_and_up_to_2_scrolls','visible_comments':[{'text':'合成回复'}]})
        merged=merge_post(list_post,detail)
        self.assertEqual(merged['created_at'],'2026-10-26')
        self.assertEqual(merged['created_at_estimated'],'2026-10-26T05:00:00Z')
        self.assertEqual(len(merged['time_observations']),2)
        self.assertEqual(merged['comments_scope'],'detail_rendered_initial_and_up_to_2_scrolls')
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder));bridge=CaptureBridge(lib,write_connection=False,start_workers=False)
            run=bridge.start({})['run_id'];bridge.ingest({'run_id':run,'posts':[merged]})
            lib.import_document({'posts':[{'id':'B_trial','text':'合成试采'}]},b'{}','trial.json','试采')
            result=build_exports(lib);root=Path(result['folder'])
            self.assertEqual(result['formal_posts'],1)
            self.assertEqual(result['manual_posts'],0)
            data=json.loads((root/'采集版本说明.json').read_text(encoding='utf-8'))
            self.assertEqual(data['coverage']['已保存评论文字条数'],1)
            self.assertEqual(data['stages'],{'正式':1,'试采':1})
            self.assertTrue((root/'资料快照.sqlite3').is_file())

    def test_stream_ten_thousand_idempotence_and_time_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder));bridge=CaptureBridge(lib,write_connection=False,start_workers=False)
            run=bridge.start({'target':10000})['run_id']
            for batch in range(100):
                posts=[{'id':f'B_stress_{batch*100+i}','text':'合成求助内容','created_at_estimated':'2026-10-26T05:00:00Z','time_method':'relative_estimate'} for i in range(100)]
                packet={'run_id':run,'sequence':batch,'posts':posts}
                first=bridge.ingest(packet);second=bridge.ingest(packet)
                self.assertEqual(first,second)
            self.assertEqual(bridge.status()['formal_posts'],10000)
            post=lib.posts(limit=1)['posts'][0]
            self.assertEqual(post['time_method'],'relative_estimate')
            self.assertNotIn('created_at',post)
            self.assertEqual(len(bridge.index()),10000)

    def test_real_pixel_crop_stitch_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder));bridge=CaptureBridge(lib,write_connection=False,start_workers=False)
            run=bridge.start({})['run_id'];bridge.ingest({'run_id':run,'posts':[{'id':'B_pixel','text':'合成截图'}]})
            screen=Image.new('RGB',(200,100),'red');screen.paste(Image.new('RGB',(200,50),'blue'),(0,50))
            stream=io.BytesIO();screen.save(stream,format='PNG')
            data={'viewport_width':200,'viewport_height':100,'data_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()}
            for offset in (0,50):
                result=bridge.screenshot({**data,'fragments':[{'post_id':'B_pixel','scope':'list','x':0,'y':offset,'width':100,'height':50,'offset':offset,'total_height':100}]})
                self.assertEqual(result['saved'],1)
            evidence=bridge.evidence('B_pixel')['screenshots'][0]
            self.assertEqual(json.loads(evidence['info_json'])['coverage'],1)
            self.assertLess(evidence['bytes'],1_000_000)
            with Image.open(Path(folder)/'截图'/evidence['relative_path']) as image:
                self.assertGreater(image.getpixel((10,10))[0],200)
                self.assertGreater(image.getpixel((10,90))[2],200)


if __name__=='__main__':unittest.main()
