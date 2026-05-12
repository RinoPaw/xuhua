const state = {
  query: "",
  selectedId: "",
  currentTaskType: "",
  lastAskContext: null,
};

const relatedList = document.querySelector("#relatedList");
const relatedCount = document.querySelector("#relatedCount");
const relatedTitle = document.querySelector("#relatedTitle");
const metaText = document.querySelector("#metaText");
const detailEmpty = document.querySelector("#detailEmpty");
const detailContent = document.querySelector("#detailContent");
const detailPanel = document.querySelector(".marginalia");
const detailCategory = document.querySelector("#detailCategory");
const detailTitle = document.querySelector("#detailTitle");
const detailMeta = document.querySelector("#detailMeta");
const detailSupport = document.querySelector("#detailSupport");
const detailSummary = document.querySelector("#detailSummary");
const detailBody = document.querySelector("#detailBody");
const questionInput = document.querySelector("#questionInput");
const querySuggestions = document.querySelector("#querySuggestions");
const askButton = document.querySelector("#askButton");
const voiceToggle = document.querySelector("#voiceToggle");
const voiceStatus = document.querySelector("#voiceStatus");
const answerBox = document.querySelector("#answerBox");
const answerMode = document.querySelector("#answerMode");
const digitalHumanPanel = document.querySelector(".hanging-scroll");
const digitalHumanVideo = document.querySelector("#digitalHumanVideo");
const digitalHumanVideoNext = document.querySelector("#digitalHumanVideoNext");
const digitalHumanStatus = document.querySelector("#digitalHumanStatus");
const digitalHumanSpeech = document.querySelector("#digitalHumanSpeech");

const humanVideos = {
  idle: ["/static/media/wait1.mp4", "/static/media/wait2.mp4"],
  thinking: ["/static/media/greet1.mp4"],
  speaking: ["/static/media/speak1.mp4", "/static/media/speak2.mp4", "/static/media/speak3.mp4"],
  farewell: ["/static/media/thanksandbye.mp4"],
};
const humanVideoIndexes = {};

let humanIdleTimer = 0;
let humanLoopTimer = 0;
let humanTransitionTimer = 0;
let humanDissolveTimer = 0;
let humanTransitionSeq = 0;
let currentHumanState = "idle";
let activeHumanVideo = digitalHumanVideo;
let standbyHumanVideo = digitalHumanVideoNext;
let currentUtterance = null;
let currentSpeechAudio = null;
let currentSpeechSegments = [];
let lastSpeechText = "";
let lastSpeechAudioUrl = "";
let speechPlaybackSeq = 0;
let speechUnlocked = false;
let speechCancelTimer = 0;
let speechStartGuardTimer = 0;
let voiceState = "idle"; // idle | speaking | disabled
let lastSpeechHumanState = "speaking";
let loadingStepTimer = 0;
let loadingFlushTimer = 0;
let loadingStepIndex = 0;
let loadingTargetIndex = 0;
let loadingStepStartedAt = 0;
let loadingProgressQueue = [];
let loadingFlushResolvers = [];
let askAbortController = null;
let askRequestId = 0;

const defaultSuggestionQueries = [
  "汴绣是什么？",
  "河南有哪些传统美术类非遗？",
  "四川皮影和湖北皮影有什么区别？",
  "推荐适合校园展示的河南非遗项目",
  "给朱仙镇木版年画生成讲解词",
  "适合社区活动展示的非遗有哪些？",
];
const followupQueriesByTask = {
  fact_qa: [
    "这个项目更适合校园展示还是社区活动？",
    "它和同类非遗有什么区别？",
    "帮我把它改成适合讲解的口语版",
  ],
  browse_query: [
    "从这些项目里推荐 3 个适合校园展示的",
    "把这些项目按展示难度做个比较",
    "帮我从中挑适合社区活动的项目",
  ],
  comparison: [
    "把这两个项目整理成展板讲解词",
    "推荐更适合校园展示的那个",
    "再加入一个同类项目一起比较",
  ],
  recommendation: [
    "基于这些推荐生成校园展示策划",
    "给每个推荐项目写一句推荐理由",
    "把推荐结果改成适合播报的讲解词",
  ],
  exhibition_plan: [
    "把这个方案压缩成 3 分钟讲解流程",
    "继续生成互动问题和研学任务",
    "改成适合社区活动的版本",
  ],
  study_task: [
    "再补 3 个课堂互动问题",
    "改成适合小学生的版本",
    "把这份任务单压缩成 15 分钟活动",
  ],
  content_transform: [
    "再生成一个更年轻化的版本",
    "改成双语传播文案",
    "基于这个项目再推荐几个相关非遗",
  ],
  chitchat: [
    "推荐适合校园展示的河南非遗项目",
    "四川皮影和湖北皮影有什么区别？",
    "河南有哪些传统美术类非遗？",
  ],
};

const browserSpeechSupported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
const audioSpeechSupported = typeof Audio !== "undefined";
const speechSupported = browserSpeechSupported || audioSpeechSupported;
const PROGRESS_STEP_INDEX = {
  classify: 0,
  search: 1,
  generate: 2,
  speech: 3,
};
const loadingSteps = [
  { title: "理解问题", detail: "正在判断任务类型，并识别项目名称、地区和输出要求" },
  { title: "检索资料", detail: "正在检索资料库，优先匹配明确标题和结构化字段" },
  { title: "思考回答", detail: "正在整理证据、取舍资料，并生成回答文本" },
  { title: "润色播报", detail: "正在清理为更适合朗读的同稿版本" },
];
let activeLoadingSteps = [...loadingSteps];
const HUMAN_MIN_THINKING_MS = 1120;
const HUMAN_DISSOLVE_LEAD_MS = 1050;
const LOADING_MIN_STEP_MS = 500;

stopSpeech({ delayed: true, preserveHuman: true });
window.addEventListener("pagehide", () => stopSpeech({ delayed: true }));
window.addEventListener("beforeunload", () => stopSpeech({ delayed: true }));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopSpeech({ delayed: true });
  }
});

