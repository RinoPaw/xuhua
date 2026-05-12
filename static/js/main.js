import { state, bindElements, els } from './state.js';
import { speechSupported } from './consts.js';
import { initHuman, configureHumanVideoPlayback, scheduleHumanVideoAdvance, restoreHumanVideoAfterVisibility } from './human.js';
import { stopSpeech, unlockSpeech, setVoiceStatus, voiceEnabled, setVoiceEnabled } from './speech.js';
import { renderQuerySuggestions, loadMeta, resizeQuestionInput, syncRestoredQuestion, handleQuestionInput } from './ui.js';
import { updateRelatedItems, renderRelatedItems, updateRelatedPanelTitle } from './search.js';
import { askQuestion } from './ask.js';

function init() {
  bindElements({
    relatedList: document.querySelector("#relatedList"),
    relatedCount: document.querySelector("#relatedCount"),
    relatedTitle: document.querySelector("#relatedTitle"),
    metaText: document.querySelector("#metaText"),
    detailEmpty: document.querySelector("#detailEmpty"),
    detailContent: document.querySelector("#detailContent"),
    detailPanel: document.querySelector(".marginalia"),
    detailCategory: document.querySelector("#detailCategory"),
    detailTitle: document.querySelector("#detailTitle"),
    detailMeta: document.querySelector("#detailMeta"),
    detailSupport: document.querySelector("#detailSupport"),
    detailSummary: document.querySelector("#detailSummary"),
    detailBody: document.querySelector("#detailBody"),
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

  // Voice toggle — on/off switch
  els.voiceToggle?.addEventListener("click", () => {
    if (!speechSupported) {
      setVoiceStatus("浏览器不支持语音");
      return;
    }
    setVoiceEnabled(!voiceEnabled);
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
      stopSpeech({ delayed: true });
    } else {
      // Browser may have suspended video playback while tab was hidden
      restoreHumanVideoAfterVisibility();
    }
  });

  // Restore question on pageshow
  window.addEventListener("pageshow", syncRestoredQuestion);
}

init();
