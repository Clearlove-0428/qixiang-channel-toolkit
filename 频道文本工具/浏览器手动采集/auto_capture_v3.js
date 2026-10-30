void(async()=>{
  if(globalThis.__qixiangAutoRunningV3)return;globalThis.__qixiangAutoRunningV3=true;
  const STOP='qixiang_auto_stop_v1',RUN='qixiang_auto_run_v1';
  const config=(await chrome.storage.local.get('qixiang_v3_config')).qixiang_v3_config||{};
  const target=Math.max(1,Math.min(10000,Number(config.target)||10000));
  const maxSteps=Math.max(2,Math.min(30000,Number(config.max_steps)||15000));
  const detailEvery=Math.max(0,Math.min(100,Number.isFinite(Number(config.detail_every))?Number(config.detail_every):5));
  const started=Date.now(),startedAt=new Date().toISOString();
  let runId,index={},baseFormal=0,added=0,updated=0,steps=0,details=0,comments=0,shots=0,sequence=0,reason='已停止',phase='连接本机资料库',imageBudget=false;
  const signatures=new Map(),shotRanges=new Map(),skipped=new Set(),seenDetail=new Set();
  const state=()=>({running:true,started_at:startedAt,last_updated_at:new Date().toISOString(),run_id:runId,steps_done:steps,new_posts:added,enriched_posts:updated,skipped_known_posts:skipped.size,detail_posts:details,comment_posts:comments,screenshot_fragments:shots,formal_posts:baseFormal+added,target,phase,reason});
  async function send(type,data,path){const answer=await chrome.runtime.sendMessage({type:'qixiang-v3:'+type,path,data});if(answer?.error)throw Error(answer.error);return answer?.result;}
  const bridge=(path,data)=>send('bridge',data,path);
  async function heartbeat(final=false){const s=state();s.running=!final;await chrome.storage.local.set({[RUN]:s});if(runId){const result=await bridge('update',{run_id:runId,state:s});if(result?.stop_requested)await chrome.storage.local.set({[STOP]:true});}}
  async function pause(ms){for(let t=0;t<ms;t+=200){if((await chrome.storage.local.get(STOP))[STOP])return false;await new Promise(r=>setTimeout(r,Math.min(200,ms-t)));}return true;}
  async function visible(){
    while(document.visibilityState!=='visible'){
      phase='等待频道标签页回到前台';await chrome.storage.local.set({[RUN]:state()});
      if(!(await pause(1000)))return false;
      if(Date.now()-started>4*3600000)return false;
    }return true;
  }
  const idOf=card=>{try{return new URL(card.href).pathname.split('/post/')[1]?.replace(/\/$/,'');}catch{return null;}};
  function fragment(node,postId,scope,clipper){
    const r=node.getBoundingClientRect(),clip=clipper?.getBoundingClientRect();
    const x=Math.max(0,r.left,clip?.left||0),y=Math.max(0,r.top,clip?.top||0);
    const right=Math.min(innerWidth,r.right,clip?.right||innerWidth),bottom=Math.min(innerHeight,r.bottom,clip?.bottom||innerHeight);
    if(right-x<80||bottom-y<35||r.height<=0)return null;
    const offset=Math.max(0,y-r.top),key=postId+'|'+scope;
    const ranges=shotRanges.get(key)||[];
    const newlyVisible=!ranges.some(([lo,hi])=>lo<=offset+8&&hi>=offset+bottom-y-8);
    if(!newlyVisible)return null;
    return{post_id:postId,scope,x,y,width:right-x,height:bottom-y,offset,total_height:r.height};
  }
  async function screenshot(fragments){
    if(!config.screenshots||imageBudget||!fragments.length)return;
    const answer=await send('screenshot',{fragments,viewport_width:innerWidth,viewport_height:innerHeight,captured_at:new Date().toISOString()});
    shots+=answer?.saved||0;
    if(answer?.reason)imageBudget=true;
    if(answer?.saved)for(const f of fragments){const key=f.post_id+'|'+f.scope;shotRanges.set(key,[...(shotRanges.get(key)||[]),[f.offset,f.offset+f.height]]);}
  }
  async function submit(posts){
    if(!posts.length)return;
    const result=await bridge('ingest',{run_id:runId,sequence:sequence++,posts});added+=result.added||0;updated+=result.updated||0;
    for(const post of posts)index[post.id]={...index[post.id],detail:post.preview_only===false||index[post.id]?.detail};
  }
  function closeDetail(){const root=document.querySelector('.game-guild-detail');const close=root?.parentElement?.querySelector('.close-icon');if(close)close.click();else if(location.pathname.includes('/post/'))history.back();}
  async function detail(postId){
    if(seenDetail.has(postId))return;
    const card=[...document.querySelectorAll('a.game-guild-main__short-content')].find(node=>idOf(node)===postId);
    if(!card)return;
    phase='读取主帖详情与可见评论';card.click();
    let raw;
    for(let count=0;count<35;count++){
      if(!(await pause(180)))return;
      const trial=extractRenderedChannelPage();if(trial.page_kind==='detail'&&trial.posts?.[0]?.id===postId){raw=trial;break;}
    }
    if(!raw){closeDetail();await pause(700);throw Error('详情加载较慢，任务停在本机已保存的位置，可稍后继续。');}
    await pause(450);
    const root=document.querySelector('.game-guild-detail');
    const first=fragment(root,postId,'detail');if(first)await screenshot([first]);
    const allComments=new Map();let latest=raw.posts[0];
    for(let round=0;round<3;round++){
      const read=extractRenderedChannelPage();if(read.page_kind!=='detail')break;
      latest=read.posts[0];for(const c of latest.visible_comments||[])allComments.set(c.text,c);
      if(allComments.size>=120||round===2)break;
      const candidates=[root,...root.querySelectorAll('*')];let parent=root.parentElement;while(parent&&parent!==document.body){candidates.push(parent);parent=parent.parentElement;}
      const scroller=candidates.find(el=>el.clientHeight>180&&el.scrollHeight>el.clientHeight+30&&/auto|scroll/.test(getComputedStyle(el).overflowY));
      if(!scroller)break;
      const before=scroller.scrollTop;scroller.scrollTop+=scroller.clientHeight*.8;
      if(!(await pause(850)))break;if(scroller.scrollTop<=before+2)break;
    }
    latest.visible_comments=[...allComments.values()].slice(0,120);latest.visible_comment_count=latest.visible_comments.length;
    latest.comments_scope='detail_rendered_initial_and_up_to_2_scrolls';latest.detail_selection='every_'+detailEvery+'_new_posts';
    await submit([latest]);details++;if(latest.visible_comments.length)comments++;seenDetail.add(postId);index[postId].detail=true;
    closeDetail();for(let wait=0;wait<20&&location.pathname.includes('/post/');wait++)await pause(100);
    await pause(300);
  }
  try{
    if(location.hostname!=='pd.qq.com'||location.pathname!=='/g/npu0lakeside')throw Error('请在启翔湖畔帖子列表开始。');
    const connected=await bridge('start',{...config,target});runId=connected.run_id;index=connected.index||{};baseFormal=connected.status?.formal_posts||0;
    let stalled=0;
    for(let step=0;step<maxSteps;step++){
      if((await chrome.storage.local.get(STOP))[STOP]){reason='用户停止';break;}
      if(baseFormal+added>=target){reason='达到正式帖子目标';break;}
      if(Date.now()-started>4*3600000){reason='达到单轮4小时上限，可继续下一轮';break;}
      if(!(await visible())){reason='用户停止或前台等待超时';break;}
      if(location.pathname!=='/g/npu0lakeside')throw Error('当前页面已离开列表，任务停止。');
      const scroller=[...document.querySelectorAll('.vue-recycle-scroller')].find(el=>el.querySelector('a.game-guild-main__short-content'));
      if(!scroller)throw Error('频道列表暂时无法读取，请刷新后继续。');
      phase='记录列表图文';const raw=extractRenderedChannelPage();if(raw.error||!raw.posts?.length)throw Error(raw.error||'当前页面等待帖子加载。');
      const beforeKnown=new Set(Object.keys(index)),fresh=raw.posts.filter(post=>!beforeKnown.has(post.id));
      const toSend=raw.posts.filter(post=>{const signature=JSON.stringify([post.text,post.images?.map(im=>im.url),post.author_avatar_url,post.comment_count]);if(signatures.get(post.id)===signature){skipped.add(post.id);return false;}signatures.set(post.id,signature);return true;});
      await submit(toSend);
      const fragments=[...document.querySelectorAll('a.game-guild-main__short-content')].filter(card=>!index[idOf(card)]?.shot).map(card=>fragment(card,idOf(card),'list',scroller)).filter(f=>f&&index[f.post_id]);
      await screenshot(fragments);
      if(detailEvery>0){const candidates=fresh.filter((post,i)=>(baseFormal+added-fresh.length+i)%detailEvery===0);for(const post of candidates){if((await chrome.storage.local.get(STOP))[STOP])break;await detail(post.id);}}
      steps++;await heartbeat();
      const current=[...document.querySelectorAll('.vue-recycle-scroller')].find(el=>el.querySelector('a.game-guild-main__short-content'));
      if(!current)throw Error('详情返回后等待列表恢复。');
      const before=current.scrollTop;current.scrollTop=before+Math.max(320,current.clientHeight*.82);current.dispatchEvent(new Event('scroll',{bubbles:true}));
      if(!(await pause(Math.max(1100,Number(config.interval_ms)||1500)))){reason='用户停止';break;}
      stalled=Math.abs(current.scrollTop-before)<2?stalled+1:0;
      if(stalled>=6){reason='页面到达可访问底部或停止加载，按实际数量保存';break;}
      if(step+1>=maxSteps)reason='达到翻屏上限，可继续下一轮';
    }
  }catch(error){reason=error.message||String(error);}
  finally{
    try{if(document.querySelector('.game-guild-detail'))closeDetail();phase='已停止';await heartbeat(true);}
    catch{await chrome.storage.local.set({[RUN]:{...state(),running:false,phase:'已停止',reason}});}
    globalThis.__qixiangAutoRunningV3=false;
  }
})();
