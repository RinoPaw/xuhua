import { state, els } from './state.js';
import { escapeHtml } from './markdown.js';

let rightSearchTimer = 0;
let rightSearchRequestKey = "";

export function beginAskSessionRelated(requestId) {
  rightSearchRequestKey = `ask:${requestId}`;
}

export async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function itemTitle(item) {
  return item?.title || "未命名项目";
}

export function itemMetaParts(item, opts = {}) {
  const parts = [];
  const location = [item?.province, item?.city, item?.district].filter(Boolean).join(" · ");
  if (location) parts.push(location);
  const fields = [item?.category];
  if (!opts.skipLevel) fields.push(item?.level);
  for (const value of fields) {
    if (value && !parts.includes(value)) parts.push(value);
  }
  return parts;
}

export function itemTagList(item, limit = 4) {
  const tags = [];
  for (const form of item?.display_forms || []) {
    if (form && !tags.includes(form)) tags.push(form);
    if (tags.length >= limit) break;
  }
  return tags;
}

export async function loadRightSearchResults(requestKey, category = "") {
  try {
    const query = els.rightSearchInput?.value?.trim() || "";
    const params = new URLSearchParams({
      q: query,
      limit: "1000",
      stream: "1",
    });
    if (category) params.set("category", category);

    try {
      const response = await fetch(`/api/items?${params}`);
      if (!response.ok) throw new Error(`${response.status}`);
      if (requestKey !== rightSearchRequestKey) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (requestKey !== rightSearchRequestKey) {
          reader.cancel();
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.phase === "results") {
              renderRelatedItems(event.items, event.total);
            }
          } catch {
            // skip unparseable events
          }
        }
      }
    } catch {
      // SSE failed — fall back to plain JSON
      const plainParams = new URLSearchParams({ q: query, limit: "1000" });
      if (category) plainParams.set("category", category);
      try {
        const data = await fetchJson(`/api/items?${plainParams}`);
        if (requestKey !== rightSearchRequestKey) return;
        renderRelatedItems(data.items, data.total);
      } catch {
        if (requestKey === rightSearchRequestKey) {
          renderRelatedItems([]);
        }
      }
    }
  } finally {
    // done
  }
}

export function searchByCategory(category) {
  // Clear search input
  if (els.rightSearchInput) els.rightSearchInput.value = "";
  // Highlight active chip
  document.querySelectorAll(".marginalia-categories button").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.category === category);
  });
  const requestKey = `cat:${category}`;
  rightSearchRequestKey = requestKey;
  els.relatedCount.textContent = "检索中";
  els.relatedList.innerHTML = `<p class="marginalia-empty is-live">正在检索「${category}」</p>`;
  loadRightSearchResults(requestKey, category);
}

export function searchRightPanel() {
  const query = els.rightSearchInput?.value?.trim() || "";
  // Clear category active state
  document.querySelectorAll(".marginalia-categories button").forEach((btn) => btn.classList.remove("is-active"));
  if (!query) {
    renderRelatedItems([]);
    return;
  }
  const requestKey = query;
  rightSearchRequestKey = requestKey;
  els.relatedCount.textContent = "检索中";
  els.relatedList.innerHTML = `<p class="marginalia-empty is-live">正在检索</p>`;
  loadRightSearchResults(requestKey);
}

export function renderRelatedItems(items, total = items.length) {
  els.relatedCount.textContent = total ? `${total} 条` : "";
  els.relatedList.innerHTML = items.length
    ? items.map(itemButtonHtml).join("")
    : `<p class="marginalia-empty">没有匹配项目</p>`;
  // Click handler for items in the list
  els.relatedList.querySelectorAll(".item-entry[data-id]").forEach((el) => {
    el.addEventListener("click", () => showDetail(el.dataset.id));
  });
}

export function itemButtonHtml(item) {
  const summary = item.summary || "暂无摘要";
  const meta = itemMetaParts(item).join(" · ");
  const tags = itemTagList(item, 4);
  const title = itemTitle(item);
  return `
    <div class="item-entry" data-id="${escapeHtml(item.id)}" data-category="${escapeHtml(item.category)}">
      <div class="item-entry-head">
        <div class="item-entry-title">${escapeHtml(title)}</div>
      </div>
      ${meta ? `<div class="item-entry-meta">${escapeHtml(meta)}</div>` : ""}
      <div class="item-entry-summary">${escapeHtml(summary.slice(0, 74))}</div>
      ${tags.length ? `<div class="item-entry-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
    </div>
  `;
}

export async function showDetail(id) {
  try {
    const item = await fetchJson(`/api/items/${encodeURIComponent(id)}`);
    els.detailCategory.textContent = item.category;
    els.detailTitle.textContent = itemTitle(item);
    els.detailMeta.innerHTML = detailMetaHtml(item);
    const support = detailSupportText(item);
    els.detailSupport.hidden = !support;
    els.detailSupport.textContent = support;
    els.detailBody.textContent = item.content || "暂无原文。";
    els.searchMode.hidden = true;
    els.detailMode.hidden = false;
  } catch {
    // silently fail if item not found
  }
}

export function hideDetail() {
  els.detailMode.hidden = true;
  els.searchMode.hidden = false;
  els.detailCategory.textContent = "";
  els.detailTitle.textContent = "";
  els.detailMeta.innerHTML = "";
  els.detailSupport.hidden = true;
  els.detailBody.textContent = "";
}

function detailMetaHtml(item) {
  const parts = [];
  const location = [item?.province, item?.city, item?.district].filter(Boolean).join(" · ");
  if (location) parts.push(location);
  for (const value of [item?.category, item?.level]) {
    if (value && !parts.includes(value)) parts.push(value);
  }
  return parts.map((p) => `<span>${escapeHtml(p)}</span>`).join("");
}

function detailSupportText(item) {
  if (item?.suitable_scenarios?.length) {
    return `适用场景：${item.suitable_scenarios.slice(0, 3).join("、")}`;
  }
  return "";
}

export function relatedPanelTitle() {
  return "资料检索";
}

export function updateRelatedPanelTitle() {
  if (els.relatedTitle) {
    els.relatedTitle.textContent = "资料检索";
  }
}