voiceToggle?.addEventListener("click", () => {
  if (!speechSupported) {
    setVoiceStatus("浏览器不支持语音");
    return;
  }
  if (voiceState === "speaking") {
    stopSpeech();
    setVoiceStatus("已停止");
    return;
  }
  if (!lastSpeechText) {
    setVoiceStatus("暂无可播报内容");
    return;
  }
  if (currentHumanState !== "speaking" && currentHumanState !== "farewell") {
    setDigitalHumanState(lastSpeechHumanState, "正在回答", lastSpeechText);
  }
  unlockSpeech();
  if (lastSpeechAudioUrl) {
    playAudioAnswer(lastSpeechAudioUrl, lastSpeechText);
  } else {
    speakText(lastSpeechText);
  }
});
window.speechSynthesis?.addEventListener?.("voiceschanged", () => {
  window.speechSynthesis.getVoices();
});

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setAnswerState(stateName) {
  answerBox.classList.remove("is-idle", "is-loading", "is-error");
  if (stateName) {
    answerBox.classList.add(`is-${stateName}`);
  }
}

function setAnswerPlain(value, stateName = "") {
  stopLoadingSteps();
  answerBox.classList.remove("markdown-answer", "result-answer");
  setAnswerState(stateName);
  answerBox.textContent = value;
}

function setAnswerMarkdown(value) {
  stopLoadingSteps();
  setAnswerState("");
  answerBox.classList.remove("result-answer");
  answerBox.classList.add("markdown-answer");
  answerBox.innerHTML = renderMarkdown(value);
}

function setAnswerResult(question, payload) {
  stopLoadingSteps();
  setAnswerState("");
  answerBox.classList.remove("markdown-answer");
  answerBox.classList.add("result-answer");
  answerBox.innerHTML = renderResultAnswer(question, payload);
  bindQueryChips(answerBox);
  bindResultItemLinks(answerBox);
}

function startLoadingSteps() {
  window.clearTimeout(loadingStepTimer);
  window.clearTimeout(loadingFlushTimer);
  loadingStepTimer = 0;
  loadingFlushTimer = 0;
  activeLoadingSteps = getLoadingSteps();
  loadingStepIndex = 0;
  loadingTargetIndex = 0;
  loadingStepStartedAt = performance.now();
  loadingProgressQueue = [];
  resolveLoadingFlush();
  setAnswerLoading(loadingStepIndex);
}

function getLoadingSteps() {
  return loadingSteps.map((step) => ({ ...step }));
}

function stopLoadingSteps() {
  window.clearTimeout(loadingStepTimer);
  window.clearTimeout(loadingFlushTimer);
  loadingStepTimer = 0;
  loadingFlushTimer = 0;
  loadingStepIndex = 0;
  loadingTargetIndex = 0;
  loadingStepStartedAt = 0;
  loadingProgressQueue = [];
  resolveLoadingFlush();
}

function setAnswerLoading(activeIndex) {
  answerBox.classList.remove("markdown-answer", "result-answer");
  setAnswerState("loading");
  const steps = activeLoadingSteps.length ? activeLoadingSteps : getLoadingSteps();
  const active = steps[activeIndex] || steps[0];
  answerBox.innerHTML = `
    <div class="answer-loading" role="status" aria-live="polite">
      <div class="loading-seal">叙</div>
      <div class="loading-copy">
        <p class="loading-title">${escapeHtml(active.title)}</p>
        <p class="loading-detail">${escapeHtml(active.detail)}</p>
      </div>
      <div class="loading-steps">
        ${steps.map((step, index) => `
          <span class="loading-step ${index < activeIndex ? "is-done" : ""} ${index === activeIndex ? "is-active" : ""}">
            ${escapeHtml(step.title)}
          </span>
        `).join("")}
      </div>
      <div class="loading-shimmer" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;
}

function applyAskProgress(event) {
  const index = PROGRESS_STEP_INDEX[event.step];
  if (index === undefined || index >= activeLoadingSteps.length) {
    return;
  }
  activeLoadingSteps[index] = {
    ...activeLoadingSteps[index],
    detail: event.detail || activeLoadingSteps[index].detail,
  };
  if (index <= loadingStepIndex) {
    if (index === loadingStepIndex) {
      setAnswerLoading(loadingStepIndex);
    }
    return;
  }
  if (!loadingProgressQueue.includes(index)) {
    loadingProgressQueue.push(index);
  }
  window.clearTimeout(loadingFlushTimer);
  loadingFlushTimer = 0;
  scheduleNextLoadingStep();
}

function scheduleNextLoadingStep() {
  if (loadingStepTimer || !loadingProgressQueue.length) {
    scheduleLoadingFlushResolution();
    return;
  }
  const elapsed = performance.now() - loadingStepStartedAt;
  const delay = Math.max(0, LOADING_MIN_STEP_MS - elapsed);
  loadingStepTimer = window.setTimeout(() => {
    loadingStepTimer = 0;
    const nextIndex = loadingProgressQueue.shift();
    if (nextIndex !== undefined && nextIndex > loadingStepIndex) {
      loadingTargetIndex = Math.max(loadingTargetIndex, nextIndex);
      loadingStepIndex = nextIndex;
      loadingStepStartedAt = performance.now();
      setAnswerLoading(loadingStepIndex);
    }
    scheduleNextLoadingStep();
  }, delay);
}

function waitForLoadingSteps() {
  scheduleNextLoadingStep();
  return new Promise((resolve) => {
    loadingFlushResolvers.push(resolve);
    scheduleLoadingFlushResolution();
  });
}

function scheduleLoadingFlushResolution() {
  if (!loadingFlushResolvers.length || loadingProgressQueue.length || loadingStepTimer || loadingFlushTimer) {
    return;
  }
  const elapsed = performance.now() - loadingStepStartedAt;
  const delay = Math.max(0, LOADING_MIN_STEP_MS - elapsed);
  loadingFlushTimer = window.setTimeout(() => {
    loadingFlushTimer = 0;
    if (loadingProgressQueue.length || loadingStepTimer) {
      scheduleLoadingFlushResolution();
      return;
    }
    resolveLoadingFlush();
  }, delay);
}

function resolveLoadingFlush() {
  window.clearTimeout(loadingFlushTimer);
  loadingFlushTimer = 0;
  const resolvers = loadingFlushResolvers;
  loadingFlushResolvers = [];
  resolvers.forEach((resolve) => resolve());
}

function normalizeMarkdownSource(value) {
  return String(value || "").replace(/\\([*_`~])/g, "$1");
}

