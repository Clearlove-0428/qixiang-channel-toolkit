const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium}=require('playwright');
const {screenFragments}=require('../background_capture.cjs');
(async()=>{
 const browser=await chromium.launch({channel:process.env.QIXIANG_TEST_BROWSER_CHANNEL||'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1200,height:850}});
  await context.addInitScript({path:path.resolve(__dirname,'../浏览器手动采集/time_utils.js')});
  await context.addInitScript({path:path.resolve(__dirname,'../浏览器手动采集/extractor.js')});
  const page=await context.newPage();
  await page.route('https://pd.qq.com/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`<style>.vue-recycle-scroller{height:600px;overflow:auto}.game-guild-main__short-content{display:block;height:260px;background:#eef}</style><div class="tab-bar__item is-active"><h3>失物</h3></div><div class="vue-recycle-scroller"><a class="game-guild-main__short-content" href="/g/npu0lakeside/post/B_test?subc=661248113"><span class="feed-detail-text">合成失物招领</span><span class="edit-time">5分钟前</span></a></div>`}));
  await page.goto('https://pd.qq.com/g/npu0lakeside?subc=661248113');
  assert.equal(await page.evaluate(()=>typeof extractRenderedChannelPage),'function');
  assert.equal(await page.evaluate(()=>typeof inferPostTime),'function');
  const raw=await page.evaluate(()=>extractRenderedChannelPage());assert.equal(raw.posts[0].board_id,'661248113');assert.equal(raw.posts[0].sampling_entry,'失物');
  const clips=await page.evaluate(screenFragments);assert.equal(clips.length,1);assert.equal(clips[0].post_id,'B_test');
  const image=await page.screenshot({type:'jpeg'});assert.ok(image.length>1000);
  console.log('后台浏览器：导航后函数可用，分区编号与入口分别记录，真实像素截图通过。');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
