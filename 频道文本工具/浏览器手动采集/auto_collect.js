void (async () => {
  const { DATA_KEY, INDEX_KEY } = QixiangCatalog;
  const RUN_KEY = 'qixiang_auto_run_v1', STOP_KEY = 'qixiang_auto_stop_v1';
  if (globalThis.__qixiangAutoRunning) return;
  globalThis.__qixiangAutoRunning = true;
  const startedAt = new Date().toISOString(), initialPage = location.pathname + location.search;
  let stepsDone = 0, added = 0, enriched = 0, totalKnown = 0, reason = '已停止';
  const skipped = new Set();
  const state = (running = true) => ({ running, started_at: startedAt,
    last_updated_at: new Date().toISOString(), source_page: location.origin + initialPage,
    steps_done: stepsDone, new_posts: added, enriched_posts: enriched,
    skipped_known_posts: skipped.size, unique_posts: totalKnown, reason });
  const update = async () => chrome.storage.local.set({ [RUN_KEY]: state() });
  const pause = async ms => {
    for (let elapsed = 0; elapsed < ms; elapsed += 250) {
      if ((await chrome.storage.local.get(STOP_KEY))[STOP_KEY]) return false;
      await new Promise(resolve => setTimeout(resolve, Math.min(250, ms - elapsed)));
    }
    return true;
  };
  try {
    if (location.hostname !== 'pd.qq.com' || location.pathname !== '/g/npu0lakeside')
      throw new Error('请在启翔湖畔的帖子列表页开始。');
    const scroller = [...document.querySelectorAll('.vue-recycle-scroller')]
      .find(el => el.querySelector('a.game-guild-main__short-content') && el.scrollHeight > el.clientHeight + 50);
    if (!scroller) throw new Error('帖子列表仍在加载，请稍后再开始。');
    const config = (await chrome.storage.local.get('qixiang_auto_config_v1')).qixiang_auto_config_v1 || {};
    const maxSteps = Math.max(2, Math.min(1000, Number(config.max_steps) || 200));
    const maxNew = Math.max(1, Math.min(500, Number(config.max_new) || 250));
    const interval = Math.max(1800, Math.min(8000, Number(config.interval_ms) || 2600));
    const index = await QixiangCatalog.load();
    const saved = (await chrome.storage.local.get(DATA_KEY))[DATA_KEY] || [];
    totalKnown = Object.keys(index.entries).length;
    let stalled = 0;
    await update();
    for (let step = 0; step < maxSteps; step++) {
      if ((await chrome.storage.local.get(STOP_KEY))[STOP_KEY]) { reason = '用户停止'; break; }
      if (location.pathname + location.search !== initialPage) { reason = '页面已切换'; break; }
      if (saved.reduce((sum, item) => sum + (item.posts?.length || 0), 0) >= 600) {
        reason = '本批已达600条新记录或补充，请导出并清空本批'; break;
      }
      if (chrome.storage.local.getBytesInUse && await chrome.storage.local.getBytesInUse(null) > 8 * 1024 * 1024) {
        reason = '浏览器暂存接近上限，请导出并清空本批'; break;
      }
      const raw = extractRenderedChannelPage();
      if (raw.error || raw.page_kind !== 'list' || !raw.posts.length) throw new Error(raw.error || '当前列表读取失败。');
      const selected = QixiangCatalog.select(raw, index);
      selected.snapshot.collection_mode = 'user_started_auto_scroll';
      selected.snapshot.sampling_entry = String(config.sampling_entry || '全部');
      selected.snapshot.posts = selected.snapshot.posts.map(post => ({ ...post, sampling_entry: selected.snapshot.sampling_entry }));
      selected.snapshot.run_id = startedAt;
      selected.snapshot.scroll_top = Math.round(scroller.scrollTop);
      selected.snapshot.scroll_height = Math.round(scroller.scrollHeight);
      selected.skipped.forEach(id => skipped.add(id));
      added += selected.added; enriched += selected.enriched; stepsDone++;
      totalKnown = Object.keys(index.entries).length;
      if (selected.snapshot.posts.length) {
        saved.push(selected.snapshot);
        await chrome.storage.local.set({ [DATA_KEY]: saved, [INDEX_KEY]: index });
      }
      await update();
      if (added >= maxNew) { reason = '达到本轮新帖目标'; break; }
      if (step + 1 >= maxSteps) { reason = '达到设定翻屏次数'; break; }
      const before = scroller.scrollTop;
      scroller.scrollTop = before + Math.max(320, Math.round(scroller.clientHeight * 0.9));
      scroller.dispatchEvent(new Event('scroll', { bubbles: true }));
      if (!(await pause(interval))) { reason = '用户停止'; break; }
      const noMovement = Math.abs(scroller.scrollTop - before) < 2;
      stalled = noMovement && selected.added === 0 ? stalled + 1 : 0;
      if (stalled >= 5) { reason = '列表停在底部或停止加载'; break; }
      // Already-known posts do not end the run: continue through the old section.
    }
  } catch (error) { reason = '错误：' + (error?.message || String(error)); }
  finally {
    await chrome.storage.local.set({ [RUN_KEY]: { ...state(false), ended_at: new Date().toISOString() } });
    globalThis.__qixiangAutoRunning = false;
  }
})();
