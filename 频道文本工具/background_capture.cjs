const fs=require('node:fs');
const path=require('node:path');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const CHANNEL='https://pd.qq.com/g/npu0lakeside';

function screenFragments(){
  const scroller=[...document.querySelectorAll('.vue-recycle-scroller')].find(el=>el.querySelector('a.game-guild-main__short-content'));
  const root=document.querySelector('.game-guild-detail');
  const nodes=root?[root]:[...document.querySelectorAll('a.game-guild-main__short-content')];
  const clip=root?null:scroller?.getBoundingClientRect();
  return nodes.map(node=>{
    let postId;if(root)postId=location.pathname.split('/post/')[1];else try{postId=new URL(node.href).pathname.split('/post/')[1];}catch{}
    if(!postId)return null;
    const r=node.getBoundingClientRect();const x=Math.max(0,r.left,clip?.left||0),y=Math.max(0,r.top,clip?.top||0),right=Math.min(innerWidth,r.right,clip?.right||innerWidth),bottom=Math.min(innerHeight,r.bottom,clip?.bottom||innerHeight);
    if(right-x<70||bottom-y<30||r.height<1)return null;
    return {post_id:postId,scope:root?'detail':'list',x,y,width:right-x,height:bottom-y,offset:Math.max(0,y-r.top),total_height:r.height};
  }).filter(Boolean);
}

async function closeDetail(page){
  const opened=await page.evaluate(()=>{const detail=document.querySelector('.game-guild-detail');const close=detail?.parentElement?.querySelector('.close-icon');if(close){close.click();return true;}return location.pathname.includes('/post/');}).catch(()=>false);
  if(opened)await page.waitForFunction(()=>!location.pathname.includes('/post/'),{},{timeout:4000}).catch(async()=>{await page.goBack({waitUntil:'domcontentloaded',timeout:15000}).catch(()=>{});});
}

async function discoverSections(page,api,save){
  const names=await page.locator('.tab-bar__item').allTextContents();const catalog=[];
  for(const raw of names){
    const name=raw.trim();if(!name||name==='全部'||name==='热门')continue;
    save({phase:'核对频道分区 '+name});
    await page.evaluate(name=>[...document.querySelectorAll('.tab-bar__item')].find(e=>e.textContent.trim()===name)?.click(),name);
    await page.waitForFunction(name=>document.querySelector('.tab-bar__item.is-active')?.textContent.trim()===name,name,{timeout:5000}).catch(()=>{});
    await pause(700);
    const url=await page.evaluate(()=>location.href);const id=new URL(url).searchParams.get('subc');
    if(/^\d{1,15}$/.test(id||''))catalog.push({id,name,url:CHANNEL+'?subc='+id});
  }
  if(catalog.length)await api('sections',{sections:catalog});
  return catalog;
}

