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
const voiceEnabled = document.querySelector("#voiceEnabled");
const voiceStatus = document.querySelector("#voiceStatus");
const answerBox = document.querySelector("#answerBox");
const answerMode = document.querySelector("#answerMode");
const digitalHumanPanel = document.querySelector(".hanging-scroll");
const digitalHumanVideo = document.querySelector("#digitalHumanVideo");
const digitalHumanStatus = document.querySelector("#digitalHumanStatus");
const digitalHumanSpeech = document.querySelector("#digitalHumanSpeech");

const humanVideos = {
  idle: "/static/media/xuhua-idle.mp4",
  thinking: "/static/media/xuhua-greet.mp4",
  speaking: "/static/media/xuhua-speak.mp4",
};

let humanIdleTimer = 0;
let currentUtterance = null;
let lastSpeechText = "";
let speechUnlocked = false;
let speechCancelTimer = 0;

const speechSupported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;

if (!speechSupported && voiceEnabled) {
  voiceEnabled.checked = false;
  voiceEnabled.disabled = true;
  voiceStatus.textContent = "浏览器不支持语音";
}

stopSpeech({ delayed: true });
window.addEventListener("pagehide", () => stopSpeech({ delayed: true }));
window.addEventListener("beforeunload", () => stopSpeech({ delayed: true }));
window.addEventListener("unload", () => stopSpeech({ delayed: true }));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopSpeech({ delayed: true });
  }
});
voiceEnabled?.addEventListener("change", () => {
  if (!voiceEnabled.checked) {
    stopSpeech({ delayed: true });
  } else {
    unlockSpeech();
    setVoiceStatus("");
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
  answerBox.classList.remove("markdown-answer");
  setAnswerState(stateName);
  answerBox.textContent = value;
}

function setAnswerMarkdown(value) {
  setAnswerState("");
  answerBox.classList.add("markdown-answer");
  answerBox.innerHTML = renderMarkdown(value);
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

async function loadRelatedItems(requestId = relatedRequestId) {
  const query = state.query;
  const params = new URLSearchParams({
    q: query,
    limit: "8",
  });
  const data = await fetchJson(`/api/items?${params}`);
  if (requestId !== relatedRequestId || query !== state.query) {
    return;
  }
  renderRelatedItems(data.items, data.total);
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
    <button class="item-entry" type="button" data-id="${escapeHtml(item.id)}">
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
let relatedRequestId = 0;
function updateRelatedItems() {
  state.query = questionInput.value.trim();
  state.selectedId = "";
  relatedRequestId += 1;
  relatedList.querySelectorAll("button").forEach((button) => button.classList.remove("active"));
  clearDetail();

  window.clearTimeout(relatedTimer);
  if (!state.query) {
    renderRelatedItems([]);
    return;
  }

  relatedCount.textContent = "检索中";
  relatedList.innerHTML = `<p class="marginalia-empty is-live">正在检索</p>`;
  const requestId = relatedRequestId;
  relatedTimer = window.setTimeout(() => {
    loadRelatedItems(requestId);
  }, 160);
}

askButton.addEventListener("click", askQuestion);
questionInput.addEventListener("input", updateRelatedItems);
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    askQuestion();
  }
});

async function askQuestion() {
  const question = questionInput.value.trim();
  if (!question) {
    setAnswerPlain("请先输入问题。", "error");
    return;
  }

  state.query = question;
  askButton.disabled = true;
  askButton.textContent = "思考中";
  answerMode.textContent = "";
  setAnswerPlain("正在检索数据集并生成回答...", "loading");
  lastSpeechText = "";
  setVoiceStatus("");
  setDigitalHumanState("thinking", "正在检索", "我先从资料库里找和问题最相关的内容。");
  unlockSpeech(true);

  try {
    const payload = await postJson("/api/ask", {
      question,
      category: "",
    });
    setAnswerMarkdown(payload.answer);
    answerMode.textContent = modeLabel(payload.mode);
    setDigitalHumanState("speaking", "正在回答", payload.answer);
    speakAnswer(payload.answer);
    renderRelatedItems(payload.sources, payload.sources.length);
  } catch (error) {
    const message = error.name === "AbortError" ? "问答超时，请稍后再试。" : `问答失败：${error.message}`;
    setAnswerPlain(message, "error");
    setDigitalHumanState("idle", "出现错误", message);
    stopSpeech();
  } finally {
    askButton.disabled = false;
    askButton.textContent = "提问";
  }
}

async function postJson(url, data, timeoutMs = 65000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  } finally {
    window.clearTimeout(timer);
  }
}

function modeLabel(mode) {
  const labels = {
    local: "本地依据式回答",
    llm: "模型生成",
    fallback: "本地回退",
    no_context: "未检索到资料",
    empty: "等待问题",
  };
  return labels[mode] || mode;
}

function setDigitalHumanState(stateName, status, speech) {
  window.clearTimeout(humanIdleTimer);
  digitalHumanPanel.dataset.state = stateName;
  digitalHumanStatus.textContent = status;
  digitalHumanSpeech.textContent = compactSpeech(speech);

  const nextSrc = humanVideos[stateName] || humanVideos.idle;
  if (!digitalHumanVideo.src.endsWith(nextSrc)) {
    digitalHumanVideo.src = nextSrc;
    digitalHumanVideo.load();
  }
  digitalHumanVideo.play().catch(() => {});

  if (stateName === "speaking") {
    humanIdleTimer = window.setTimeout(() => {
      setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
    }, 7000);
  }
}

function speakAnswer(value) {
  lastSpeechText = speechText(value);
  if (!voiceEnabled?.checked || !lastSpeechText) {
    return;
  }
  speakText(lastSpeechText);
}

function speakText(text) {
  if (!speechSupported) {
    setVoiceStatus("浏览器不支持语音");
    return;
  }
  stopSpeech();
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
    setVoiceStatus("正在播报");
  };
  utterance.onend = () => {
    setVoiceStatus("");
  };
  utterance.onerror = () => {
    setVoiceStatus("自动播报被浏览器拦截");
  };

  window.speechSynthesis.speak(utterance);
  window.setTimeout(() => {
    if (!window.speechSynthesis.speaking && !window.speechSynthesis.pending) {
      setVoiceStatus("播报未启动");
    }
  }, 700);
}

function stopSpeech(options = {}) {
  if (speechSupported) {
    window.clearTimeout(speechCancelTimer);
    window.speechSynthesis.cancel();
    if (options.delayed) {
      speechCancelTimer = window.setTimeout(() => window.speechSynthesis.cancel(), 0);
    }
  }
  currentUtterance = null;
}

function unlockSpeech(withThinkingVoice = false) {
  if (!speechSupported || speechUnlocked || !voiceEnabled?.checked) {
    return;
  }
  speechUnlocked = true;
  try {
    const text = withThinkingVoice ? "正在思考" : "语音播报已准备";
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
}

function speechText(value) {
  const text = stripMarkdown(value)
    .replace(/模型接口暂不可用[\s\S]*$/u, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 520 ? `${text.slice(0, 520)}。` : text;
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

function compactSpeech(value) {
  const text = stripMarkdown(value);
  if (!text) {
    return "我在这里。";
  }
  return text.length > 86 ? `${text.slice(0, 86)}...` : text;
}

loadMeta();
renderRelatedItems([]);
