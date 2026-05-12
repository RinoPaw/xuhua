import { browserSpeechSupported, audioSpeechSupported, speechSupported } from './consts.js';
import { currentHumanState, setDigitalHumanState } from './human.js';
import { els } from './state.js';
import { stripMarkdown } from './markdown.js';

let currentUtterance = null;
let currentSpeechAudio = null;
let currentSpeechSegments = [];
export let lastSpeechText = "";
export function resetLastSpeechText() {
  lastSpeechText = "";
}
export let lastSpeechAudioUrl = "";
let speechPlaybackSeq = 0;
let speechUnlocked = false;
let speechCancelTimer = 0;
let speechStartGuardTimer = 0;
export let voiceState = "idle";
export let voiceEnabled = true;
export let lastSpeechHumanState = "speaking";

export function setVoiceEnabled(enabled) {
  voiceEnabled = enabled;
  if (!enabled) {
    stopSpeech();
  }
  setVoiceState(enabled ? "idle" : "disabled");
  setVoiceStatus(enabled ? "" : "已关闭");
  refreshVoiceToggleUI();
}

function refreshVoiceToggleUI() {
  if (!els.voiceToggle) return;
  if (!voiceEnabled) {
    els.voiceToggle.dataset.state = "disabled";
    els.voiceToggle.setAttribute("disabled", "disabled");
    els.voiceToggle.setAttribute("aria-pressed", "false");
    els.voiceToggle.classList.remove("is-speaking");
    const label = els.voiceToggle.querySelector(".voice-label");
    if (label) label.textContent = "已关闭";
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
    if (label) label.textContent = "播报";
  }
}

export function speakAnswer(value, audioUrl = "", options = {}) {
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

export function finishSpeechPlayback(status = "") {
  clearSpeechStartGuard();
  currentUtterance = null;
  currentSpeechAudio = null;
  currentSpeechSegments = [];
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
  syncVoiceIdleState("");
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

export function speakText(text, playbackSeq = ++speechPlaybackSeq) {
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

export function playAudioAnswer(audioUrl, fallbackText = "", playbackSeq = ++speechPlaybackSeq, options = {}) {
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

export function requestServerSpeech(text, playbackSeq) {
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

export function requestServerSpeechFile(text, playbackSeq) {
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

export function speechPlaybackSegments(text) {
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
  if (!speechSupported) {
    setVoiceState("disabled");
    setVoiceStatus("浏览器不支持语音");
    return;
  }
  setVoiceState("idle");
  setVoiceStatus(status);
}
