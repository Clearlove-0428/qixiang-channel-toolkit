const $=id=>document.getElementById(id);
async function refresh(){
  const stored=await chrome.storage.local.get(['qixiang_auto_run_v1','qixiang_manual_result']);const run=stored.qixiang_auto_run_v1;
  const active=Boolean(run?.running&&Date.now()-Date.parse(run.last_updated_at||0)<45000);
  $('start').disabled=active;$('stop').disabled=!active;$('capture').disabled=active;
  $('runStatus').textContent=run?.target?`${run.phase||''} · 正式 ${run.formal_posts||0}/${run.target} 帖；本轮新增 ${run.new_posts||0}，详情 ${run.detail_posts||0}，有评论 ${run.comment_posts||0}，截图片段 ${run.screenshot_fragments||0}。${active?'':run.reason||''}`:'等待新一轮开始。';
  try{const response=await chrome.runtime.sendMessage({type:'qixiang-v3:bridge',path:'status',data:{}});if(response.error)throw Error(response.error);const s=response.result;$('catalogStatus').textContent=`资料库已有正式帖子 ${s.formal_posts}；截图 ${s.screenshots}，头像 ${s.saved_avatars}。`;$('status').textContent=stored.qixiang_manual_result||'本机连接正常，图文、截图和评论会直接保存。';$('status').classList.remove('error');}
  catch{$('status').textContent='请先双击项目中的“打开资料管理.cmd”，再回到这里。';$('status').classList.add('error');}
}
$('start').onclick=async()=>{
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(!tab?.id)throw Error('请先打开频道列表。');
    const config={target:Number($('target').value)||10000,detail_every:Number($('detailEvery').value),screenshots:$('screenshots').checked,max_steps:Number($('maxSteps').value)||15000,interval_ms:Number($('interval').value)||1500};
    await chrome.storage.local.set({qixiang_v3_config:config,qixiang_auto_stop_v1:false,qixiang_manual_result:''});
    await chrome.scripting.executeScript({target:{tabId:tab.id},files:['time_utils.js','extractor.js','auto_capture_v3.js']});window.close();
  }catch(error){$('status').textContent=error.message;$('status').classList.add('error');}
};
$('stop').onclick=async()=>{await chrome.storage.local.set({qixiang_auto_stop_v1:true});$('runStatus').textContent='正在停止，已经收到的记录保留在本机。';};
$('capture').onclick=async()=>{try{const[tab]=await chrome.tabs.query({active:true,currentWindow:true});await chrome.storage.local.set({qixiang_manual_result:''});await chrome.scripting.executeScript({target:{tabId:tab.id},files:['time_utils.js','extractor.js','capture_current_v3.js']});window.close();}catch(error){$('status').textContent=error.message;}};
$('dashboard').onclick=()=>chrome.tabs.create({url:'http://127.0.0.1:8765'});
refresh();setInterval(refresh,2000);