function renderMarkdown(value) {
  const source = normalizeMarkdownSource(value);
  const markedEngine = window.marked;
  const sanitizer = window.DOMPurify;
  if (markedEngine?.parse && sanitizer?.sanitize) {
    try {
      const rawHtml = markedEngine.parse(source, {
        gfm: true,
        breaks: true,
      });
      return sanitizer.sanitize(rawHtml);
    } catch (error) {
      console.warn("Markdown engine failed; falling back to local parser.", error);
    }
  }
  return renderMarkdownFallback(source);
}

function renderMarkdownFallback(value) {
  const lines = String(value || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let codeLines = [];
  let inCodeBlock = false;

  const closeParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) {
      return;
    }
    html.push(`</${listType}>`);
    listType = "";
  };
  const closeCodeBlock = () => {
    if (!inCodeBlock) {
      return;
    }
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
    inCodeBlock = false;
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCodeBlock) {
        closeCodeBlock();
      } else {
        closeParagraph();
        closeList();
        inCodeBlock = true;
        codeLines = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      closeParagraph();
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/u);
    if (heading) {
      closeParagraph();
      closeList();
      const level = Math.min(6, heading[1].length + 2);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/u);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/u);
    if (unordered || ordered) {
      closeParagraph();
      const nextType = ordered ? "ol" : "ul";
      if (listType !== nextType) {
        closeList();
        html.push(`<${nextType}>`);
        listType = nextType;
      }
      html.push(`<li>${renderInlineMarkdown((ordered || unordered)[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }

  closeCodeBlock();
  closeParagraph();
  closeList();
  return html.join("") || escapeHtml(value);
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/_([^_]+)_/g, "<em>$1</em>");
}

function renderSuggestionStrip(queries, options = {}) {
  if (!queries?.length) {
    return "";
  }
  const chips = queries.map((query) => `
    <button
      class="query-chip ${options.compact ? "is-compact" : ""}"
      type="button"
      data-query="${escapeHtml(query)}"
      data-submit="${options.submit === false ? "0" : "1"}"
    >${escapeHtml(query)}</button>
  `).join("");
  return chips;
}

function renderQuerySuggestions() {
  if (!querySuggestions) {
    return;
  }
  querySuggestions.innerHTML = renderSuggestionStrip(defaultSuggestionQueries, { submit: true });
  bindQueryChips(querySuggestions);
}

function bindQueryChips(scope) {
  scope?.querySelectorAll?.(".query-chip[data-query]")?.forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.query || "";
      resizeQuestionInput();
      updateRelatedItems();
      if (button.dataset.submit !== "0") {
        askQuestion();
      } else {
        questionInput.focus();
      }
    });
  });
}

function bindResultItemLinks(scope) {
  scope?.querySelectorAll?.(".result-item-link[data-id]")?.forEach((button) => {
    button.addEventListener("click", () => loadDetail(button.dataset.id, true));
  });
}

function resultIntroText(question, payload) {
  const taskType = payload?.task_type || "";
  const itemCount = payload?.items?.length || payload?.sources?.length || 0;
  const totalCount = payload?.total_count || itemCount;
  const sourceItem = payload?.items?.[0] || payload?.sources?.[0] || null;
  const sourceTitle = sourceItem ? itemTitle(sourceItem) : "";
  const taskLabel = payload?.task_label || "任务";

  if (taskType === "browse_query") {
    return `系统已根据你的问题整理出 ${totalCount} 个匹配项目，当前优先展示其中最相关的 ${itemCount} 项。`;
  }
  if (taskType === "comparison") {
    return `系统把你关心的项目放到同一组维度里对照，方便直接看差异和适用场景。`;
  }
  if (taskType === "recommendation") {
    return `系统会围绕你的使用场景，从资料库里挑出更合适的项目，并说明为什么推荐它们。`;
  }
  if (taskType === "exhibition_plan") {
    return `系统正在把候选非遗项目整理成可直接落地的展示方案，而不只是给一段说明文字。`;
  }
  if (taskType === "study_task") {
    return `系统把资料库内容转成研学和教学任务，方便继续做课堂活动或学习单。`;
  }
  if (taskType === "content_transform") {
    return `系统先匹配最相关的非遗项目，再把内容改写成更适合传播或展示的版本。`;
  }
  if (taskType === "chitchat") {
    return "这是一次直接回应。如果你想查项目、做筛选、对比或策划，也可以直接自然提问。";
  }
  if (sourceTitle) {
    return `系统正围绕「${sourceTitle}」回答你的问题，并把可追溯的资料条目放在右侧。`;
  }
  return `系统已识别为「${taskLabel}」任务，并结合资料库来回答「${question}」。`;
}

function resultStats(payload) {
  const taskType = payload?.task_type || "";
  const itemCount = payload?.items?.length || payload?.sources?.length || 0;
  const totalCount = payload?.total_count || 0;
  const stats = [];

  if (taskType) {
    stats.push(`任务类型 · ${payload?.task_label || modeLabel(payload?.mode)}`);
  }
  if (totalCount) {
    stats.push(`命中 ${totalCount} 项`);
  } else if (itemCount) {
    stats.push(`涉及 ${itemCount} 项`);
  }
  if (taskType === "comparison" && itemCount) {
    stats.push(`当前对比 ${itemCount} 项`);
  }
  if (taskType === "recommendation") {
    stats.push("已进入场景推荐");
  }
  if (taskType === "exhibition_plan") {
    stats.push("已整理展示方案");
  }
  if (taskType === "content_transform") {
    stats.push("已切换内容转化");
  }
  return stats;
}

function renderResultStats(payload) {
  const stats = resultStats(payload);
  if (!stats.length) {
    return "";
  }
  return `
    <section class="result-section">
      <h3>任务概览</h3>
      <div class="result-stats">
        ${stats.map((value) => `<span class="result-stat">${escapeHtml(value)}</span>`).join("")}
      </div>
    </section>
  `;
}

function itemTitle(item) {
  return item?.title || "未命名项目";
}

function itemMetaParts(item) {
  const parts = [];
  for (const value of [item?.category, item?.family, item?.level]) {
    if (value && !parts.includes(value)) parts.push(value);
  }
  const location = [item?.province, item?.city].filter(Boolean).join(" · ");
  if (location) parts.push(location);
  return parts;
}

function itemTagList(item, limit = 4) {
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

function renderResultItems(payload) {
  const items = payload?.items?.length ? payload.items : payload?.sources || [];
  if (!items.length) {
    return "";
  }
  const itemCountLabel = items.length > 1 ? `（${items.length}项）` : "";
  return `
    <section class="result-section">
      <h3>重点项目${itemCountLabel}</h3>
      <div class="result-items">
        ${items.map((item) => {
          const meta = itemMetaParts(item).join(" · ");
          const tags = itemTagList(item, 3);
          return `
            <button class="result-item-link" type="button" data-id="${escapeHtml(item.id)}">
              <span class="result-item-title">${escapeHtml(itemTitle(item))}</span>
              ${meta ? `<span class="result-item-meta">${escapeHtml(meta)}</span>` : ""}
              ${tags.length ? `<span class="result-item-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</span>` : ""}
            </button>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function renderSelectionReason(payload) {
  if (!payload?.selection_reason) {
    return "";
  }
  return `
    <section class="result-section">
      <h3>为什么这样选</h3>
      <p class="result-note">${escapeHtml(payload.selection_reason)}</p>
    </section>
  `;
}

function renderWarnings(payload) {
  if (!payload?.warnings?.length) {
    return "";
  }
  return `
    <section class="result-section">
      <h3>补充说明</h3>
      <ul class="result-warnings">
        ${payload.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function followupQueries(payload) {
  return followupQueriesByTask[payload?.task_type] || followupQueriesByTask.fact_qa;
}

function renderFollowups(payload) {
  const queries = followupQueries(payload);
  if (!queries.length) {
    return "";
  }
  return `
    <section class="result-section">
      <h3>下一步可以这样问</h3>
      <div class="result-followups">
        ${renderSuggestionStrip(queries, { compact: true, submit: true })}
      </div>
    </section>
  `;
}

function renderResultAnswer(question, payload) {
  const taskLabel = payload?.task_label || modeLabel(payload?.mode);
  return `
    <div class="result-shell" data-task="${escapeHtml(payload?.task_type || "fact_qa")}">
      <section class="result-section">
        <h3>任务理解</h3>
        <p class="result-intro">${escapeHtml(resultIntroText(question, payload))}</p>
      </section>
      ${renderResultStats(payload)}
      ${renderResultItems(payload)}
      ${renderSelectionReason(payload)}
      <section class="result-section">
        <h3>${escapeHtml(taskLabel)}结果</h3>
        <div class="result-markdown">${renderMarkdown(payload?.answer || "")}</div>
      </section>
      ${renderWarnings(payload)}
      ${renderFollowups(payload)}
    </div>
  `;
}

function detailCardMeta(item) {
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

function detailSupportText(item) {
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

async function loadMeta() {
  try {
    const data = await fetchJson("/api/meta");
    metaText.textContent = `${data.item_count} 项 · ${data.category_count} 类`;
  } catch {
    metaText.textContent = "资料库已就绪";
  }
}

async function loadRelatedItems(requestKey = relatedRequestKey) {
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

function relatedPanelTitle(taskType = state.currentTaskType) {
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

function updateRelatedPanelTitle(taskType = state.currentTaskType) {
  if (relatedTitle) {
    relatedTitle.textContent = relatedPanelTitle(taskType);
  }
}

function renderRelatedItems(items, total = items.length) {
  updateRelatedPanelTitle();
  relatedCount.textContent = state.query ? `${total} 条` : "";
  relatedList.innerHTML = items.length
    ? items.map(itemButtonHtml).join("")
    : `<p class="marginalia-empty">${state.query ? "没有匹配条目" : "暂无相关条目"}</p>`;
  relatedList.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === state.selectedId);
    button.addEventListener("click", () => loadDetail(button.dataset.id, true));
  });
}

function itemButtonHtml(item) {
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

async function loadDetail(id, shouldFocus = false) {
  state.selectedId = id;
  relatedList.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === id);
  });

  const item = await fetchJson(`/api/items/${encodeURIComponent(id)}`);
  detailEmpty.hidden = true;
  detailContent.hidden = false;
  detailCategory.textContent = item.category;
  detailCategory.setAttribute("data-category", item.category);
  detailTitle.textContent = itemTitle(item);
  detailMeta.innerHTML = detailCardMeta(item);
  const support = detailSupportText(item);
  detailSupport.hidden = !support;
  detailSupport.textContent = support;
  detailSummary.textContent = item.summary || "暂无摘要。";
  detailBody.textContent = item.content || "暂无原文。";

  if (shouldFocus && window.matchMedia("(max-width: 760px)").matches) {
    detailPanel.scrollIntoView({ block: "start" });
  }
}

function clearDetail() {
  detailEmpty.hidden = false;
  detailContent.hidden = true;
  detailCategory.textContent = "";
  detailTitle.textContent = "";
  detailMeta.innerHTML = "";
  detailSupport.hidden = true;
  detailSupport.textContent = "";
  detailSummary.textContent = "";
  detailBody.textContent = "";
}

let relatedTimer = 0;
let relatedRequestKey = "";
let inFlightKey = "";
function updateRelatedItems() {
  const newQuery = questionInput.value.trim();
  state.query = newQuery;
  state.selectedId = "";
  state.currentTaskType = "";
  relatedList.querySelectorAll("button").forEach((button) => button.classList.remove("active"));
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
  relatedCount.textContent = "思考中";
  relatedList.innerHTML = `<p class="marginalia-empty is-live">正在思考</p>`;
  relatedTimer = window.setTimeout(() => {
    loadRelatedItems(newQuery);
  }, 1000);
}

askButton.addEventListener("click", askQuestion);
questionInput.addEventListener("input", handleQuestionInput);
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    askQuestion();
  }
});

function handleQuestionInput() {
  resizeQuestionInput();
  updateRelatedItems();
}

function resizeQuestionInput() {
  questionInput.style.height = "auto";
  const styles = window.getComputedStyle(questionInput);
  const maxHeight = Number.parseFloat(styles.maxHeight) || 132;
  const nextHeight = Math.min(questionInput.scrollHeight, maxHeight);
  questionInput.style.height = `${nextHeight}px`;
  questionInput.classList.toggle("is-scrollable", questionInput.scrollHeight > maxHeight + 1);
}

function isActiveAskRequest(requestId, controller = askAbortController) {
  return requestId === askRequestId && controller === askAbortController;
}

function beginAskSession(question) {
  const requestId = ++askRequestId;
  askAbortController?.abort();
  const controller = new AbortController();
  askAbortController = controller;
  window.clearTimeout(relatedTimer);
  relatedRequestKey = `ask:${requestId}`;
  inFlightKey = "";

  state.query = question;
  state.currentTaskType = "";
  askButton.disabled = true;
  askButton.textContent = "提问";
  answerMode.textContent = "正在识别任务";
  startLoadingSteps();
  lastSpeechText = "";
  stopSpeech({ preserveHuman: true });
  const thinkingStartedAt = performance.now();
  setDigitalHumanState("thinking", "正在思考", "我先从资料库里找和问题最相关的内容。");
  unlockSpeech(true);

  return { requestId, controller, thinkingStartedAt };
}

function finishAskSession(requestId, controller) {
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }
  askButton.disabled = false;
  askButton.textContent = "提问";
  askAbortController = null;
}

function answerSpeechFromPayload(payload) {
  return payload?.speech || payload?.answer || "";
}

function answerRelatedItems(payload) {
  return payload?.items?.length ? payload.items : (payload?.sources || []);
}

function isContextualFollowup(question) {
  const text = String(question || "").trim();
  if (!text) {
    return false;
  }
  const startsLikeFollowup = /^(再|继续|接着|然后|上一|上个|这个|这份|这段|它|把它|把这个|帮我把它|帮我把这个|基于)/u.test(text);
  const startsLikeTransform = /^(改成|改为|换成|润色|压缩|精简|扩写|翻译|做成|来个|更)/u.test(text);
  const asksForTransform = /(年轻化|口语化|轻松|双语|英文|翻译|压缩|精简|扩写|改写|润色|换个版本|讲解词|口播稿|文案)/u.test(text);
  return startsLikeFollowup || (startsLikeTransform && asksForTransform);
}

function compactAskContextText(value, limit = 3000) {
  const text = String(value || "").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit).trimEnd()}……`;
}

function contextItemPayload(item) {
  return {
    id: item?.id || "",
    title: itemTitle(item),
    family: item?.family || "",
    category: item?.category || "",
    level: item?.level || "",
    address: item?.address || "",
  };
}

function rememberAskContext(question, payload) {
  const related = answerRelatedItems(payload).slice(0, 5).map(contextItemPayload);
  const answer = compactAskContextText(payload?.answer || "");
  if (!answer && !related.length) {
    return;
  }
  state.lastAskContext = {
    question,
    task_type: payload?.task_type || "",
    answer,
    items: related,
  };
}

function buildAskContext(question) {
  if (!state.lastAskContext || !isContextualFollowup(question)) {
    return null;
  }
  return state.lastAskContext;
}

async function presentAskResponse(requestId, controller, question, payload, thinkingStartedAt) {
  await waitForThinkingDissolve(thinkingStartedAt);
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }
  await waitForLoadingSteps();
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }

  const speech = answerSpeechFromPayload(payload);
  const speechAudioUrl = payload?.speech_audio_url || "";
  const speechAudioPending = Boolean(payload?.speech_audio_pending);
  state.currentTaskType = payload?.task_type || "";
  setAnswerResult(question, payload);
  rememberAskContext(question, payload);
  console.info("[xuhua:speech]", {
    mode: payload.mode,
    engine: payload?.speech_engine || "browser",
    length: speech.length,
    text: speech,
  });
  answerMode.textContent = taskModeLabel(payload);
  lastSpeechHumanState = responseHumanState(question);
  setDigitalHumanState(lastSpeechHumanState, "正在回答", speech);
  if (!speakAnswer(speech, speechAudioUrl, { serverTts: speechAudioPending })) {
    scheduleHumanReturnToIdle(visualAnswerDuration(speech));
  }
  const related = answerRelatedItems(payload);
  renderRelatedItems(related, payload?.total_count || related.length);
}

function presentAskError(requestId, controller, error) {
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }
  state.currentTaskType = "";
  const message = error.name === "AbortError" ? "问答超时，请稍后再试。" : `问答失败：${error.message}`;
  setAnswerPlain(message, "error");
  answerMode.textContent = "系统自动识别任务";
  setDigitalHumanState("idle", "出现错误", message);
  stopSpeech();
}

async function askQuestion() {
  const question = questionInput.value.trim();
  if (!question) {
    setAnswerPlain("请先输入问题。", "error");
    return;
  }

  const session = beginAskSession(question);
  const requestData = {
    question,
    category: "",
    voice_enabled: speechSupported,
  };
  const context = buildAskContext(question);
  if (context) {
    requestData.context = context;
  }

  try {
    const payload = await postSseResult("/api/ask", requestData, 65000, session.controller);
    await presentAskResponse(session.requestId, session.controller, question, payload, session.thinkingStartedAt);
  } catch (error) {
    presentAskError(session.requestId, session.controller, error);
  } finally {
    finishAskSession(session.requestId, session.controller);
  }
}

async function postSseResult(url, data, timeoutMs = 65000, controller = null) {
  const requestController = controller || new AbortController();
  const signal = requestController.signal;
  const timer = window.setTimeout(() => requestController.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
      signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }

    if (!response.body) {
      return response.json();
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let payload = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "progress") {
          applyAskProgress(event);
        } else if (event.type === "result") {
          payload = event;
        }
      }
    }

    if (!payload) {
      throw new Error("未收到回答结果");
    }
    return payload;
  } finally {
    window.clearTimeout(timer);
  }
}

