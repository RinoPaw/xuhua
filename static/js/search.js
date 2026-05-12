import { state, els } from './state.js';
import { escapeHtml } from './markdown.js';

let relatedTimer = 0;
let relatedRequestKey = "";
let inFlightKey = "";

export function cancelRelatedSearch() {
  window.clearTimeout(relatedTimer);
}

export function beginAskSessionRelated(requestId) {
  cancelRelatedSearch();
  relatedRequestKey = `ask:${requestId}`;
  inFlightKey = "";
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

export function itemMetaParts(item) {
  const parts = [];
  for (const value of [item?.category, item?.family, item?.level]) {
    if (value && !parts.includes(value)) parts.push(value);
  }
  const location = [item?.province, item?.city].filter(Boolean).join(" · ");
  if (location) parts.push(location);
  return parts;
}

export function itemTagList(item, limit = 4) {
  const tags = [];
  for (const form of item?.display_forms || []) {
    if (form && !tags.includes(form)) tags.push(form);
    if (tags.length >= limit) break;
  }
  for (const keyword of item?.cultural_keywords || []) {
    if (keyword && !tags.includes(keyword)) tags.push(keyword);
    if (tags.length >= limit) break;
  }
  return tags;
}

export async function loadRelatedItems(requestKey = relatedRequestKey) {
  inFlightKey = requestKey;
  try {
    const query = state.query;
    const params = new URLSearchParams({
      q: query,
      limit: "8",
      stream: "1",
    });

    try {
      const response = await fetch(`/api/items?${params}`);
      if (!response.ok) throw new Error(`${response.status}`);
      if (requestKey !== relatedRequestKey || query !== state.query) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (requestKey !== relatedRequestKey || query !== state.query) {
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
            if (event.phase === "lexical" || event.phase === "hybrid") {
              renderRelatedItems(event.items, event.total);
            }
          } catch {
            // skip unparseable events
          }
        }
      }
    } catch {
      // SSE failed — fall back to plain JSON
      const plainParams = new URLSearchParams({ q: query, limit: "8" });
      try {
        const data = await fetchJson(`/api/items?${plainParams}`);
        if (requestKey !== relatedRequestKey || query !== state.query) return;
        renderRelatedItems(data.items, data.total);
      } catch {
        if (requestKey === relatedRequestKey && query === state.query) {
          renderRelatedItems([]);
        }
      }
    }
  } finally {
    if (inFlightKey === requestKey) {
      inFlightKey = "";
    }
  }
}

export function renderRelatedItems(items, total = items.length) {
  updateRelatedPanelTitle();
  els.relatedCount.textContent = state.query ? `${total} 条` : "";
  els.relatedList.innerHTML = items.length
    ? items.map(itemButtonHtml).join("")
    : `<p class="marginalia-empty">${state.query ? "没有匹配条目" : "暂无相关条目"}</p>`;
  els.relatedList.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === state.selectedId);
    button.addEventListener("click", () => loadDetail(button.dataset.id, true));
  });
}

