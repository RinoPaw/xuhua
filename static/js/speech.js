import { browserSpeechSupported, audioSpeechSupported, speechSupported } from './consts.js';
import { currentHumanState, setDigitalHumanState } from './human.js';
import { els } from './state.js';
import { stripMarkdown } from './markdown.js';

let currentUtterance = null;
let currentSpeechAudio = null;
let currentSpeechSegments = [];
export let lastSpeechText = "";
export let lastSpeechAudioUrl = "";
let lastSpeechUsesServerTts = false;
let lastSpeechLang = "zh-CN";
let speechPlaybackSeq = 0;
let speechUnlocked = false;
let speechCancelTimer = 0;
let speechStartGuardTimer = 0;
export let voiceState = "idle";
export let voiceEnabled = true;
export let lastSpeechHumanState = "speaking";
let pendingSpeechRewrite = false;
let visibilityInterruptedPlayback = false;
let visibilityInterruptedMode = "";

function syncVoiceStatusVisuals(value = "") {
  if (!els.voiceToggle) {
    return;
  }
  els.voiceToggle.classList.toggle("is-rewriting", value === "正在润色播报");
}

export function setVoiceEnabled(enabled) {
  voiceEnabled = enabled;
  if (!enabled) {
    pendingSpeechRewrite = false;
    visibilityInterruptedPlayback = false;
    visibilityInterruptedMode = "";
    stopSpeech();
    setVoiceState("disabled");
    setVoiceStatus("已暂停");
    refreshVoiceToggleUI();
    return;
  }
  if (lastSpeechText) {
    setVoiceState("speaking");
    refreshVoiceToggleUI();
    speakAnswer(lastSpeechText, lastSpeechAudioUrl, { serverTts: lastSpeechUsesServerTts, lang: lastSpeechLang });
  } else {
    setVoiceState("idle");
    setVoiceStatus("");
    refreshVoiceToggleUI();
  }
}

export function hasReplayableSpeech() {
  return Boolean(lastSpeechText);
}

export function replayLastSpeech() {
  if (!lastSpeechText) {
    setVoiceStatus("暂无可播报内容");
    return false;
  }
  if (!voiceEnabled) {
    voiceEnabled = true;
  }
  return speakAnswer(lastSpeechText, lastSpeechAudioUrl, { serverTts: lastSpeechUsesServerTts, lang: lastSpeechLang });
}

export function cacheSpeechResult(text, audioUrl = "", options = {}) {
  lastSpeechText = speechText(text);
  lastSpeechAudioUrl = audioUrl || "";
  lastSpeechUsesServerTts = Boolean(options.serverTts || audioUrl);
  lastSpeechLang = normalizeSpeechLang(options.lang || lastSpeechText);
}

export function clearSpeechCache() {
  lastSpeechText = "";
  lastSpeechAudioUrl = "";
  lastSpeechUsesServerTts = false;
  lastSpeechLang = "zh-CN";
  pendingSpeechRewrite = false;
  visibilityInterruptedPlayback = false;
  visibilityInterruptedMode = "";
}

export function markSpeechRewritePending(pending = true) {
  pendingSpeechRewrite = pending;
  if (!voiceEnabled || voiceState === "speaking") {
    return;
  }
  setVoiceStatus(pending ? "正在润色播报" : "");
}

export function pauseSpeechForVisibility() {
  if (!voiceEnabled) {
    return;
  }
  if (currentSpeechAudio) {
    visibilityInterruptedPlayback = true;
    visibilityInterruptedMode = "audio";
    clearSpeechStartGuard();
    currentSpeechAudio.pause();
    setVoiceState("idle");
    setVoiceStatus("播报已暂停");
    return;
  }
  if (browserSpeechSupported && currentUtterance && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
    visibilityInterruptedPlayback = true;
    visibilityInterruptedMode = "browser";
    clearSpeechStartGuard();
    window.speechSynthesis.pause();
    setVoiceState("idle");
    setVoiceStatus("播报已暂停");
    return;
  }
  visibilityInterruptedPlayback = false;
  visibilityInterruptedMode = "";
  stopSpeech({
    delayed: true,
    preserveHuman: true,
    preserveIdleStatus: true,
    pausedByVisibility: true,
  });
}