function modeLabel(mode) {
  const labels = {
    local: "资料库回答",
    llm: "模型生成",
    fallback: "回退回答",
    no_context: "能力边界",
    empty: "等待问题",
  };
  return labels[mode] || mode;
}

function taskModeLabel(payload) {
  if (payload?.task_type === "chitchat") {
    return payload?.decision?.planner === "model" ? "对话回应" : "对话回应";
  }
  return `已识别：${payload?.task_label || modeLabel(payload?.mode)}`;
}

function setDigitalHumanState(stateName, status, speech = "") {
  window.clearTimeout(humanIdleTimer);
  window.clearTimeout(humanLoopTimer);
  currentHumanState = stateName;
  digitalHumanPanel.dataset.state = stateName;
  digitalHumanStatus.textContent = status;
  digitalHumanSpeech.textContent = digitalHumanCaption(stateName, status, speech);

  const nextSrc = pickHumanVideo(stateName);
  transitionHumanVideo(nextSrc, stateName);
}

function transitionHumanVideo(nextSrc, stateName = currentHumanState, options = {}) {
  if (!activeHumanVideo || (activeHumanVideo.src.endsWith(nextSrc) && !options.force)) {
    configureHumanVideoPlayback(activeHumanVideo, stateName);
    activeHumanVideo?.play().catch(() => {});
    scheduleHumanVideoAdvance(activeHumanVideo, stateName);
    return;
  }
  const transitionSeq = ++humanTransitionSeq;
  if (!standbyHumanVideo) {
    configureHumanVideoPlayback(activeHumanVideo, stateName);
    activeHumanVideo.src = nextSrc;
    activeHumanVideo.load();
    activeHumanVideo.play().catch(() => {});
    scheduleHumanVideoAdvance(activeHumanVideo, stateName);
    return;
  }

  window.clearTimeout(humanTransitionTimer);
  window.clearTimeout(humanDissolveTimer);
  const incoming = standbyHumanVideo;
  const outgoing = activeHumanVideo;
  let started = false;

  incoming.pause();
  incoming.classList.remove("is-active");
  configureHumanVideoPlayback(incoming, stateName);
  incoming.src = nextSrc;
  incoming.load();

  const startTransition = () => {
    if (started || transitionSeq !== humanTransitionSeq) return;
    started = true;
    incoming.play().catch(() => {});
    window.requestAnimationFrame(() => {
      incoming.style.opacity = "0";
      incoming.classList.add("is-active");
      incoming.classList.add("is-dissolve-in");
      outgoing.classList.add("is-dissolve-out");
      digitalHumanVideo.parentElement?.classList.add("is-dissolving");
      window.requestAnimationFrame(() => {
        incoming.style.opacity = "";
        outgoing.classList.remove("is-active");
      });
    });
    humanDissolveTimer = window.setTimeout(() => {
      incoming.classList.remove("is-dissolve-in");
      outgoing.classList.remove("is-dissolve-out");
      digitalHumanVideo.parentElement?.classList.remove("is-dissolving");
    }, 980);
    activeHumanVideo = incoming;
    standbyHumanVideo = outgoing;
    scheduleHumanVideoAdvance(incoming, stateName);
    humanTransitionTimer = window.setTimeout(() => {
      outgoing.pause();
      outgoing.removeAttribute("src");
      outgoing.load();
    }, 1020);
  };

  incoming.addEventListener("loadeddata", startTransition, { once: true });
  incoming.addEventListener("canplay", startTransition, { once: true });
  window.setTimeout(startTransition, 240);
}

