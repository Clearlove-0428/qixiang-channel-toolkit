void(async()=>{
  const send=async(path,data)=>{const r=await chrome.runtime.sendMessage({type:'qixiang-v3:bridge',path,data});if(r?.error)throw Error(r.error);return r.result;};
  let run;
  try{
    const snapshot=extractRenderedChannelPage();if(snapshot.error||!snapshot.posts?.length)throw Error(snapshot.error||'当前页面等待内容加载。');
    run=await send('start',{manual:true});await send('ingest',{run_id:run.run_id,sequence:0,posts:snapshot.posts});
    const root=document.querySelector('.game-guild-detail');
    if(root){const r=root.getBoundingClientRect(),x=Math.max(0,r.left),y=Math.max(0,r.top),w=Math.min(innerWidth,r.right)-x,h=Math.min(innerHeight,r.bottom)-y;
      if(w>80&&h>35){const response=await chrome.runtime.sendMessage({type:'qixiang-v3:screenshot',data:{captured_at:new Date().toISOString(),viewport_width:innerWidth,viewport_height:innerHeight,fragments:[{post_id:snapshot.posts[0].id,scope:'detail',x,y,width:w,height:h,offset:y-r.top,total_height:r.height}]}});if(response?.error)throw Error(response.error);}
    }
    await send('update',{run_id:run.run_id,state:{running:false,phase:'手动页面已保存',posts:snapshot.posts.length}});
    await chrome.storage.local.set({qixiang_manual_result:'当前页面已保存到本机资料库。'});
  }catch(error){await chrome.storage.local.set({qixiang_manual_result:error.message});}
})();