async function collect({context,root,config,control,save}){
  const connection=JSON.parse(fs.readFileSync(path.join(root,'索引','采集连接.json'),'utf8'));
  if(!/^http:\/\/127\.0\.0\.1:\d{1,5}$/.test(connection.base_url))throw Error('本机资料库地址待核对');
  const api=async(name,data)=>{
    const response=await fetch(connection.base_url+'/api/collector/'+name,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+connection.token},body:JSON.stringify(data),signal:AbortSignal.timeout(30000)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'本机保存请求失败');return result;
  };
  await context.addInitScript({path:path.join(__dirname,'浏览器手动采集','time_utils.js')});
  await context.addInitScript({path:path.join(__dirname,'浏览器手动采集','extractor.js')});
  const first=context.pages()[0]||await context.newPage();
  await first.goto(CHANNEL,{waitUntil:'domcontentloaded',timeout:60000});
  await first.locator('.tab-bar__item').first().waitFor({timeout:30000});
  if(await first.getByText('登录之后可以',{exact:true}).isVisible().catch(()=>false))throw Error('请先在独立采集浏览器完成QQ登录');
  const visibleNames=await first.locator('.tab-bar__item').allTextContents();
  let cached=[];try{cached=JSON.parse(fs.readFileSync(path.join(root,'索引','分区目录.json'),'utf8'));}catch{}
  let sections=cached.filter(s=>visibleNames.map(n=>n.trim()).includes(s.name)&&Date.now()-Date.parse(s.observed_at)<24*3600000).map(s=>({...s,url:CHANNEL+'?subc='+s.id}));
  if(sections.length<visibleNames.filter(n=>!['全部','热门'].includes(n.trim())).length)sections=await discoverSections(first,api,save);
  if(!sections.length)throw Error('分区入口正在加载，已保留当前资料，请稍后重试');
  const requested=Array.isArray(config.section_names)?config.section_names:[];
  if(requested.length)sections=sections.filter(s=>requested.includes(s.name));
  const priority=['翱翔峰会（学习论坛）','选课、老师相关','学习资源分享','失物','转专业','校园活动','宝藏社团','求职有道','竞赛找队友','搭子与赛事'];
  sections.sort((a,b)=>{const ai=priority.indexOf(a.name),bi=priority.indexOf(b.name);return (ai<0?100:ai)-(bi<0?100:bi);});
  const target=Math.max(1,Math.min(50000,Number(config.target)||10000));
  const perSection=Math.max(10,Math.min(3000,Number(config.per_section)||500));
  const detailEvery=Math.max(0,Math.min(100,Number(config.detail_every)||0));
  const interval=Math.max(900,Number(config.interval_ms)||1100);
  const workerCount=Math.max(1,Math.min(2,Number(config.workers)||2));
  const started=Date.now(),deadline=started+Math.max(1,Math.min(12,Number(config.max_hours)||8))*3600000;
  const connected=await api('start',{...config,mode:'headless_by_section',target,sections});
  const index=connected.index||{},base=connected.status.formal_posts,progress=sections.map(s=>({...s,seen:0,added:0,details:0,status:'待采集'}));
  const counters={new_posts:0,enriched_posts:0,details:0,comments:0,screenshot_fragments:0,detail_errors:0};
  let stopped=false,imageBudget=false,cursor=0,sequence=0,lastHeartbeat=0;
  const shouldStop=()=>stopped||control().action!=='collect'||base+counters.new_posts>=target||Date.now()>=deadline;
  function currentState(){return {running:true,mode:'collect',headless:true,run_id:connected.run_id,started_at:new Date(started).toISOString(),last_updated_at:new Date().toISOString(),formal_posts:base+counters.new_posts,target,workers:workerCount,phase:'按分区后台采集',...counters,section_progress:progress};}
  async function heartbeat(force=false){
    save(currentState());if(!force&&Date.now()-lastHeartbeat<1500)return;lastHeartbeat=Date.now();
    const result=await api('update',{run_id:connected.run_id,state:currentState()});if(result.stop_requested)stopped=true;
  }
  async function submit(posts){
    if(!posts.length)return;
    const result=await api('ingest',{run_id:connected.run_id,sequence:sequence++,posts});
    counters.new_posts+=result.added||0;counters.enriched_posts+=result.updated||0;
    for(const p of posts)index[p.id]={...index[p.id],detail:index[p.id]?.detail||p.preview_only===false};
    return result;
  }
  async function snapshot(page,ranges){
    if(!config.screenshots||imageBudget)return;
    let fragments=await page.evaluate(screenFragments);
    fragments=fragments.filter(f=>{
      if(!index[f.post_id]||(f.scope==='list'&&index[f.post_id]?.shot))return false;
      return !(ranges.get(f.post_id+'|'+f.scope)||[]).some(([lo,hi])=>lo<=f.offset+5&&hi>=f.offset+f.height-5);
    });
    if(!fragments.length)return;
    try{
      const buffer=await page.screenshot({type:'jpeg',quality:82,animations:'disabled',timeout:12000});
      const viewport=page.viewportSize();
      const result=await api('screenshot',{fragments,viewport_width:viewport.width,viewport_height:viewport.height,captured_at:new Date().toISOString(),capture_method:'headless_rendered_pixels',data_url:'data:image/jpeg;base64,'+buffer.toString('base64')});
      counters.screenshot_fragments+=result.saved||0;if(result.reason)imageBudget=true;
      if(result.saved)for(const f of fragments){const key=f.post_id+'|'+f.scope;ranges.set(key,[...(ranges.get(key)||[]),[f.offset,f.offset+f.height]]);}
    }catch(error){save({last_screenshot_note:'本屏截图稍后补充：'+String(error.message).slice(0,180)});}
  }
  async function observeDetail(page,postId,section,ranges){
    if(index[postId]?.detail||shouldStop())return false;
    try{
      const opened=await page.evaluate(id=>{const card=[...document.querySelectorAll('a.game-guild-main__short-content')].find(el=>new URL(el.href).pathname.endsWith('/post/'+id));if(card){card.click();return true;}return false;},postId);
      if(!opened)return false;
      await page.waitForFunction(id=>location.pathname.endsWith('/post/'+id)&&document.querySelector('.game-guild-detail .feed-content'),postId,{timeout:9000});
      await pause(400);await snapshot(page,ranges);
      const comments=new Map();let post;
      for(let round=0;round<3;round++){
        const raw=await page.evaluate(()=>extractRenderedChannelPage());post=raw.posts?.[0];if(post?.id!==postId)break;
        for(const item of post.visible_comments||[])comments.set(item.text,item);
        if(round===2||comments.size>=120||shouldStop())break;
        const scrolled=await page.evaluate(()=>{const root=document.querySelector('.game-guild-detail');if(!root)return false;const elements=[root,...root.querySelectorAll('*')];let parent=root.parentElement;while(parent&&parent!==document.body){elements.push(parent);parent=parent.parentElement;}const el=elements.find(e=>e.clientHeight>180&&e.scrollHeight>e.clientHeight+30&&/auto|scroll/.test(getComputedStyle(e).overflowY));if(!el)return false;const before=el.scrollTop;el.scrollTop+=el.clientHeight*.85;return el.scrollTop>before+2;});
        if(!scrolled)break;await pause(600);
      }
      if(post?.id===postId){post.visible_comments=[...comments.values()];post.sampling_entry=section.name;post.sampling_frame='section_supplement';post.comments_scope='headless_detail_initial_and_up_to_2_scrolls';post.detail_selection='every_'+detailEvery+'_new_posts';await submit([post]);counters.details++;counters.comments+=comments.size;return true;}
    }catch(error){counters.detail_errors++;save({last_detail_note:'详情暂缓，继续列表：'+postId});}
    finally{await closeDetail(page);await pause(180);}
    return false;
  }
  async function sectionTask(page,section,record){
    record.status='采集中';const seen=new Set(),signatures=new Map(),ranges=new Map();let stalled=0;
    await page.goto(section.url,{waitUntil:'domcontentloaded',timeout:45000});
    await page.locator('.tab-bar__item').first().waitFor({timeout:20000});
    await page.evaluate(name=>[...document.querySelectorAll('.tab-bar__item')].find(e=>e.textContent.trim()===name)?.click(),section.name);
    await page.waitForFunction(()=>[...document.querySelectorAll('.vue-recycle-scroller')].some(el=>el.querySelector('a.game-guild-main__short-content')),{},{timeout:20000}).catch(()=>{});
    for(let step=0;step<15000&&!shouldStop()&&seen.size<perSection;step++){
      if(await page.getByText('登录之后可以',{exact:true}).isVisible().catch(()=>false)){stopped=true;throw Error('登录状态需要刷新，请打开采集浏览器');}
      const raw=await page.evaluate(()=>extractRenderedChannelPage());
      if(raw.error){await closeDetail(page);await pause(interval);stalled++;if(stalled>8){record.status='页面待恢复';break;}continue;}
      const posts=raw.posts||[];const fresh=posts.filter(p=>!index[p.id]);
      const sent=posts.filter(post=>{seen.add(post.id);post.sampling_entry=section.name;post.sampling_frame='section_supplement';const signature=JSON.stringify([post.text,post.images,post.comment_count,post.board_id]);if(signatures.get(post.id)===signature)return false;signatures.set(post.id,signature);return true;});
      const result=await submit(sent);record.added+=result?.added||0;record.seen=seen.size;
      await snapshot(page,ranges);
      if(detailEvery)for(let i=0;i<fresh.length;i++)if((seen.size-fresh.length+i)%detailEvery===0&&!shouldStop())record.details+=await observeDetail(page,fresh[i].id,section,ranges)?1:0;
      await heartbeat();
      const moved=await page.evaluate(()=>{const el=[...document.querySelectorAll('.vue-recycle-scroller')].find(e=>e.querySelector('a.game-guild-main__short-content'));if(!el)return null;const before=el.scrollTop;el.scrollTop+=Math.max(320,el.clientHeight*.82);el.dispatchEvent(new Event('scroll',{bubbles:true}));return el.scrollTop-before;});
      stalled=moved===null||moved<2?stalled+1:0;
      if(stalled>=8){record.status='可见列表已到达底部';break;}
      await pause(stalled?2200:interval);
    }
    if(record.status==='采集中')record.status=shouldStop()?'随任务保存':'达到本分区观察量';
  }
  try{
    await heartbeat(true);await first.close();
    await Promise.all(Array.from({length:workerCount},async()=>{
      const page=await context.newPage();
      try{
        while(cursor<sections.length&&!shouldStop()){
          const position=cursor++;const section=sections[position],record=progress[position];
          try{await sectionTask(page,section,record);}
          catch(error){record.status='本分区暂缓';record.note=String(error.message||error).split('\n')[0].slice(0,160);save({last_section_note:record.name+'：'+record.note});}
          await heartbeat(true);
        }
      }finally{await page.close().catch(()=>{});}
    }));
  }finally{
    const reason=base+counters.new_posts>=target?'达到正式帖子目标':Date.now()>=deadline?'达到本轮运行时长':control().action!=='collect'||stopped?'按停止指令或登录状态保存':'已完成所选分区的可见观察范围';
    const final={...currentState(),running:false,phase:'后台采集已结束',reason};save(final);await api('update',{run_id:connected.run_id,state:final});
  }
}

module.exports={collect,screenFragments,closeDetail,discoverSections};