function configureHumanVideoPlayback(video, stateName) {
  if (!video) return;
  video.loop = false;
  video.muted = true;
  video.playsInline = true;
}

function scheduleHumanVideoAdvance(video, stateName = currentHumanState) {
  window.clearTimeout(humanLoopTimer);
  if (!video || currentHumanState !== stateName) {
    return;
  }
  const schedule = () => {
    if (currentHumanState !== stateName || activeHumanVideo !== video) {
      return;
    }
    const duration = Number.isFinite(video.duration) ? video.duration : 5;
    const delay = Math.max(1200, duration * 1000 - HUMAN_DISSOLVE_LEAD_MS);
    humanLoopTimer = window.setTimeout(() => {
      if (currentHumanState === stateName && activeHumanVideo === video) {
        transitionHumanVideo(pickHumanVideo(stateName, { allowSame: true }), stateName, { force: true });
      }
    }, delay);
  };
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
    schedule();
  } else {
    video.addEventListener("loadedmetadata", schedule, { once: true });
  }
}

function pickHumanVideo(stateName, options = {}) {
  const source = humanVideos[stateName] || humanVideos.idle;
  const videos = Array.isArray(source) ? source : [source];
  let index = humanVideoIndexes[stateName] || 0;
  let next = videos[index % videos.length];
  if (!options.allowSame && videos.length > 1 && activeHumanVideo?.src.endsWith(next)) {
    index += 1;
    next = videos[index % videos.length];
  }
  humanVideoIndexes[stateName] = (index + 1) % videos.length;
  return next;
}