export function resumeSpeechAfterVisibility() {
  if (!voiceEnabled) {
    visibilityInterruptedPlayback = false;
    visibilityInterruptedMode = "";
    return;
  }
  if (visibilityInterruptedPlayback && visibilityInterruptedMode === "audio" && currentSpeechAudio) {
    visibilityInterruptedPlayback = false;
    visibilityInterruptedMode = "";
    const playPromise = currentSpeechAudio.play();
    if (playPromise?.catch) {
      playPromise.catch(() => {
        speakAnswer(lastSpeechText, lastSpeechAudioUrl, { serverTts: lastSpeechUsesServerTts, lang: lastSpeechLang });
      });
    }
    return;
  }
  if (visibilityInterruptedPlayback && visibilityInterruptedMode === "browser" && currentUtterance) {
    visibilityInterruptedPlayback = false;
    visibilityInterruptedMode = "";
    window.speechSynthesis.resume();
    setVoiceState("speaking");
    setVoiceStatus("正在播报");
    return;
  }
  if (visibilityInterruptedPlayback && lastSpeechText) {
    visibilityInterruptedPlayback = false;
    visibilityInterruptedMode = "";
    speakAnswer(lastSpeechText, lastSpeechAudioUrl, { serverTts: lastSpeechUsesServerTts, lang: lastSpeechLang });
    return;
  }
  visibilityInterruptedPlayback = false;
  visibilityInterruptedMode = "";
  if (pendingSpeechRewrite) {
    setVoiceStatus("正在润色播报");
  } else if (voiceState !== "speaking") {
    setVoiceStatus("");
  }
}

function refreshVoiceToggleUI() {
  if (!els.voiceToggle) return;
  if (!voiceEnabled) {
    els.voiceToggle.dataset.state = "disabled";
    els.voiceToggle.removeAttribute("disabled");
    els.voiceToggle.setAttribute("aria-pressed", "false");
    els.voiceToggle.classList.remove("is-speaking");
    const label = els.voiceToggle.querySelector(".voice-label");
    if (label) label.textContent = "暂停播报";
  } else if (voiceState === "speaking") {
    els.voiceToggle.dataset.state = "speaking";
    els.voiceToggle.removeAttribute("disabled");
    els.voiceToggle.setAttribute("aria-pressed", "true");
    els.voiceToggle.classList.add("is-speaking");
    const label = els.voiceToggle.querySelector(".voice-label");
    if (label) label.textContent = "播报中";
  } else {
    els.voiceToggle.dataset.state = "idle";
    els.voiceToggle.removeAttribute("disabled");
    els.voiceToggle.setAttribute("aria-pressed", "true");
    els.voiceToggle.classList.remove("is-speaking");
    const label = els.voiceToggle.querySelector(".voice-label");
    if (label) label.textContent = "等待播报";
  }
}

export function speakAnswer(value, audioUrl = "", options = {}) {
  pendingSpeechRewrite = false;
  lastSpeechText = speechText(value);
  lastSpeechAudioUrl = audioUrl || "";
  lastSpeechUsesServerTts = Boolean(options.serverTts || audioUrl);
  lastSpeechLang = normalizeSpeechLang(options.lang || lastSpeechText);
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
  return speakText(lastSpeechText, playbackSeq, { lang: lastSpeechLang });
}

export function finishSpeechPlayback(status = "") {
  clearSpeechStartGuard();
  currentUtterance = null;
  currentSpeechAudio = null;
  currentSpeechSegments = [];
  visibilityInterruptedPlayback = false;
  visibilityInterruptedMode = "";
  syncVoiceIdleState(status);
  if (currentHumanState === "speaking" || currentHumanState === "farewell") {
    setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
  }
}

