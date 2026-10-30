const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { extractRenderedChannelPage } = require('../浏览器手动采集/extractor.js');

const ORIGIN = 'https://pd.qq.com/g/npu0lakeside';

async function syntheticPage(browser, path, html) {
  const page = await browser.newPage();
  await page.route('https://pd.qq.com/**', route => route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html }));
  await page.goto(ORIGIN + path);
  return page;
}

(async () => {
  const browser = await chromium.launch({ channel: process.env.QIXIANG_TEST_BROWSER_CHANNEL || 'msedge', headless: true });
  try {
    const list = await syntheticPage(browser, '?tab=1&subc=hot&token=secret', `
      <a class="game-guild-main__short-content" href="/g/npu0lakeside/post/B_test01">
        <span class="edit-time">2天前</span><span class="feed-detail-text">求助联系 13812345678</span>
        <span class="game-guild-main__short-content__comment">12</span>
      </a>
      <a class="game-guild-main__short-content" href="/g/npu0lakeside/post/B_test02">
        <span class="edit-time">2026-10-12</span><span class="feed-detail-text">办事咨询</span>
        <div class="short-feed-image__placeholder"><img src="https://channel.qpic.cn/post-image-1.jpg" width="640" height="400"></div>
        <span class="game-guild-main__short-content__comment">1.2万</span>
      </a>`);
    const listResult = await list.evaluate(extractRenderedChannelPage);
    assert.equal(listResult.posts.length, 2);
    assert.equal(listResult.posts[0].text, '求助联系 [联系方式]');
    assert.equal(listResult.posts[0].created_at, null);
    assert.equal(listResult.posts[0].comment_count, 12);
    assert.equal(listResult.posts[1].created_at, '2026-10-12');
    assert.equal(listResult.posts[1].comment_count, null);
    assert.equal(listResult.posts[0].preview_only, true);
    assert.equal(listResult.posts[1].image_count, 1);
    assert.match(listResult.posts[1].images[0].url, /post-image-1/);
    assert.equal(listResult.page_tab_hint, 'hot');
    assert.doesNotMatch(JSON.stringify(listResult), /secret/);
    await list.close();

    const detail = await syntheticPage(browser, '/post/B_test02?subc=hot', `
      <div class="game-guild-detail">
        <div class="short-feed-image__placeholder"><img src="https://channel.qpic.cn/detail-image.jpg" width="800" height="600"></div>
        <div class="feed-content">
          <p class="feed-detail-text">办事咨询，邮箱 ab@example.com</p>
          <div class="comment-list-item">
            <span class="comment-list-item__info__title-time">1天前</span>
            <div class="comment-richcontent"><span class="feed-detail-text">带上学生证办理</span></div>
          </div>
        </div>
        <div class="feed-info__detail__time">2026-10-12 09:30</div>
        <div class="bottom-right"><span class="comment-text">8</span></div>
      </div>`);
    const detailResult = await detail.evaluate(extractRenderedChannelPage);
    assert.equal(detailResult.page_kind, 'detail');
    assert.equal(detailResult.posts.length, 1);
    assert.equal(detailResult.posts[0].text, '办事咨询，邮箱 [联系方式]');
    assert.equal(detailResult.posts[0].created_at, '2026-10-12T09:30+08:00');
    assert.equal(detailResult.posts[0].preview_only, false);
    assert.equal(detailResult.posts[0].comment_count, 8);
    assert.equal(detailResult.posts[0].image_count, 1);
    assert.equal(detailResult.posts[0].visible_comment_count, 1);
    assert.equal(detailResult.posts[0].visible_comments[0].text, '带上学生证办理');
    assert.doesNotMatch(detailResult.posts[0].text, /学生证/);
    await detail.close();

    const loading = await syntheticPage(browser, '/post/B_loading', '<a class="game-guild-main__short-content" href="/g/npu0lakeside/post/B_other">背景列表</a>');
    assert.match((await loading.evaluate(extractRenderedChannelPage)).error, /详情仍在加载/);
    await loading.close();

    const wrong = await syntheticPage(browser, '/../somewhere', '<p>其他页面</p>');
    const wrongResult = await wrong.evaluate(extractRenderedChannelPage);
    assert.match(wrongResult.error, /启翔湖畔/);
    await wrong.close();

    console.log('浏览器 DOM 采集测试：列表、详情、相对日期、联系方式遮蔽、非目标页均通过。');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
