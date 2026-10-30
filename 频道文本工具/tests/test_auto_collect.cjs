const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const TOOL = path.resolve(__dirname, '../浏览器手动采集');
const URL = 'https://pd.qq.com/g/npu0lakeside';
const HTML = `<!doctype html><html><body>
<div class="vue-recycle-scroller" style="height:300px;overflow-y:auto">
  <a class="game-guild-main__short-content" href="/g/npu0lakeside/post/B_first" style="display:block;height:90px">
    <span class="feed-detail-text">第一条求助</span><span class="edit-time">1天前</span>
  </a><div style="height:1200px"></div>
</div>
<script>
const scroller=document.querySelector('.vue-recycle-scroller');
scroller.addEventListener('scroll',()=>{
  if(scroller.scrollTop>200){
    const card=scroller.querySelector('a');
    card.href='/g/npu0lakeside/post/B_second';
    card.querySelector('.feed-detail-text').textContent='第二条校园卡咨询';
  }
});
</script></body></html>`;

(async () => {
  const browser = await chromium.launch({ channel: process.env.QIXIANG_TEST_BROWSER_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      const data = { qixiang_auto_config_v1: { max_steps: 2, interval_ms: 1800 }, qixiang_auto_stop_v1: false };
      window.chrome = { storage: { local: {
        _data: data,
        async get(key) { return Object.fromEntries((Array.isArray(key) ? key : [key]).map(k => [k, data[k]])); },
        async set(values) { Object.assign(data, values); },
      } } };
    });
    await page.route('https://pd.qq.com/**', route => route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML }));
    await page.goto(URL);
    await page.addScriptTag({ path: path.join(TOOL, 'extractor.js') });
    await page.addScriptTag({ path: path.join(TOOL, 'catalog.js') });
    await page.addScriptTag({ path: path.join(TOOL, 'auto_collect.js') });
    await page.waitForFunction(() => window.chrome.storage.local._data.qixiang_auto_run_v1?.running === false, { timeout: 12000 });
    const state = await page.evaluate(() => window.chrome.storage.local._data);
    assert.equal(state.qixiang_auto_run_v1.steps_done, 2);
    assert.equal(state.qixiang_auto_run_v1.unique_posts, 2);
    assert.equal(state.qixiang_page_observations_v1.length, 2);
    assert.equal(state.qixiang_page_observations_v1[0].collection_mode, 'user_started_auto_scroll');
    assert.equal(state.qixiang_auto_run_v1.reason, '达到设定翻屏次数');
    await page.close();
    const stopped = await browser.newPage();
    await stopped.addInitScript(() => {
      const data = { qixiang_auto_config_v1: { max_steps: 10, interval_ms: 1800 }, qixiang_auto_stop_v1: false };
      window.chrome = { storage: { local: {
        _data: data,
        async get(key) { return Object.fromEntries((Array.isArray(key) ? key : [key]).map(k => [k, data[k]])); },
        async set(values) { Object.assign(data, values); },
      } } };
    });
    await stopped.route('https://pd.qq.com/**', route => route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML }));
    await stopped.goto(URL);
    await stopped.addScriptTag({ path: path.join(TOOL, 'extractor.js') });
    await stopped.addScriptTag({ path: path.join(TOOL, 'catalog.js') });
    await stopped.addScriptTag({ path: path.join(TOOL, 'auto_collect.js') });
    await stopped.waitForFunction(() => window.chrome.storage.local._data.qixiang_auto_run_v1?.steps_done >= 1);
    await stopped.evaluate(() => { window.chrome.storage.local._data.qixiang_auto_stop_v1 = true; });
    await stopped.waitForFunction(() => window.chrome.storage.local._data.qixiang_auto_run_v1?.running === false);
    const stoppedState = await stopped.evaluate(() => window.chrome.storage.local._data.qixiang_auto_run_v1);
    assert.equal(stoppedState.reason, '用户停止');
    await stopped.close();
    console.log('自动采集测试：逐屏滚动、去重、上限停止、用户停止与本机保存均通过。');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