function responseHumanState(query) {
  const farewellTerms = ["谢谢", "感谢", "辛苦了", "再见", "拜拜", "下次见"];
  return farewellTerms.some((term) => query.includes(term)) ? "farewell" : "speaking";
}

function waitForThinkingDissolve(startedAt) {
  if (currentHumanState !== "thinking") {
    return Promise.resolve();
  }
  const elapsed = performance.now() - startedAt;
  const remaining = Math.max(0, HUMAN_MIN_THINKING_MS - elapsed);
  return remaining ? new Promise((resolve) => window.setTimeout(resolve, remaining)) : Promise.resolve();
}

function scheduleHumanReturnToIdle(delayMs) {
  window.clearTimeout(humanIdleTimer);
  humanIdleTimer = window.setTimeout(() => {
    if (currentHumanState === "speaking" || currentHumanState === "farewell") {
      setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
    }
  }, delayMs);
}

function visualAnswerDuration(text) {
  const length = stripMarkdown(text).length;
  return Math.min(22000, Math.max(7500, 3600 + length * 90));
}

function digitalHumanCaption(stateName, status, fallback = "") {
  const captions = {
    idle: "我在这里，可以继续问我。",
    thinking: "我先从资料库里找和问题最相关的内容。",
    speaking: "正在为你讲述。",
    farewell: "期待下次再见。",
  };
  if (status === "出现错误") {
    return "刚才没有答好，请再试一次。";
  }
  return captions[stateName] || fallback || "我在这里。";
}

