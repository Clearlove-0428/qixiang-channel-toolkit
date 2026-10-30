import json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research_library import Library
from local_model import LocalModel

class LocalModelTests(unittest.TestCase):
    def test_malformed_batch_retries_and_keeps_human_annotation(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=Library(Path(folder));data={'posts':[{'id':f'B_model_{i}','text':'合成课程咨询内容'} for i in range(4)]}
            lib.import_document(data,b'{}','fixture.json');lib.annotate({'post_id':'B_model_0','main_category':'校园办事','reviewer':'合成核查员'})
            model=LocalModel(lib);model.ensure=lambda:None;calls=[]
            def request(*args,**kwargs):
                calls.append(1)
                content='{' if len(calls)==1 else json.dumps({'labels':[{'key':str(i),'category':'学习与课程','topic':'合成咨询','evidence':'课程咨询','confidence':.8} for i in range(4)]})
                return {'choices':[{'message':{'content':content}}]}
            model.request=request;model.start(4)
            for _ in range(80):
                if not model.state['running']:break
                time.sleep(.05)
            self.assertFalse(model.state['running']);self.assertEqual(model.state['processed'],4);self.assertEqual(model.state['batch_errors'],1)
            self.assertEqual(lib.posts()['posts'][0]['annotation']['main_category'],'校园办事')

if __name__=='__main__':unittest.main()
