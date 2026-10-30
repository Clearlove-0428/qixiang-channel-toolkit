let connection;
let lastCapture=0;
let captureChain=Promise.resolve();
async function localRequest(path,data){
  if(!connection)connection=await (await fetch(chrome.runtime.getURL('local_connection.json'))).json();
  if(connection.base_url!=='http://127.0.0.1:8765')throw Error('本机采集连接地址异常。');
  const response=await fetch(connection.base_url+'/api/collector/'+path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+connection.token},body:JSON.stringify(data),signal:AbortSignal.timeout(20000)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'本机保存失败。');return result;
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(!message?.type?.startsWith('qixiang-v3:'))return;
  const trustedPage=sender.tab?.url?.startsWith('https://pd.qq.com/g/npu0lakeside');
  const fromPopup=!sender.tab&&sender.url?.startsWith(chrome.runtime.getURL(''));
  if(!trustedPage&&!fromPopup){reply({error:'采集来源页面不匹配。'});return;}
  const work=async()=>{
    if(message.type==='qixiang-v3:bridge'){
      if(!['start','ingest','update','status','sections'].includes(message.path))throw Error('采集请求类型异常。');
      return localRequest(message.path,message.data);
    }
    if(message.type==='qixiang-v3:screenshot'){
      if(!trustedPage)throw Error('请在频道页面截图。');
      const [active]=await chrome.tabs.query({active:true,windowId:sender.tab.windowId});
      if(active?.id!==sender.tab.id)throw Error('频道标签页已切到后台，请切回后继续。');
      const delay=Math.max(0,700-(Date.now()-lastCapture));if(delay)await new Promise(r=>setTimeout(r,delay));
      const dataUrl=await chrome.tabs.captureVisibleTab(sender.tab.windowId,{format:'jpeg',quality:86});lastCapture=Date.now();
      return localRequest('screenshot',{...message.data,data_url:dataUrl});
    }
    throw Error('采集操作未识别。');
  };
  if(message.type==='qixiang-v3:screenshot'){
    captureChain=captureChain.catch(()=>{}).then(work);captureChain.then(result=>reply({result})).catch(error=>reply({error:error.message}));
  }else work().then(result=>reply({result})).catch(error=>reply({error:error.message}));
  return true;
});