export function stopSpeech(options = {}) {
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
  visibilityInterruptedMode = "";
  syncVoiceIdleState("", options);
  if (!options.preserveHuman && (currentHumanState === "speaking" || currentHumanState === "farewell")) {
    setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
  }
}

export function unlockSpeech(withThinkingVoice = false) {
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

export function setVoiceStatus(value) {
  if (els.voiceStatus) {
    els.voiceStatus.textContent = value;
  }
  syncVoiceStatusVisuals(value);
  if (value) {
    els.voiceStatus.classList.add("is-active");
  } else {
    els.voiceStatus.classList.remove("is-active");
  }
}

export function setVoiceState(state) {
  voiceState = state;
  refreshVoiceToggleUI();
}

export function speakText(text, playbackSeq = ++speechPlaybackSeq, options = {}) {
  if (!browserSpeechSupported) {
    setVoiceStatus("浏览器不支持语音");
    return false;
  }
  stopSpeech({ preserveHuman: true, keepPlaybackSeq: true });
  clearSpeechStartGuard();
  const lang = normalizeSpeechLang(options.lang || text);
  const segments = speechPlaybackSegments(text, lang);
  return playBrowserSpeechSegment(segments, 0, playbackSeq, lang);
}

export function playBrowserSpeechSegment(segments, index, playbackSeq, lang = "zh-CN") {
  const text = segments[index] || "";
  if (!text) {
    finishSpeechPlayback("");
    return true;
  }
  window.speechSynthesis.resume();
  const utterance = new SpeechSynthesisUtterance(text);
  currentUtterance = utterance;
  utterance.lang = lang;
  utterance.rate = 1;
  utterance.pitch = 1;

  const voices = window.speechSynthesis.getVoices();
  const preferredVoice = pickSpeechVoice(voices, lang);
  if (preferredVoice) {
    utterance.voice = preferredVoice;
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
    playBrowserSpeechSegment(segments, index + 1, playbackSeq, lang);
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

export function playAudioAnswer(audioUrl, fallbackText = "", playbackSeq = ++speechPlaybackSeq, options = {}) {
  if (!audioSpeechSupported || !audioUrl) {
    return speakText(fallbackText, playbackSeq, { lang: lastSpeechLang });
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
    if (!speakText(fallbackText, playbackSeq, { lang: lastSpeechLang })) {
      finishSpeechPlayback("音频播报失败");
    }
  };
  const playPromise = audio.play();
  if (playPromise?.catch) {
    playPromise.catch(() => {
      if (currentSpeechAudio !== audio || speechPlaybackSeq !== playbackSeq) return;
      currentSpeechAudio = null;
      if (options.onError?.()) return;
      if (!speakText(fallbackText, playbackSeq, { lang: lastSpeechLang })) {
        finishSpeechPlayback("自动播报被浏览器拦截");
      }
    });
  }
  return true;
}

export function requestServerSpeech(text, playbackSeq) {
  if (!audioSpeechSupported) {
    return speakText(text, playbackSeq, { lang: lastSpeechLang });
  }
  stopSpeech({ preserveHuman: true, keepPlaybackSeq: true });
  setVoiceState("speaking");
  setVoiceStatus("正在播报");
  currentSpeechSegments = speechPlaybackSegments(text);
  if (currentSpeechSegments.length) {
    return playSpeechSegment(0, playbackSeq);
  }
  return requestServerSpeechFile(text, playbackSeq);
}

export function requestServerSpeechFile(text, playbackSeq) {
  if (speechPlaybackSeq !== playbackSeq || lastSpeechText !== text) {
    return true;
  }
  setVoiceState("speaking");
  setVoiceStatus("正在播报");
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
      } else if (!speakText(text, playbackSeq, { lang: lastSpeechLang })) {
        finishSpeechPlayback("语音暂不可用");
      }
    })
    .catch(() => {
      if (speechPlaybackSeq !== playbackSeq || lastSpeechText !== text) return;
      if (!speakText(text, playbackSeq, { lang: lastSpeechLang })) {
        finishSpeechPlayback("语音生成失败");
      }
    });
  return true;
}

