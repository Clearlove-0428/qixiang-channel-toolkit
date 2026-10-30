/* Persistent post IDs are independent of the export batch. */
globalThis.QixiangCatalog = (() => {
  const INDEX_KEY = 'qixiang_seen_index_v2';
  const DATA_KEY = 'qixiang_page_observations_v1';
  const hash = value => {
    let h = 2166136261;
    for (const ch of String(value)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(16);
  };
  const validId = id => typeof id === 'string' && /^B_[A-Za-z0-9_]{1,150}$/.test(id);
  const meta = post => ({
    first_seen: post.captured_at || new Date().toISOString(),
    has_detail: post.preview_only === false,
    images: [...new Set((post.images || []).map(im => hash(im.url)))].slice(0, 12),
    detail_hash: post.preview_only === false ? hash(JSON.stringify([
      post.text, (post.visible_comments || []).map(c => c.text)])) : null,
  });
  function seed(index, post) {
    if (!validId(post?.id)) return;
    const next = meta(post), old = index.entries[post.id];
    if (!old) index.entries[post.id] = next;
    else {
      old.images = [...new Set([...(old.images || []), ...next.images])].slice(0, 24);
      if (next.has_detail) { old.has_detail = true; old.detail_hash = next.detail_hash; }
    }
  }
  async function load() {
    const result = await chrome.storage.local.get([INDEX_KEY, DATA_KEY]);
    const index = result[INDEX_KEY]?.schema === 'qixiang_seen_index_v2'
      ? result[INDEX_KEY] : { schema: 'qixiang_seen_index_v2', entries: {} };
    for (const observation of result[DATA_KEY] || []) for (const post of observation.posts || []) seed(index, post);
    await chrome.storage.local.set({ [INDEX_KEY]: index });
    return index;
  }
  function select(snapshot, index) {
    const selected = [], skipped = [];
    let added = 0, enriched = 0;
    for (const post of snapshot.posts || []) {
      if (!validId(post.id)) continue;
      const old = index.entries[post.id], next = meta(post);
      const hasNewImage = next.images.some(value => !(old?.images || []).includes(value));
      const hasDetailUpdate = next.has_detail && (!old?.has_detail || old.detail_hash !== next.detail_hash);
      if (!old || hasNewImage || hasDetailUpdate) {
        selected.push({ ...post, record_kind: old ? 'supplement' : 'new' });
        if (old) enriched++; else added++;
        seed(index, post);
      } else skipped.push(post.id);
    }
    return { snapshot: { ...snapshot, posts: selected }, added, enriched, skipped };
  }
  function mergeImported(index, incoming) {
    if (incoming?.schema === 'qixiang_seen_index_v2' && incoming.entries && typeof incoming.entries === 'object') {
      for (const [id, item] of Object.entries(incoming.entries).slice(0, 20000)) {
        if (!validId(id)) continue;
        const old = index.entries[id];
        const clean = { first_seen: String(item?.first_seen || ''), has_detail: Boolean(item?.has_detail),
          detail_hash: typeof item?.detail_hash === 'string' ? item.detail_hash.slice(0, 32) : null,
          images: Array.isArray(item?.images) ? item.images.filter(x => typeof x === 'string').map(x => x.slice(0, 32)).slice(0, 24) : [] };
        if (!old) index.entries[id] = clean;
        else { old.images = [...new Set([...(old.images || []), ...clean.images])].slice(0, 24); old.has_detail ||= clean.has_detail; }
      }
    } else if (Array.isArray(incoming?.posts)) for (const post of incoming.posts) seed(index, post);
    else throw new Error('请选择本工具导出的去重索引或页面观察 JSON。');
    return index;
  }
  return { INDEX_KEY, DATA_KEY, hash, load, select, mergeImported };
})();
