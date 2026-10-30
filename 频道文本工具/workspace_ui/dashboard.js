const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const node=document.createElement(tag); if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node; };
let state, page=1, total=0, selectedPost, busy=false;
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw Error(data.error||'操作失败');return data;}
function metric(parent,label,value){const row=el('div',undefined,'metric');row.append(el('span',label),el('strong',String(value)));parent.append(row);}
async function refresh(){
  state=await api('/api/state');$('stats').replaceChildren();
  const rows=[['正式材料',state.stages['正式']||0,'目标约10000帖'],['试采留档',state.stages['试采']||0,'保留来源标记'],['人工复核',Object.values(state.reviewed).reduce((a,b)=>a+b,0),'与模型候选分别统计'],['已存图片',state.image_files,'单张控制在1MB以内']];
  for(const [label,value,note] of rows){const card=el('div',undefined,'stat');card.append(el('p',label),el('strong',value.toLocaleString()),el('small',note));$('stats').append(card);}
  $('coverage').replaceChildren();for(const [label,key]of[['含图片地址的帖子','images'],['已经打开详情','details'],['页面明示日期','dates'],['保留推算时间','estimated_dates'],['取得可见评论文字','comments']])metric($('coverage'),label,state.coverage[key]);
  $('storage').replaceChildren();metric($('storage'),'压缩图片占用',(state.image_bytes/1e6).toFixed(2)+' MB');metric($('storage'),'所在磁盘可用',(state.free_bytes/2**30).toFixed(1)+' GB');metric($('storage'),'图片地址待保存 / 请求失败',`${state.media_status?.['待保存']||0} / ${state.media_status?.['请求失败']||0}`);metric($('storage'),'保存位置',state.library_root);
  $('typeChart').replaceChildren();const max=Math.max(1,...state.reviewed_types.map(r=>r.count));
  if(!state.reviewed_types.length)$('typeChart').append(el('p','完成帖子复核后，这里会出现类别数量。','muted'));
  for(const row of state.reviewed_types){const box=el('div',undefined,'bar-row'),track=el('div',undefined,'bar-track'),fill=el('div',undefined,'bar-fill');fill.style.width=(row.count/max*100)+'%';track.append(fill);box.append(el('span',row.stage+' · '+row.category,'bar-label'),track,el('span',String(row.count),'bar-count'));$('typeChart').append(box);}
  $('batchRows').replaceChildren();for(const row of state.batches){const tr=el('tr');for(const value of[row.filename,row.stage,row.new_posts,row.enriched,row.skipped,new Date(row.imported_at).toLocaleString()])tr.append(el('td',String(value)));$('batchRows').append(tr);}
  $('sectionCoverage').replaceChildren();for(const section of state.sections||[])metric($('sectionCoverage'),section.name,section.posts);
  const boardFilter=$('boardFilter');if(boardFilter){const selected=boardFilter.value;boardFilter.replaceChildren(new Option('全部原生分区',''));for(const section of state.sections||[])boardFilter.append(new Option(section.name,section.id));boardFilter.value=selected;}
  if(!$('mainCategory').options.length){for(const category of state.categories){$('mainCategory').append(new Option(category,category));$('secondCategory').append(new Option(category,category));$('categoryFilter').append(new Option(category,category));}}
}
async function loadPosts(){
  const query=new URLSearchParams({page,stage:$('stageFilter').value,search:$('search').value,category:$('categoryFilter').value,reviewed:$('reviewFilter').value,board_id:$('boardFilter')?.value||''});
  const result=await api('/api/posts?'+query);total=result.total;$('postList').replaceChildren();$('listCount').textContent=`共 ${total} 帖，当前第 ${page} 页`;
  const stage=$('stageFilter').value;$('exportCsv').href='/api/export?stage='+encodeURIComponent(stage||'all');$('sampleCsv').href='/api/export?sample=60&stage='+encodeURIComponent(stage||'正式');
  if(!(state.stages[stage||'正式']||0)){$('sampleCsv').removeAttribute('href');$('sampleCsv').textContent='正式采集后可抽样';}else $('sampleCsv').textContent='抽60帖核查表';
  for(const post of result.posts){
    const card=el('article',undefined,'post'),head=el('div',undefined,'post-head'),left=el('div');left.append(el('span',post.stage,'badge'+(post.stage==='试采'?' trial':'')),el('span',post.preview_only?'列表预览':'详情主帖','badge'),el('span',post.annotation.main_category||'待复核','badge'));
    const button=el('button','填写复核','button');button.onclick=()=>openReview(post);head.append(left,button);card.append(head,el('p',post.id,'post-id'),el('div',post.text||'这条记录主要由图片组成。','post-text'));
    if(post.evidence?.avatar?.relative_path){const avatar=el('img');avatar.src='/evidence/avatars/'+post.evidence.avatar.relative_path;avatar.alt='发帖头像原样记录';avatar.style.cssText='width:36px;height:36px;border-radius:50%;margin-right:10px';left.prepend(avatar);}
    card.append(el('p',`页面时间：${post.created_at||post.displayed_date_label||'待核实'} · 评论数快照：${post.comment_count??'待核实'} · 图片地址：${post.images.length} · 词表候选：${post.candidate_labels||'待判断'}`,'post-meta'));
    card.append(el('p',`原生分区：${post.board||post.board_id||'待核实'} · 初次采集入口：${post.sampling_entry||'待核实'} · 材料来源：${post.sampling_frame==='primary_all'?'全部入口观察':post.sampling_frame==='section_supplement'?'按分区补充':'按原始记录'}`,'post-meta'));
    if(post.created_at_estimated&&post.time_method!=='displayed_calendar')card.append(el('p',`推算时间：${new Date(post.created_at_estimated).toLocaleString()} · ${post.time_precision||'估计'} · 原始标签：${post.time_label_raw||''}`,'post-meta'));
    if(post.model_label)card.append(el('p',`本地模型候选：${post.model_label.category}；主题：${post.model_label.topic}；依据：${post.model_label.evidence||'待查看图片或补充语境'}`,'post-meta'));
    const images=el('div',undefined,'images');for(const image of post.local_images.filter(i=>i.status==='已保存')){const a=el('a');a.href='/media/'+image.relative_path;a.target='_blank';a.rel='noopener';const img=el('img');img.src=a.href;img.loading='lazy';img.alt='帖子内容图片，点击查看';a.append(img);images.append(a);}card.append(images);
    if(post.evidence?.screenshots?.length){const shots=el('div',undefined,'images');for(const shot of post.evidence.screenshots){const info=JSON.parse(shot.info_json||'{}');const link=el('a');link.href='/evidence/shots/'+shot.relative_path;link.target='_blank';link.rel='noopener';const img=el('img');img.src=link.href;img.loading='lazy';img.alt=`${shot.scope==='detail'?'详情':'列表'}截图 覆盖${Math.round((info.coverage||0)*100)}%`;img.style.cssText='width:160px;height:100px;object-fit:cover;object-position:top';link.append(img,el('span',img.alt,'muted'));shots.append(link);}card.append(shots);}
    if(post.visible_comments.length){const details=el('details');details.append(el('summary',`查看已采到的 ${post.visible_comments.length} 条评论文字`));for(const comment of post.visible_comments)details.append(el('p',comment.text,'comment'));card.append(details);}
    if(post.annotation.notes)card.append(el('p','复核备注：'+post.annotation.notes,'post-meta'));
    try{const url=new URL(post.url);if(url.hostname==='pd.qq.com'&&url.protocol==='https:'){const link=el('a','打开原帖核对','text-link');link.href=url.href;link.target='_blank';link.rel='noreferrer noopener';card.append(link);}}catch{}
    $('postList').append(card);
  }
  if(!result.posts.length)$('postList').append(el('p','当前筛选下等待资料导入。','muted'));
  $('pageNum').textContent=`${page} / ${Math.max(1,Math.ceil(total/30))}`;$('prev').disabled=page<=1;$('next').disabled=page*30>=total;
}
function openReview(post){selectedPost=post;$('reviewForm').reset();$('mainCategory').value='待判断';$('reviewId').textContent=post.id;$('reviewExcerpt').textContent=post.text;for(const[name,value]of Object.entries(post.annotation)){const control=$('reviewForm').elements.namedItem(name);if(control)control.value=value;}$('saveStatus').textContent='';$('reviewDialog').showModal();}
$('reviewForm').onsubmit=async event=>{event.preventDefault();try{const data=Object.fromEntries(new FormData(event.target));data.post_id=selectedPost.id;await api('/api/annotate',data);$('saveStatus').textContent='已保存到本地资料库。';await refresh();await loadPosts();}catch(error){$('saveStatus').textContent=error.message;}};
$('closeDialog').onclick=()=>$('reviewDialog').close();
for(const button of document.querySelectorAll('nav button'))button.onclick=async()=>{document.querySelectorAll('.tab').forEach(section=>section.hidden=section.id!==button.dataset.tab);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('selected',b===button));$('pageTitle').textContent=button.textContent==='资料概况'?'调研资料概况':button.textContent;if(button.dataset.tab==='posts')await loadPosts();};
$('searchButton').onclick=()=>{page=1;loadPosts().catch(error=>alert(error.message));};$('search').onkeydown=event=>{if(event.key==='Enter')$('searchButton').click();};
$('prev').onclick=()=>{page--;loadPosts();};$('next').onclick=()=>{page++;loadPosts();};
$('importFile').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>30*1024*1024)throw Error('请选择30MB以内的导出文件。');await api('/api/import',{filename:file.name,document:JSON.parse(await file.text()),stage:$('importStage').value,download_images:$('withImages').checked});busy=true;$('job').textContent='本批正在导入……';}catch(error){$('job').textContent=error.message;}finally{event.target.value='';}};
$('reviewCsvFile').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;const result=await api('/api/reviews',{csv_text:await file.text()});alert(`导入 ${result.accepted} 行；空类别或ID待核对 ${result.skipped} 行。`);await refresh();await loadPosts();}catch(error){alert(error.message);}finally{event.target.value='';}};
setInterval(async()=>{try{const job=await api('/api/job');$('job').textContent=job.message;if(busy&&!job.running){busy=false;await refresh();if(!$('posts').hidden)await loadPosts();}}catch{}},1500);
refresh().then(()=>$('job').textContent='资料已就绪，正式采集等你开始。').catch(error=>$('job').textContent=error.message);
async function captureProgress(){try{const s=await api('/api/collector/state');const run=s.run?JSON.parse(s.run.state_json):{};const live=run.running&&Date.now()-Date.parse(run.last_updated_at||s.run.updated_at)<60000;$('collectorState').textContent=`正式 ${s.formal_posts}/${s.target} 帖；截图 ${s.screenshots}，头像 ${s.saved_avatars}，图片队列 ${s.queued_images}。${run.phase||'等待浏览器开始'}${live?'':run.reason?' · '+run.reason:''} · 图像用量 ${(s.used_evidence_bytes/1e6).toFixed(1)}/${(s.budget_bytes/1e6).toFixed(0)} MB`;const model=await api('/api/model/state');$('modelState').textContent=`${model.phase} · ${model.processed}/${model.total}，已有候选 ${model.cached_labels} 帖 · ${model.cost}`;$('modelStart').disabled=model.running;$('modelStop').disabled=!model.running;}catch(error){$('collectorState').textContent=error.message;}}
$('stopCollect').onclick=()=>api('/api/capture-stop',{}).then(()=>captureProgress());
$('modelStart').onclick=()=>api('/api/model/start',{limit:Number($('modelLimit').value),stage:'正式'}).then(()=>captureProgress()).catch(error=>alert(error.message));
$('modelStop').onclick=()=>api('/api/model/stop',{}).then(()=>captureProgress());
captureProgress();setInterval(captureProgress,2500);setInterval(()=>refresh().catch(()=>{}),15000);

