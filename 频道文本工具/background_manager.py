"""Manage a dedicated user-login browser and a local headless capture worker."""
from __future__ import annotations
import json,os,shutil,subprocess,time
from pathlib import Path


class BackgroundManager:
    def __init__(self,library):
        self.library=library;self.root=library.root
        self.control_file=self.root/'索引/后台采集控制.json';self.state_file=self.root/'索引/后台采集状态.json'
        self.log_root=self.root/'运行日志';self.log_root.mkdir(exist_ok=True)

    def status(self):
        try:state=json.loads(self.state_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):return {'running':False,'phase':'先打开采集浏览器完成登录','mode':'idle'}
        from datetime import datetime
        try:fresh=time.time()-datetime.fromisoformat(state['updated_at'].replace('Z','+00:00')).timestamp()<25
        except (KeyError,ValueError):fresh=False
        if state.get('running') and not fresh:state.update(running=False,phase='本地采集进程已结束，已有记录保留')
        return state

    def command(self,action,config=None):
        state=self.status()
        if action=='login' and state.get('running') and state.get('mode')=='collect':raise ValueError('请先停止后台采集，再打开登录浏览器。')
        if action=='collect' and state.get('running') and state.get('mode')=='collect':raise ValueError('后台采集正在运行，进度可在当前页面查看。')
        allowed={'target':10000,'per_section':500,'detail_every':10,'interval_ms':1100,'screenshots':True,'workers':2,'max_hours':8,'section_names':[]}
        allowed.update({key:value for key,value in (config or {}).items() if key in allowed})
        payload={'action':action,**allowed,'updated_at':time.time()}
        temp=self.control_file.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8');temp.replace(self.control_file)
        if action!='stop' and not state.get('running'):
            node=shutil.which('node')
            if not node:raise ValueError('本机Node运行环境待检查。')
            program=Path(__file__).with_name('background_worker.cjs')
            with (self.log_root/'background_worker.log').open('ab') as log:
                child=subprocess.Popen([node,str(program),str(self.root)],cwd=program.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            initial={'pid':child.pid,'running':True,'mode':'starting','phase':'正在启动本地采集浏览器','updated_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
            self.state_file.write_text(json.dumps(initial,ensure_ascii=False),encoding='utf-8')
        return {'ok':True,'message':'已发送'+{'login':'打开登录浏览器','collect':'后台采集','stop':'停止采集'}[action]+'指令','state':self.status()}
