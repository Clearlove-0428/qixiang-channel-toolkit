const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {chromium}=require('playwright');
const root=path.resolve(process.argv[2]);
const controlPath=path.join(root,'索引','后台采集控制.json');
const statePath=path.join(root,'索引','后台采集状态.json');
const profile=path.resolve(process.env.QIXIANG_BROWSER_PROFILE||path.join(root,'浏览器登录配置'));
const browserChannel=process.env.QIXIANG_BROWSER_CHANNEL||'chrome';
let state={pid:process.pid,running:true,mode:'starting',phase:'准备采集浏览器',new_posts:0},context;
function control(){try{return JSON.parse(fs.readFileSync(controlPath,'utf8'));}catch{return {action:'stop'};}}
function save(extra={}){state={...state,...extra,updated_at:new Date().toISOString()};try{const temp=statePath+'.tmp';fs.writeFileSync(temp,JSON.stringify(state));fs.renameSync(temp,statePath);}catch{}}
const timer=setInterval(()=>save(),2000);
async function launch(headless){return chromium.launchPersistentContext(profile,{...(browserChannel==='chromium'?{}:{channel:browserChannel}),headless,viewport:{width:1600,height:1100},locale:'zh-CN',timezoneId:'Asia/Shanghai',acceptDownloads:false,args:['--disable-background-timer-throttling']});}
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  try{
    let config=control();
    if(config.action==='login'){
      context=await launch(false);const page=context.pages()[0]||await context.newPage();
      await page.goto('https://pd.qq.com/g/npu0lakeside',{waitUntil:'domcontentloaded',timeout:60000}).catch(()=>{});
      save({mode:'login',phase:'请在新打开的采集浏览器中登录QQ，再点击资料页的开始后台采集'});
      while((config=control()).action==='login')await pause(700);
      await context.close();context=null;
    }
    if(config.action==='collect'){
      context=await launch(true);save({mode:'collect',phase:'正在后台打开频道',headless:true});
      await require('./background_capture.cjs').collect({context,root,config,control,save});
    }
  }catch(error){save({phase:'采集已停止：'+String(error.message||error).replace(/Bearer\s+\S+/g,'[本机连接]'),error:true});}
  finally{if(context)await context.close().catch(()=>{});clearInterval(timer);save({running:false,finished_at:new Date().toISOString()});}
})();