export function playSpeechSegment(index, playbackSeq) {
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

export function speechPlaybackSegments(text, lang = "zh-CN") {
  const source = String(text || "").trim();
  if (!source) return [];
  const splitter = lang === "en-US"
    ? /[^.!?;]+[.!?;]?/gu
    : /[^。！？!?；;]+[。！？!?；;]?/gu;
  const pieces = source.match(splitter) || [source];
  const segments = [];
  let current = "";
  const maxBytes = lang === "en-US" ? 320 : 720;
  for (const piece of pieces) {
    const candidate = current + piece;
    if (current && utf8ByteLength(candidate) > maxBytes) {
      segments.push(current);
      current = piece;
    } else {
      current = candidate;
    }
    while (utf8ByteLength(current) > maxBytes) {
      segments.push(sliceUtf8Bytes(current, maxBytes));
      current = current.slice(segments[segments.length - 1].length);
    }
  }
  if (current) {
    segments.push(current);
  }
  return segments;
}

export function utf8ByteLength(value) {
  return new TextEncoder().encode(String(value || "")).length;
}

export function sliceUtf8Bytes(value, maxBytes) {
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

export function ttsStreamUrl(text) {
  const params = new URLSearchParams({ text });
  return `/api/tts/stream?${params.toString()}`;
}

export function speechText(value) {
  const text = stripSpeechDecorations(value)
    .replace(/模型接口暂不可用[\s\S]*$/u, "")
    .replace(/\s+/g, " ")
    .trim();
  return text;
}

export function normalizeSpeechLang(value) {
  const text = String(value || "").trim();
  if (/^en(?:-[A-Z]{2})?$/i.test(text)) {
    return "en-US";
  }
  const latinCount = (text.match(/[A-Za-z]/g) || []).length;
  const chineseCount = (text.match(/[\u4e00-\u9fff]/g) || []).length;
  if (latinCount >= 24 && latinCount > chineseCount * 2) {
    return "en-US";
  }
  return "zh-CN";
}

export function pickSpeechVoice(voices, lang = "zh-CN") {
  if (!Array.isArray(voices) || !voices.length) {
    return null;
  }
  if (lang === "en-US") {
    const englishVoices = voices.filter((voice) => /en|English/i.test(`${voice.lang} ${voice.name}`));
    if (!englishVoices.length) {
      return null;
    }
    const preferredFemaleEnglishVoice = englishVoices.find((voice) =>
      /zira|aria|ava|jenny|emma|samantha|victoria|hazel|susan|sara|sonia|libby|female|woman/i.test(voice.name || ""),
    );
    return preferredFemaleEnglishVoice || englishVoices[0] || null;
  }
  return voices.find((voice) => /zh|Chinese|普通话|中文/i.test(`${voice.lang} ${voice.name}`)) || null;
}

export function stripSpeechDecorations(value) {
  return stripMarkdown(value)
    .replace(/[\u{1F1E6}-\u{1F1FF}\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function clearSpeechStartGuard() {
  window.clearTimeout(speechStartGuardTimer);
  speechStartGuardTimer = 0;
}

function syncVoiceIdleState(status = "") {
  const options = arguments[1] || {};
  if (!voiceEnabled) {
    return;
  }
  if (!speechSupported) {
    setVoiceState("disabled");
    setVoiceStatus("浏览器不支持语音");
    return;
  }
  setVoiceState("idle");
  if (status) {
    setVoiceStatus(status);
    return;
  }
  if (options.pausedByVisibility) {
    setVoiceStatus("播报已暂停");
    return;
  }
  if (options.preserveIdleStatus) {
    return;
  }
  setVoiceStatus(pendingSpeechRewrite ? "正在润色播报" : "");
}