function syncVoiceIdleState(status = "") {
  if (!speechSupported) {
    setVoiceState("disabled");
    setVoiceStatus("浏览器不支持语音");
    return;
  }
  setVoiceState("idle");
  setVoiceStatus(status);
}

function speakAnswer(value, audioUrl = "", options = {}) {
  lastSpeechText = speechText(value);
  lastSpeechAudioUrl = audioUrl || "";
  if (!speechSupported || !lastSpeechText) {
    return false;
  }
  const playbackSeq = ++speechPlaybackSeq;
  if (lastSpeechAudioUrl) {
    return playAudioAnswer(lastSpeechAudioUrl, lastSpeechText, playbackSeq);
  }
  if (options.serverTts) {
    return requestServerSpeech(lastSpeechText, playbackSeq);
  }
  return speakText(lastSpeechText, playbackSeq);
}

function requestServerSpeech(text, playbackSeq) {
  if (!audioSpeechSupported) {
    return speakText(text, playbackSeq);
  }
  stopSpeech({ preserveHuman: true, keepPlaybackSeq: true });
  setVoiceState("speaking");
  setVoiceStatus("正在连接语音");
  currentSpeechSegments = speechPlaybackSegments(text);
  if (currentSpeechSegments.length) {
    return playSpeechSegment(0, playbackSeq);
  }
  return requestServerSpeechFile(text, playbackSeq);
}

function requestServerSpeechFile(text, playbackSeq) {
  if (speechPlaybackSeq !== playbackSeq || lastSpeechText !== text) {
    return true;
  }
  setVoiceState("speaking");
  setVoiceStatus("正在生成语音");
  fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      return response.json();
    })
    .then((payload) => {
      if (speechPlaybackSeq !== playbackSeq || lastSpeechText !== text) return;
      const audioUrl = payload?.speech_audio_url || "";
      lastSpeechAudioUrl = audioUrl;
      if (audioUrl) {
        playAudioAnswer(audioUrl, text, playbackSeq);
      } else if (!speakText(text, playbackSeq)) {
        finishSpeechPlayback("语音暂不可用");
      }
    })
    .catch(() => {
      if (speechPlaybackSeq !== playbackSeq || lastSpeechText !== text) return;
      if (!speakText(text, playbackSeq)) {
        finishSpeechPlayback("语音生成失败");
      }
    });
  return true;
}

function playSpeechSegment(index, playbackSeq) {
  if (speechPlaybackSeq !== playbackSeq) {
    return true;
  }
  const text = currentSpeechSegments[index] || "";
  if (!text) {
    finishSpeechPlayback("");
    return true;
  }
  const streamUrl = ttsStreamUrl(text);
  if (streamUrl.length >= 7600) {
    return requestServerSpeechFile(currentSpeechSegments.slice(index).join(""), playbackSeq);
  }
  return playAudioAnswer(streamUrl, text, playbackSeq, {
    onEnd: () => playSpeechSegment(index + 1, playbackSeq),
    onError: () => requestServerSpeechFile(currentSpeechSegments.slice(index).join(""), playbackSeq),
  });
}

function speechPlaybackSegments(text) {
  const source = String(text || "").trim();
  if (!source) return [];
  const pieces = source.match(/[^。！？!?；;]+[。！？!?；;]?/gu) || [source];
  const segments = [];
  let current = "";
  for (const piece of pieces) {
    const candidate = current + piece;
    if (current && utf8ByteLength(candidate) > 720) {
      segments.push(current);
      current = piece;
    } else {
      current = candidate;
    }
    while (utf8ByteLength(current) > 720) {
      segments.push(sliceUtf8Bytes(current, 720));
      current = current.slice(segments[segments.length - 1].length);
    }
  }
  if (current) {
    segments.push(current);
  }
  return segments;
}

function utf8ByteLength(value) {
  return new TextEncoder().encode(String(value || "")).length;
}

function sliceUtf8Bytes(value, maxBytes) {
  let bytes = 0;
  let index = 0;
  const text = String(value || "");
  for (const char of text) {
    const size = utf8ByteLength(char);
    if (bytes + size > maxBytes) break;
    bytes += size;
    index += char.length;
  }
  return text.slice(0, Math.max(index, 1));
}

function ttsStreamUrl(text) {
  const params = new URLSearchParams({ text });
  return `/api/tts/stream?${params.toString()}`;
}

function playAudioAnswer(audioUrl, fallbackText = "", playbackSeq = ++speechPlaybackSeq, options = {}) {
  if (!audioSpeechSupported || !audioUrl) {
    return speakText(fallbackText, playbackSeq);
  }
  stopSpeech({ preserveHuman: true, keepPlaybackSeq: true });
  clearSpeechStartGuard();
  const audio = new Audio(audioUrl);
  currentSpeechAudio = audio;
  audio.preload = "auto";
  audio.onplay = () => {
    if (currentSpeechAudio !== audio || speechPlaybackSeq !== playbackSeq) return;
    setVoiceState("speaking");
    setVoiceStatus("正在播报");
  };
  audio.onended = () => {
    if (currentSpeechAudio !== audio || speechPlaybackSeq !== playbackSeq) return;
    if (options.onEnd?.()) return;
    finishSpeechPlayback("");
  };
  audio.onerror = () => {
    if (currentSpeechAudio !== audio || speechPlaybackSeq !== playbackSeq) return;
    currentSpeechAudio = null;
    if (options.onError?.()) return;
    if (!speakText(fallbackText, playbackSeq)) {
      finishSpeechPlayback("音频播报失败");
    }
  };
  const playPromise = audio.play();
  if (playPromise?.catch) {
    playPromise.catch(() => {
      if (currentSpeechAudio !== audio || speechPlaybackSeq !== playbackSeq) return;
      currentSpeechAudio = null;
      if (options.onError?.()) return;
      if (!speakText(fallbackText, playbackSeq)) {
        finishSpeechPlayback("自动播报被浏览器拦截");
      }
    });
  }
  return true;
}

