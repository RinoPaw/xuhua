import { followupQueriesByTask, PROGRESS_STEP_INDEX, loadingSteps, LOADING_MIN_STEP_MS, speechSupported } from './consts.js';
import { state, els } from './state.js';
import { escapeHtml, renderMarkdown } from './markdown.js';
import { itemTitle, itemMetaParts, itemTagList, beginAskSessionRelated, showDetail } from './search.js';
import { responseHumanState, setDigitalHumanState, scheduleHumanReturnToIdle, waitForThinkingDissolve, visualAnswerDuration } from './human.js';
import { speakAnswer, stopSpeech, unlockSpeech, cacheSpeechResult, clearSpeechCache, voiceEnabled, markSpeechRewritePending } from './speech.js';
import { bindQueryChips } from './ui.js';

let askAbortController = null;
let askRequestId = 0;
let loadingStepTimer = 0;
let loadingFlushTimer = 0;
let loadingStepIndex = 0;
let loadingTargetIndex = 0;
let loadingStepStartedAt = 0;
let loadingProgressQueue = [];
let loadingFlushResolvers = [];
let activeLoadingSteps = [...loadingSteps];
let plannerReason = "";
export let lastSpeechHumanState = "speaking";

function setAnswerState(stateName) {
  els.answerBox.classList.remove("is-idle", "is-loading", "is-error");
  if (stateName) {
    els.answerBox.classList.add(`is-${stateName}`);
  }
}

function setAnswerPlain(value, stateName = "") {
  stopLoadingSteps();
  els.answerBox.classList.remove("markdown-answer", "result-answer");
  setAnswerState(stateName);
  els.answerBox.textContent = value;
}

function setAnswerMarkdown(value) {
  stopLoadingSteps();
  setAnswerState("");
  els.answerBox.classList.remove("result-answer");
  els.answerBox.classList.add("markdown-answer");
  els.answerBox.innerHTML = renderMarkdown(value);
}

