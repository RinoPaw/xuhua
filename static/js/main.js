import { state, bindElements, els } from './state.js';
import { speechSupported } from './consts.js';
import { initHuman, configureHumanVideoPlayback, scheduleHumanVideoAdvance, restoreHumanVideoAfterVisibility } from './human.js';
import { stopSpeech, unlockSpeech, setVoiceStatus, voiceState, replayLastSpeech, hasReplayableSpeech, pauseSpeechForVisibility, resumeSpeechAfterVisibility } from './speech.js';
import { renderQuerySuggestions, loadMeta, resizeQuestionInput, syncRestoredQuestion, handleQuestionInput } from './ui.js';
import { renderRelatedItems, updateRelatedPanelTitle, searchRightPanel, searchByCategory, showDetail, hideDetail } from './search.js';
import { askQuestion } from './ask.js';

function init() {
  bindElements({
    relatedList: document.querySelector("#relatedList"),
    relatedCount: document.querySelector("#relatedCount"),
    relatedTitle: document.querySelector("#relatedTitle"),
    metaText: document.querySelector("#metaText"),
    questionInput: document.querySelector("#questionInput"),
    querySuggestions: document.querySelector("#querySuggestions"),
    askButton: document.querySelector("#askButton"),
    voiceToggle: document.querySelector("#voiceToggle"),
    voiceStatus: document.querySelector("#voiceStatus"),
    answerBox: document.querySelector("#answerBox"),
    answerMode: document.querySelector("#answerMode"),
    digitalHumanPanel: document.querySelector(".hanging-scroll"),
    digitalHumanVideo: document.querySelector("#digitalHumanVideo"),
    digitalHumanVideoNext: document.querySelector("#digitalHumanVideoNext"),
    digitalHumanStatus: document.querySelector("#digitalHumanStatus"),
    digitalHumanSpeech: document.querySelector("#digitalHumanSpeech"),
    rightSearchInput: document.querySelector("#rightSearchInput"),
    rightSearchButton: document.querySelector("#rightSearchButton"),
    searchMode: document.querySelector("#searchMode"),
    detailMode: document.querySelector("#detailMode"),
    backToSearch: document.querySelector("#backToSearch"),
    detailCategory: document.querySelector("#detailCategory"),
    detailTitle: document.querySelector("#detailTitle"),
    detailMeta: document.querySelector("#detailMeta"),
    detailSupport: document.querySelector("#detailSupport"),
    detailBody: document.querySelector("#detailBody"),
  });

  initHuman();
  stopSpeech({ delayed: true, preserveHuman: true });

  // Initial setup
  configureHumanVideoPlayback(els.digitalHumanVideo, "idle");
  scheduleHumanVideoAdvance(els.digitalHumanVideo, "idle");
  renderQuerySuggestions();
  loadMeta();
  updateRelatedPanelTitle();
  syncRestoredQuestion();

  // Event listeners
  els.askButton?.addEventListener("click", askQuestion);
  els.questionInput?.addEventListener("input", handleQuestionInput);
  els.questionInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      askQuestion();
    }
  });

  // Right panel search
  els.rightSearchButton?.addEventListener("click", searchRightPanel);
  els.rightSearchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchRightPanel();
  });

  // Category chips
  document.querySelectorAll("#categoryChips button").forEach((btn) => {
    btn.addEventListener("click", () => searchByCategory(btn.dataset.category));
  });

  // Detail back button
  els.backToSearch?.addEventListener("click", hideDetail);

  // Voice toggle — on/off switch
  els.voiceToggle?.addEventListener("click", () => {
    if (!speechSupported) {
      setVoiceStatus("浏览器不支持语音");
      return;
    }
    if (voiceState === "speaking") {
      stopSpeech({ preserveHuman: true });
      return;
    }
    if (hasReplayableSpeech()) {
      replayLastSpeech();
      return;
    }
    setVoiceStatus("暂无可播报内容");
  });

  // SpeechSynthesis voice list
  window.speechSynthesis?.addEventListener?.("voiceschanged", () => {
    window.speechSynthesis.getVoices();
  });

  // Page lifecycle — stop speech
  window.addEventListener("pagehide", () => stopSpeech({ delayed: true }));
  window.addEventListener("beforeunload", () => stopSpeech({ delayed: true }));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      pauseSpeechForVisibility();
    } else {
      restoreHumanVideoAfterVisibility();
      resumeSpeechAfterVisibility();
    }
  });

  // Restore question on pageshow
  window.addEventListener("pageshow", syncRestoredQuestion);
}

init();