export function itemButtonHtml(item) {
  const summary = item.summary || "暂无摘要";
  const meta = itemMetaParts(item).join(" · ");
  const tags = itemTagList(item, 4);
  const title = itemTitle(item);
  return `
    <button class="item-entry" type="button" data-id="${escapeHtml(item.id)}" data-category="${escapeHtml(item.category)}">
      <div class="item-entry-head">
        <div class="item-entry-title">${escapeHtml(title)}</div>
        <div class="item-entry-action">查看详情</div>
      </div>
      ${meta ? `<div class="item-entry-meta">${escapeHtml(meta)}</div>` : ""}
      <div class="item-entry-summary">${escapeHtml(summary.slice(0, 74))}</div>
      ${tags.length ? `<div class="item-entry-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
    </button>
  `;
}

export async function loadDetail(id, shouldFocus = false) {
  state.selectedId = id;
  els.relatedList.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === id);
  });

  const item = await fetchJson(`/api/items/${encodeURIComponent(id)}`);
  els.detailEmpty.hidden = true;
  els.detailContent.hidden = false;
  els.detailCategory.textContent = item.category;
  els.detailCategory.setAttribute("data-category", item.category);
  els.detailTitle.textContent = itemTitle(item);
  els.detailMeta.innerHTML = detailCardMeta(item);
  const support = detailSupportText(item);
  els.detailSupport.hidden = !support;
  els.detailSupport.textContent = support;
  els.detailSummary.textContent = item.summary || "暂无摘要。";
  els.detailBody.textContent = item.content || "暂无原文。";

  if (shouldFocus && window.matchMedia("(max-width: 760px)").matches) {
    els.detailPanel.scrollIntoView({ block: "start" });
  }
}

export function clearDetail() {
  els.detailEmpty.hidden = false;
  els.detailContent.hidden = true;
  els.detailCategory.textContent = "";
  els.detailTitle.textContent = "";
  els.detailMeta.innerHTML = "";
  els.detailSupport.hidden = true;
  els.detailSupport.textContent = "";
  els.detailSummary.textContent = "";
  els.detailBody.textContent = "";
}

export function updateRelatedItems() {
  const newQuery = els.questionInput.value.trim();
  state.query = newQuery;
  state.selectedId = "";
  state.currentTaskType = "";
  els.relatedList.querySelectorAll("button").forEach((button) => button.classList.remove("active"));
  clearDetail();
  updateRelatedPanelTitle();

  window.clearTimeout(relatedTimer);
  if (!newQuery) {
    relatedRequestKey = "";
    renderRelatedItems([]);
    return;
  }

  if (newQuery === inFlightKey) {
    relatedRequestKey = newQuery;
    return;
  }

  relatedRequestKey = newQuery;
  els.relatedCount.textContent = "思考中";
  els.relatedList.innerHTML = `<p class="marginalia-empty is-live">正在思考</p>`;
  relatedTimer = window.setTimeout(() => {
    loadRelatedItems(newQuery);
  }, 1000);
}

export function relatedPanelTitle(taskType = state.currentTaskType) {
  if (!state.query) {
    return "相关资料";
  }
  const titles = {
    browse_query: "匹配项目",
    comparison: "对比项目",
    recommendation: "候选项目",
    exhibition_plan: "候选项目",
    study_task: "候选项目",
    content_transform: "相关项目",
    fact_qa: "相关资料",
    chitchat: "相关资料",
  };
  return titles[taskType] || "匹配项目";
}

export function updateRelatedPanelTitle(taskType = state.currentTaskType) {
  if (els.relatedTitle) {
    els.relatedTitle.textContent = relatedPanelTitle(taskType);
  }
}

export function detailCardMeta(item) {
  const tags = [];
  for (const value of [item?.category, item?.family, item?.level, item?.province, item?.city]) {
    if (value && !tags.includes(value)) {
      tags.push(value);
    }
  }
  for (const form of item?.display_forms || []) {
    if (form && !tags.includes(form)) {
      tags.push(form);
    }
    if (tags.length >= 7) break;
  }
  for (const keyword of item?.cultural_keywords || []) {
    if (keyword && !tags.includes(keyword)) {
      tags.push(keyword);
    }
    if (tags.length >= 10) break;
  }
  return tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
}

export function detailSupportText(item) {
  const parts = [];
  if (item?.suitable_scenarios?.length) {
    parts.push(`适用场景：${item.suitable_scenarios.slice(0, 3).join("、")}`);
  }
  if (item?.target_audience?.length) {
    parts.push(`适合人群：${item.target_audience.slice(0, 3).join("、")}`);
  }
  if (item?.education_value) {
    parts.push(`教育价值：${item.education_value}`);
  }
  if (item?.interaction_potential) {
    parts.push(`互动潜力：${item.interaction_potential}`);
  }
  return parts.join(" · ");
}
