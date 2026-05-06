const state = {
  query: "",
  selectedId: "",
};

const relatedList = document.querySelector("#relatedList");
const relatedCount = document.querySelector("#relatedCount");
const metaText = document.querySelector("#metaText");
const detailEmpty = document.querySelector("#detailEmpty");
const detailContent = document.querySelector("#detailContent");
const detailPanel = document.querySelector(".marginalia");
const detailCategory = document.querySelector("#detailCategory");
const detailTitle = document.querySelector("#detailTitle");
const detailSummary = document.querySelector("#detailSummary");
const detailBody = document.querySelector("#detailBody");
const questionInput = document.querySelector("#questionInput");
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
let lastSpeechText = "";
let speechUnlocked = false;
let speechCancelTimer = 0;
let speechStartGuardTimer = 0;
let voiceState = "idle"; // idle | speaking | disabled
let lastSpeechHumanState = "speaking";
let loadingStepTimer = 0;
let loadingStepIndex = 0;
let loadingTargetIndex = 0;
let askAbortController = null;
let askRequestId = 0;

const speechSupported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
const PROGRESS_STEP_INDEX = {
  classify: 0,
  search: 1,
  generate: 3,
  speech: 4,
};
const baseLoadingSteps = [
  { title: "翻检资料库", detail: "正在查找最相关的非遗条目" },
  { title: "比对资料", detail: "正在合并项目、地区和技艺线索" },
  { title: "组织回答", detail: "正在把资料整理成可阅读的说明" },
  { title: "生成回答", detail: "正在请模型生成最终文字" },
];
const speechLoadingStep = { title: "润色播报", detail: "正在准备更适合朗读的版本" };
const finalLoadingStep = { title: "收束答案", detail: "正在整理最后的回答文本" };
let activeLoadingSteps = [...baseLoadingSteps, speechLoadingStep];
const HUMAN_MIN_THINKING_MS = 1120;
const HUMAN_DISSOLVE_LEAD_MS = 1050;

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
  speakText(lastSpeechText);
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
  answerBox.classList.remove("markdown-answer");
  setAnswerState(stateName);
  answerBox.textContent = value;
}

function setAnswerMarkdown(value) {
  stopLoadingSteps();
  setAnswerState("");
  answerBox.classList.add("markdown-answer");
  answerBox.innerHTML = renderMarkdown(value);
}

function startLoadingSteps() {
  activeLoadingSteps = getLoadingSteps();
  loadingStepIndex = 0;
  loadingTargetIndex = 0;
  setAnswerLoading(loadingStepIndex);
  window.clearInterval(loadingStepTimer);
  loadingStepTimer = window.setInterval(() => {
    const maxIndex = activeLoadingSteps.length - 1;
    if (loadingStepIndex < loadingTargetIndex) {
      loadingStepIndex += 1;
      setAnswerLoading(loadingStepIndex);
      return;
    }
    if (loadingTargetIndex < maxIndex) {
      loadingTargetIndex += 1;
      loadingStepIndex = Math.min(loadingStepIndex + 1, loadingTargetIndex);
      setAnswerLoading(loadingStepIndex);
    }
  }, 1800);
}

function getLoadingSteps() {
  const finalStep = speechSupported ? speechLoadingStep : finalLoadingStep;
  return [...baseLoadingSteps, finalStep];
}

function stopLoadingSteps() {
  window.clearInterval(loadingStepTimer);
  loadingStepTimer = 0;
  loadingStepIndex = 0;
  loadingTargetIndex = 0;
}

function setAnswerLoading(activeIndex) {
  answerBox.classList.remove("markdown-answer");
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
    title: event.title || activeLoadingSteps[index].title,
    detail: event.detail || activeLoadingSteps[index].detail,
  };
  loadingTargetIndex = Math.max(loadingTargetIndex, index);
  if (index <= loadingStepIndex) {
    setAnswerLoading(loadingStepIndex);
  }
}

function renderMarkdown(value) {
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

function renderRelatedItems(items, total = items.length) {
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
  return `
    <button class="item-entry" type="button" data-id="${escapeHtml(item.id)}" data-category="${escapeHtml(item.category)}">
      <div class="item-entry-title">${escapeHtml(item.title)}</div>
      <div class="item-entry-meta">${escapeHtml(item.category)} · ${escapeHtml(summary.slice(0, 46))}</div>
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
  detailTitle.textContent = item.title;
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
  relatedList.querySelectorAll("button").forEach((button) => button.classList.remove("active"));
  clearDetail();

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

  state.query = question;
  askButton.disabled = true;
  askButton.textContent = "提问";
  answerMode.textContent = "";
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

async function presentAskResponse(requestId, controller, question, payload, thinkingStartedAt) {
  await waitForThinkingDissolve(thinkingStartedAt);
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }

  const speech = answerSpeechFromPayload(payload);
  setAnswerMarkdown(payload.answer);
  console.info("[xuhua:speech]", {
    mode: payload.mode,
    length: speech.length,
    text: speech,
  });
  answerMode.textContent = taskModeLabel(payload);
  lastSpeechHumanState = responseHumanState(question);
  setDigitalHumanState(lastSpeechHumanState, "正在回答", speech);
  if (!speakAnswer(speech)) {
    scheduleHumanReturnToIdle(visualAnswerDuration(speech));
  }
  const related = answerRelatedItems(payload);
  renderRelatedItems(related, related.length);
}

function presentAskError(requestId, controller, error) {
  if (!isActiveAskRequest(requestId, controller)) {
    return;
  }
  const message = error.name === "AbortError" ? "问答超时，请稍后再试。" : `问答失败：${error.message}`;
  setAnswerPlain(message, "error");
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

  try {
    const payload = await postSseResult("/api/ask", {
      question,
      category: "",
      voice_enabled: speechSupported,
    }, 65000, session.controller);
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
    return payload?.decision?.planner === "model" ? "智能体回应" : "直接回应";
  }
  return payload?.task_label || modeLabel(payload?.mode);
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

function speakAnswer(value) {
  lastSpeechText = speechText(value);
  if (!speechSupported || !lastSpeechText) {
    return false;
  }
  return speakText(lastSpeechText);
}

function speakText(text) {
  if (!speechSupported) {
    setVoiceStatus("浏览器不支持语音");
    return false;
  }
  stopSpeech({ preserveHuman: true });
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
    if (currentUtterance !== utterance) return;
    clearSpeechStartGuard();
    setVoiceState("speaking");
    setVoiceStatus("正在播报");
  };
  utterance.onend = () => {
    if (currentUtterance !== utterance) return;
    clearSpeechStartGuard();
    finishSpeechPlayback("");
  };
  utterance.onerror = () => {
    if (currentUtterance !== utterance) return;
    clearSpeechStartGuard();
    finishSpeechPlayback("自动播报被浏览器拦截");
  };

  window.speechSynthesis.speak(utterance);
  speechStartGuardTimer = window.setTimeout(() => {
    if (currentUtterance !== utterance) return;
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
  syncVoiceIdleState(status);
  if (currentHumanState === "speaking" || currentHumanState === "farewell") {
    setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
  }
}

function stopSpeech(options = {}) {
  clearSpeechStartGuard();
  if (speechSupported) {
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
  if (!speechSupported || speechUnlocked) {
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
  const text = stripMarkdown(value)
    .replace(/模型接口暂不可用[\s\S]*$/u, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 720 ? `${text.slice(0, 720)}。` : text;
}

function stripMarkdown(value) {
  return String(value || "")
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
loadMeta();
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