$('analysisExport').onclick=async()=>{const button=$('analysisExport');button.disabled=true;$('analysisStatus').textContent='正在固定当前资料并生成统计表……';try{const result=await api('/api/analysis/export',{});$('analysisStatus').textContent=`已保存：${result.folder}；正式 ${result.formal_posts} 帖，人工 ${result.manual_posts} 帖，模型候选 ${result.model_posts} 帖。`;}catch(error){$('analysisStatus').textContent=error.message;}finally{button.disabled=false;}};
$('resumeMedia').onclick=()=>api('/api/media/resume',{}).then(result=>$('analysisStatus').textContent=result.message+' 队列 '+result.queued+' 项。').catch(error=>$('analysisStatus').textContent=error.message);
async function backgroundProgress(){try{const s=await api('/api/background/state');$('backgroundState').textContent=`${s.phase}；${s.formal_posts||state?.stages?.['正式']||0}/${s.target||10000}帖；本轮详情${s.details||0}，评论文字${s.comments||0}。${s.reason||''}`;$('backgroundStart').disabled=s.running&&s.mode==='collect';$('backgroundLogin').disabled=s.running;$('backgroundStop').disabled=!s.running;$('sectionProgress').replaceChildren();for(const section of s.section_progress||[])metric($('sectionProgress'),section.name,`${section.seen}帖观察 / ${section.added}帖新增 · ${section.status}`);}catch(error){$('backgroundState').textContent=error.message;}}
$('backgroundLogin').onclick=()=>api('/api/background/login',{}).then(backgroundProgress).catch(error=>alert(error.message));
$('backgroundStart').onclick=()=>api('/api/background/start',{target:Number($('backgroundTarget').value),per_section:Number($('perSection').value),detail_every:Number($('backgroundDetail').value),workers:Number($('backgroundWorkers').value),screenshots:true}).then(backgroundProgress).catch(error=>alert(error.message));
$('backgroundStop').onclick=()=>api('/api/background/stop',{}).then(backgroundProgress).catch(error=>alert(error.message));
backgroundProgress();setInterval(backgroundProgress,2500);
