import { DEFAULT_LOCALE } from "./locale.js";
import { TtsScheduler } from "./ttsScheduler.js";
import { TtsTextPlan } from "./ttsTextPlan.js";
import {
  compactRecognitionContext,
  requestTtsSource,
  resolveSpeechLocale,
} from "./voiceProtocol.js";

function makeTraceId() {
  return globalThis.crypto?.randomUUID?.() || `tts-${Date.now()}`;
}

export function normalizeSpeechText(value) {
  return String(value || "")
    .replace(/^[ \t]{0,3}#{1,6}[ \t]+/gmu, "")
    .replace(/^[ \t]*[-+*][ \t]+/gmu, "")
    .replace(/(\*\*|__)([^\n]*?)\1/gu, "$2")
    .replace(/`([^`\n]+)`/gu, "$1")
    .replace(/[ \t]+/gu, " ")
    .trim();
}

export class VoiceOutputController {
  constructor({
    websocketPath = "/api/voice",
    getRecognitionContext = () => null,
    createScheduler = (options) => new TtsScheduler(options),
    createTraceId = makeTraceId,
    onEvent = () => {},
    onPlayingChange = () => {},
    onTerminal = () => {},
  } = {}) {
    this.websocketPath = websocketPath;
    this.getRecognitionContext = getRecognitionContext;
    this.createTraceId = createTraceId;
    this.onEvent = onEvent;
    this.onPlayingChange = onPlayingChange;
    this.onTerminal = onTerminal;
    this.pipelineActive = false;
    this.playing = false;
    this.traceId = "";
    this.locale = DEFAULT_LOCALE;
    this.textPlan = new TtsTextPlan(DEFAULT_LOCALE);
    this.scheduler = createScheduler({
      prepareSource: ({ text, segment, reason, locale, signal }) => requestTtsSource({
        websocketPath: this.websocketPath,
        text,
        traceId: this.traceId,
        segment,
        reason,
        locale,
        signal,
      }),
      onEvent: (event) => this.onEvent(event),
      onPlayingChange: (playing) => {
        this.playing = playing;
        this.onPlayingChange(playing);
      },
      onTerminal: ({ failed }) => {
        this.clearTurnState();
        this.onTerminal({ failed });
      },
    });
  }

  setWebsocketPath(path) {
    this.websocketPath = String(path || "/api/voice");
  }

  clearTurnState() {
    this.pipelineActive = false;
    this.playing = false;
    this.traceId = "";
    this.locale = DEFAULT_LOCALE;
    this.textPlan.reset(DEFAULT_LOCALE);
  }

  begin(locale = "") {
    const generation = this.scheduler.begin();
    this.pipelineActive = true;
    this.traceId = this.createTraceId();
    this.locale = resolveSpeechLocale(
      locale,
      compactRecognitionContext(this.getRecognitionContext()).locale_hint,
    );
    this.textPlan.reset(this.locale);
    this.playing = false;
    return generation;
  }

  stop() {
    this.scheduler.stop();
    this.clearTurnState();
    return true;
  }

  enqueue(segment, reason) {
    const content = normalizeSpeechText(segment);
    if (!content) return false;
    return this.scheduler.enqueue(content, {
      reason,
      locale: this.locale,
    });
  }

  append(text, locale = "") {
    const delta = String(text || "");
    if (!delta) return false;
    if (!this.pipelineActive) this.begin(locale);
    const firstSegment = this.textPlan.append(delta);
    if (firstSegment) this.enqueue(firstSegment, "first_sentence");
    return true;
  }

  finish(fallbackText = "", locale = "") {
    if (!this.pipelineActive) this.begin(locale);
    const remainder = this.textPlan.finish();
    if (remainder) this.enqueue(remainder, "text_complete");
    else if (fallbackText && !this.scheduler.hasSegments) {
      this.enqueue(fallbackText, "text_complete");
    }
    this.scheduler.complete();
    return true;
  }
}