function setAnswerResult(question, payload) {
  stopLoadingSteps();
  setAnswerState("");
  els.answerBox.classList.remove("markdown-answer");
  els.answerBox.classList.add("result-answer");
  els.answerBox.innerHTML = renderResultAnswer(question, payload);
  bindQueryChips(els.answerBox);
  // Make result cards clickable → show detail in right panel
  els.answerBox.querySelectorAll(".result-item-link[data-id]").forEach((el) => {
    el.addEventListener("click", () => showDetail(el.dataset.id));
  });
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
  els.answerBox.classList.remove("markdown-answer", "result-answer");
  setAnswerState("loading");
  const steps = activeLoadingSteps.length ? activeLoadingSteps : getLoadingSteps();
  const active = steps[activeIndex] || steps[0];
  els.answerBox.innerHTML = `
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
  // Capture planner reason on first classify with real detail
  if (event.step === "classify" && event.detail && event.detail.indexOf("判断") === -1) {
    plannerReason = event.detail;
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

export function renderSuggestionStrip(queries, options = {}) {
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

function renderResultStats(payload) {
  return "";
}

function renderResultItems(payload) {
  const items = payload?.items?.length ? payload.items : payload?.sources || [];
  if (!items.length) {
    return "";
  }
  const taskType = payload?.task_type || "fact_qa";
  const itemCountLabel = items.length > 1 ? `（${items.length}项）` : "";

  // Card style hint per task type
  const cardStyleClass = {
    browse_query: "is-browse-card",
    recommendation: "is-recommend-card",
    exhibition_plan: "is-exhibit-card",
    study_task: "is-study-card",
    comparison: "is-compare-card",
  }[taskType] || "";

  return `
    <section class="result-section">
      <h3>重点项目${itemCountLabel}</h3>
      <div class="result-items ${cardStyleClass}">
        ${items.map((item) => {
          const meta = itemMetaParts(item, { skipLevel: !!item?.reason_tags?.length }).join(" · ");
          const tags = itemTagList(item, 3);
          const category = item?.category || "未分类";
          return `
            <button
              class="result-item-link"
              type="button"
              data-id="${escapeHtml(item.id)}"
              data-category="${escapeHtml(category)}"
            >
              <span class="result-item-title">${escapeHtml(itemTitle(item))}</span>
              ${meta ? `<span class="result-item-meta">${escapeHtml(meta)}</span>` : ""}
              ${!item?.reason_tags?.length && tags.length ? `<span class="result-item-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</span>` : ""}
              ${renderItemReasonTags(item)}
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

function renderItemReasonTags(item) {
  const tags = item?.reason_tags;
  if (!tags?.length) return "";
  return `<span class="result-item-reasons">${tags.map((t) => `<span>${escapeHtml(t)}</span>`).join("")}</span>`;
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

function renderPlannerEcho(payload) {
  return "";
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

function renderBilingualCard(payload) {
  const fields = payload?.bilingual_fields;
  if (!fields?.length) return "";

  const title = payload?.items?.[0]?.title || "";
  const enTitle = fields.find(f => f.label_cn === "名称")?.value_en || "";

  return `
    <div class="bilingual-card">
      <div class="bilingual-head">
        <h2 class="bilingual-title">${escapeHtml(title)}</h2>
        <p class="bilingual-subtitle">${escapeHtml(enTitle)}</p>
      </div>
      ${payload?.answer ? `<p class="bilingual-intro">${escapeHtml(payload.answer)}</p>` : ""}
      <div class="bilingual-fields">
        ${fields.map(f => `
        <div class="bilingual-field-row">
          <div class="bilingual-field-col">
            <span class="bilingual-field-label">${escapeHtml(f.label_cn)}</span>
            <span class="bilingual-field-value">${escapeHtml(f.value_cn)}</span>
          </div>
          <div class="bilingual-field-col">
            <span class="bilingual-field-label">${escapeHtml(f.label_en)}</span>
            <span class="bilingual-field-value">${escapeHtml(f.value_en)}</span>
          </div>
        </div>`).join("")}
      </div>
    </div>
  `;
}

function renderResultAnswer(question, payload) {
  const taskLabel = payload?.task_label || modeLabel(payload?.mode);

  const bilingualCard = renderBilingualCard(payload);
  const answerSection = bilingualCard
    ? bilingualCard
    : `<section class="result-section">
        <h3>${escapeHtml(taskLabel)}结果</h3>
        <div class="result-markdown">${renderMarkdown(payload?.answer || "")}</div>
      </section>`;

  return `
    <div class="result-shell" data-task="${escapeHtml(payload?.task_type || "fact_qa")}">
      ${renderPlannerEcho(payload)}
      ${renderResultStats(payload)}
      ${renderResultItems(payload)}
      ${renderSelectionReason(payload)}
      ${answerSection}
      ${renderWarnings(payload)}
      ${renderFollowups(payload)}
    </div>
  `;
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

function isActiveAskRequest(requestId, controller = askAbortController) {
  return requestId === askRequestId && controller === askAbortController;
}

function beginAskSession(question) {
  const requestId = ++askRequestId;
  askAbortController?.abort();
  const controller = new AbortController();
  askAbortController = controller;
  beginAskSessionRelated(requestId);

  state.query = question;
  state.currentTaskType = "";
  plannerReason = "";
  els.askButton.disabled = true;
  els.askButton.textContent = "提问";
  els.answerMode.textContent = "";
  startLoadingSteps();
  clearSpeechCache();
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
  els.askButton.disabled = false;
  els.askButton.textContent = "提问";
  askAbortController = null;
}

function answerRelatedItems(payload) {
  return payload?.items?.length ? payload.items : (payload?.sources || []);
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
  return state.lastAskContext || null;
}

async function presentAskResult(requestId, controller, question, payload, thinkingStartedAt) {
  // Display answer text immediately — don't wait for video dissolve
  stopLoadingSteps();
  state.currentTaskType = payload?.task_type || "";
  setAnswerResult(question, payload);
  rememberAskContext(question, payload);
  els.answerMode.textContent = "";

  // Video dissolve is visual polish for the digital human, can happen after text is visible
  await waitForThinkingDissolve(thinkingStartedAt);
}

function applyAnswerSpeech(event) {
  const text = event?.text || "";
  if (!text) return;

  const speechAudioUrl = event?.speech_audio_url || "";
  const speechAudioPending = Boolean(event?.speech_audio_pending);
  const speechLang = event?.speech_lang || "";

  console.info("[xuhua:speech]", {
    engine: event?.speech_engine || "browser",
    length: text.length,
    text,
  });

  lastSpeechHumanState = responseHumanState(state.query || "");
  setDigitalHumanState(lastSpeechHumanState, "正在回答", text);

  if (!voiceEnabled) {
    cacheSpeechResult(text, speechAudioUrl, { serverTts: speechAudioPending, lang: speechLang });
    scheduleHumanReturnToIdle(visualAnswerDuration(text));
    return;
  }

  if (!speakAnswer(text, speechAudioUrl, { serverTts: speechAudioPending, lang: speechLang })) {
    scheduleHumanReturnToIdle(visualAnswerDuration(text));
  }
}

function presentAskError(requestId, controller, error) {
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }
  state.currentTaskType = "";
  const message = error.name === "AbortError" ? "问答超时，请稍后再试。" : `问答失败：${error.message}`;
  setAnswerPlain(message, "error");
  els.answerMode.textContent = "";
  setDigitalHumanState("idle", "出现错误", message);
  stopSpeech();
}

export async function askQuestion() {
  const question = els.questionInput.value.trim();
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
  if (state.sessionId) {
    requestData.session_id = state.sessionId;
  }
  const context = buildAskContext(question);
  if (context) {
    requestData.context = context;
  }

  let speechArrived = false;

  try {
    const payload = await postSseResult("/api/ask", requestData, 65000, session.controller, {
      onResult(p) {
        if (voiceEnabled && !speechArrived && p?.answer) {
          markSpeechRewritePending(true);
        }
        presentAskResult(session.requestId, session.controller, question, p, session.thinkingStartedAt);
      },
      onSpeech(e) {
        speechArrived = true;
        markSpeechRewritePending(false);
        applyAnswerSpeech(e);
      },
    });
    // If speech arrived before stream ended, it was already handled by onSpeech
    // Otherwise, speech may be in the result payload (non-streaming fallback)
    if (!speechArrived && payload?.speech) {
      markSpeechRewritePending(false);
      applyAnswerSpeech({
        text: payload.speech,
        speech_engine: payload?.speech_engine || "browser",
        speech_audio_url: payload?.speech_audio_url || "",
        speech_audio_pending: Boolean(payload?.speech_audio_pending),
        speech_lang: payload?.speech_lang || "",
      });
    } else if (!speechArrived) {
      markSpeechRewritePending(false);
    }
  } catch (error) {
    markSpeechRewritePending(false);
    presentAskError(session.requestId, session.controller, error);
  } finally {
    finishAskSession(session.requestId, session.controller);
  }
}

async function postSseResult(url, data, timeoutMs = 65000, controller = null, callbacks = {}) {
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
          if (event.session_id) state.sessionId = event.session_id;
          applyAskProgress(event);
        } else if (event.type === "result") {
          if (event.session_id) state.sessionId = event.session_id;
          payload = event;
          callbacks.onResult?.(event);
        } else if (event.type === "speech") {
          if (event.session_id) state.sessionId = event.session_id;
          callbacks.onSpeech?.(event);
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