function speakText(text, playbackSeq = ++speechPlaybackSeq) {
  if (!browserSpeechSupported) {
    setVoiceStatus("浏览器不支持语音");
    return false;
  }
  stopSpeech({ preserveHuman: true, keepPlaybackSeq: true });
  clearSpeechStartGuard();
  window.speechSynthesis.resume();
  const utterance = new SpeechSynthesisUtterance(text);
  currentUtterance = utterance;
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  utterance.pitch = 1;

  const voices = window.speechSynthesis.getVoices();
  const chineseVoice = voices.find((voice) => /zh|Chinese|普通话|中文/i.test(voice.lang + voice.name));
  if (chineseVoice) {
    utterance.voice = chineseVoice;
  }

  utterance.onstart = () => {
    if (currentUtterance !== utterance || speechPlaybackSeq !== playbackSeq) return;
    clearSpeechStartGuard();
    setVoiceState("speaking");
    setVoiceStatus("正在播报");
  };
  utterance.onend = () => {
    if (currentUtterance !== utterance || speechPlaybackSeq !== playbackSeq) return;
    clearSpeechStartGuard();
    finishSpeechPlayback("");
  };
  utterance.onerror = () => {
    if (currentUtterance !== utterance || speechPlaybackSeq !== playbackSeq) return;
    clearSpeechStartGuard();
    finishSpeechPlayback("自动播报被浏览器拦截");
  };

  window.speechSynthesis.speak(utterance);
  speechStartGuardTimer = window.setTimeout(() => {
    if (currentUtterance !== utterance || speechPlaybackSeq !== playbackSeq) return;
    if (!window.speechSynthesis.speaking && !window.speechSynthesis.pending) {
      finishSpeechPlayback("播报未启动");
    }
  }, 700);
  return true;
}

function clearSpeechStartGuard() {
  window.clearTimeout(speechStartGuardTimer);
  speechStartGuardTimer = 0;
}

function finishSpeechPlayback(status = "") {
  clearSpeechStartGuard();
  currentUtterance = null;
  currentSpeechAudio = null;
  currentSpeechSegments = [];
  syncVoiceIdleState(status);
  if (currentHumanState === "speaking" || currentHumanState === "farewell") {
    setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
  }
}

function stopSpeech(options = {}) {
  if (!options.keepPlaybackSeq) {
    speechPlaybackSeq += 1;
  }
  clearSpeechStartGuard();
  if (currentSpeechAudio) {
    currentSpeechAudio.pause();
    currentSpeechAudio.currentTime = 0;
    currentSpeechAudio.removeAttribute("src");
    currentSpeechAudio.load();
    currentSpeechAudio = null;
  }
  if (!options.keepPlaybackSeq) {
    currentSpeechSegments = [];
  }
  if (browserSpeechSupported) {
    window.clearTimeout(speechCancelTimer);
    window.speechSynthesis.cancel();
    if (options.delayed) {
      speechCancelTimer = window.setTimeout(() => window.speechSynthesis.cancel(), 0);
    }
  }
  currentUtterance = null;
  syncVoiceIdleState("");
  if (!options.preserveHuman && (currentHumanState === "speaking" || currentHumanState === "farewell")) {
    setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
  }
}

function unlockSpeech(withThinkingVoice = false) {
  if (!browserSpeechSupported || speechUnlocked) {
    return;
  }
  speechUnlocked = true;
  try {
    const text = withThinkingVoice ? "正在检索" : "语音播报已准备";
    const warmup = new SpeechSynthesisUtterance(text);
    warmup.lang = "zh-CN";
    warmup.rate = 1;
    warmup.pitch = 1;
    warmup.volume = withThinkingVoice ? 0.75 : 0.01;
    window.speechSynthesis.resume();
    window.speechSynthesis.speak(warmup);
  } catch {
    speechUnlocked = false;
  }
}

function setVoiceStatus(value) {
  if (voiceStatus) {
    voiceStatus.textContent = value;
  }
  if (value) {
    voiceStatus.classList.add("is-active");
  } else {
    voiceStatus.classList.remove("is-active");
  }
}

function setVoiceState(state) {
  voiceState = state;
  if (!voiceToggle) return;
  voiceToggle.classList.toggle("is-speaking", state === "speaking");
  voiceToggle.dataset.state = state;
  voiceToggle.setAttribute("aria-pressed", state === "speaking" ? "true" : "false");
  if (state === "disabled") {
    voiceToggle.setAttribute("disabled", "disabled");
  } else {
    voiceToggle.removeAttribute("disabled");
  }
  const label = voiceToggle.querySelector(".voice-label");
  if (label) {
    label.textContent = { speaking: "停止", idle: "播放", disabled: "播放" }[state] || "播放";
  }
}

function speechText(value) {
  const text = stripSpeechDecorations(value)
    .replace(/模型接口暂不可用[\s\S]*$/u, "")
    .replace(/\s+/g, " ")
    .trim();
  return text;
}

function stripSpeechDecorations(value) {
  return stripMarkdown(value)
    .replace(/[\u{1F1E6}-\u{1F1FF}\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function stripMarkdown(value) {
  return normalizeMarkdownSource(value)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/[>#*_~|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

configureHumanVideoPlayback(activeHumanVideo, "idle");
scheduleHumanVideoAdvance(activeHumanVideo, "idle");
renderQuerySuggestions();
loadMeta();
updateRelatedPanelTitle();
syncRestoredQuestion();
window.addEventListener("pageshow", syncRestoredQuestion);

function syncRestoredQuestion() {
  resizeQuestionInput();
  const restoredQuery = questionInput.value.trim();
  if (restoredQuery !== state.query) {
    updateRelatedItems();
  } else if (!restoredQuery) {
    renderRelatedItems([]);
  }
}
