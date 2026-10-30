/* Executed only after a user clicks the extension button. No network or account APIs. */
function extractRenderedChannelPage() {
  const now = new Date().toISOString();
  const pageAge = Math.round((performance?.now?.() || 0) / 1000);
  const current = new URL(location.href);
  if (current.hostname !== "pd.qq.com" ||
      !(current.pathname === "/g/npu0lakeside" || current.pathname.startsWith("/g/npu0lakeside/"))) {
    return { error: "请先打开“启翔湖畔-西北工业大学”的频道网页。" };
  }

  const clean = (value) => String(value || "").replace(/[\u200b-\u200d\ufeff]/g, "").replace(/[ \t\r\f\v]+/g, " ").trim();
  const redact = (value) => clean(value)
    .replace(/(?<!\d)1[3-9]\d{9}(?!\d)/g, "[联系方式]")
    .replace(/(?<![A-Za-z0-9_.+-])[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g, "[联系方式]")
    .replace(/\bQQ\s*(?:号码|号|群号|群)?\s*[:：=]?\s*[1-9]\d{4,11}(?!\d)/gi, "[联系方式]");
  const exactCount = (value) => {
    const s = clean(value);
    return /^[\d,]+$/.test(s) ? Number(s.replace(/,/g, "")) : null;
  };
  const fullDate = (label) => {
    const s = clean(label);
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?$/.test(s)) return s.replace(/\s+/, "T") + "+08:00";
    return null;
  };
  const timing = label => typeof inferPostTime === 'function' ? inferPostTime(label, now, pageAge) : {};
  const avatarIn = node => {
    const image = [...node.querySelectorAll('.avatar img')].find(el => !el.closest('.comment-list-item'));
    try { const url = new URL(image?.currentSrc || image?.src); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
  };
  const activeEntry = clean(document.querySelector('.tab-bar__item.is-active')?.textContent) || null;
  const safePageUrl = (url) => {
    const query = new URLSearchParams();
    for (const key of ["tab", "subc"]) {
      const value = url.searchParams.get(key);
      if (value && /^[A-Za-z0-9_-]{1,40}$/.test(value)) query.set(key, value);
    }
    return url.origin + url.pathname + (query.size ? "?" + query.toString() : "");
  };
  const postInfo = (href) => {
    try {
      const url = new URL(href, location.href);
      if (url.hostname !== "pd.qq.com") return null;
      const match = url.pathname.match(/^\/g\/npu0lakeside\/post\/([A-Za-z0-9_]+)\/?$/);
      const native=url.searchParams.get('subc');
      return match ? { id: match[1], url: safePageUrl(url),board_id:/^\d{1,15}$/.test(native||'')?native:null } : null;
    } catch { return null; }
  };
  const textIn = (node, selector, maxChars, omitComments = false) => {
    const texts = [...node.querySelectorAll(selector)]
      .filter(el => !omitComments || !el.closest(".comment-list-item"))
      .map(el => redact(el.textContent)).filter(Boolean);
    const text = texts.join("");
    return { text: text.slice(0, maxChars), truncated: text.length > maxChars };
  };
  const imagesIn = (node, selector) => {
    const found = [];
    const seen = new Set();
    for (const img of node.querySelectorAll(selector)) {
      if (img.closest(".avatar, .comment-list-item, .short-feed-emoji")) continue;
      const raw = img.currentSrc || img.getAttribute("src") || img.getAttribute("data-src");
      try {
        const url = new URL(raw, location.href);
        if (url.protocol !== "https:" || url.href.length > 4096 || seen.has(url.href)) continue;
        seen.add(url.href);
        found.push({ url: url.href,
          width: img.naturalWidth || Number(img.getAttribute("width")) || null,
          height: img.naturalHeight || Number(img.getAttribute("height")) || null,
          source: "rendered_post_image" });
      } catch { /* Ignore placeholders without a usable image address. */ }
      if (found.length >= 12) break;
    }
    return found;
  };
  const commentsIn = (node) => {
    const comments = [];
    for (const item of node.querySelectorAll(".comment-list-item")) {
      const rich = [...item.querySelectorAll(".comment-richcontent .feed-detail-text")]
        .filter(el => el.closest(".comment-list-item") === item)
        .map(el => redact(el.textContent)).filter(Boolean).join("");
      if (!rich) continue;
      comments.push({ order_on_page: comments.length + 1, text: rich.slice(0, 1200),
        displayed_time_label: clean(item.querySelector(".comment-list-item__info__title-time")?.textContent) || null });
      if (comments.length >= 120) break;
    }
    return comments;
  };

  const detailInfo = postInfo(current.href);
  if (detailInfo) {
    const detailRoot = document.querySelector(".game-guild-detail");
    const detailNode = detailRoot?.querySelector(".feed-content");
    if (!detailNode) return { error: "帖子详情仍在加载，请稍等后再记录；本次没有保存列表卡片。" };
    const body = textIn(detailNode, ".feed-detail-text", 12000, true);
    const images = imagesIn(detailRoot, ".short-feed-image__placeholder img, .feed-content img");
    const comments = commentsIn(detailRoot);
    const dateLabel = clean(detailRoot.querySelector(".feed-info__detail__time")?.textContent);
    const commentLabel = clean(detailRoot.querySelector(".bottom-right .comment-text")?.textContent);
    return { source_page: safePageUrl(current), captured_at: now, page_kind: "detail",
      displayed_cards_in_dom: 0, skipped_invalid_links: 0,
      posts: [{ ...detailInfo, title: "", text: body.text, created_at: fullDate(dateLabel),
        displayed_date_label: dateLabel || null, comment_count: exactCount(commentLabel),
        comment_count_basis: "user_triggered_rendered_page_snapshot", comment_count_as_of: now,
        displayed_comment_label: commentLabel || null, board: "", preview_only: false,
        text_source: "user_triggered_rendered_detail_dom", text_truncated_by_tool: body.truncated,
        ...timing(dateLabel), author_avatar_url:avatarIn(detailRoot), page_age_seconds:pageAge,
        sampling_entry:activeEntry, images, image_count: images.length, visible_comments: comments,
        visible_comment_count: comments.length, comments_scope: "rendered_dom_at_capture",
        captured_at: now, source_page: safePageUrl(current) }],
      coverage: "手动打开的这一个帖子详情；图片为页面中已呈现的地址，评论只含当前页面已呈现的文字" };
  }

  const posts = [];
  let skipped = 0;
  const cardNodes = [...document.querySelectorAll("a.game-guild-main__short-content[href*='/post/']")];
  for (const card of cardNodes.slice(0, 150)) {
    if (!card.getClientRects().length) continue;
    const info = postInfo(card.href);
    if (!info) { skipped++; continue; }
    const body = textIn(card, ".feed-detail-text", 1200);
    const images = imagesIn(card, ".short-feed-image__placeholder img");
    const dateLabel = clean(card.querySelector(".edit-time")?.textContent);
    const commentLabel = clean(card.querySelector(".game-guild-main__short-content__comment")?.textContent);
    posts.push({ ...info, title: "", text: body.text, created_at: fullDate(dateLabel),
      displayed_date_label: dateLabel || null, comment_count: exactCount(commentLabel),
      comment_count_basis: "user_triggered_rendered_page_snapshot", comment_count_as_of: now,
      displayed_comment_label: commentLabel || null, board: "", preview_only: true,
      text_source: "user_triggered_rendered_list_dom", text_truncated_by_tool: body.truncated,
      ...timing(dateLabel), author_avatar_url:avatarIn(card), page_age_seconds:pageAge,
      sampling_entry:activeEntry, images, image_count: images.length, visible_comments: [], visible_comment_count: 0,
      comments_scope: "not_collected_from_list",
      captured_at: now, source_page: safePageUrl(current) });
  }
  return { source_page: safePageUrl(current), captured_at: now, page_kind: "list",
    page_tab_hint: current.searchParams.get("subc") || null, displayed_cards_in_dom: cardNodes.length,
    skipped_invalid_links: skipped, posts,
    coverage: "手动点击时网页已呈现的主帖卡片或详情；未验证任何日期范围全量，也未采集评论正文" };
}

if (typeof globalThis !== 'undefined') globalThis.extractRenderedChannelPage = extractRenderedChannelPage;
if (typeof module !== "undefined" && module.exports) module.exports = { extractRenderedChannelPage };
