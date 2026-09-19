import { DEFAULT_LOCALE } from "./locale.js";
import { TtsScheduler } from "./ttsScheduler.js";
import { TtsTextPlan } from "./ttsTextPlan.js";
import {
  buildTtsUrl,
  compactRecognitionContext,
  resolveSpeechLocale,
} from "./voiceProtocol.js";

function makeTraceId() {
  return globalThis.crypto?.randomUUID?.() || `tts-${Date.now()}`;
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
      onEvent: (event) => this.onEvent(event),
      onPlayingChange: (playing) => {
        this.playing = playing;
        this.onPlayingChange(playing);
      },
      onTerminal: ({ failed }) => {
        this.pipelineActive = false;
        this.playing = false;
        this.onTerminal({ failed });
      },
    });
  }

  setWebsocketPath(path) {
    this.websocketPath = String(path || "/api/voice");
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
    this.pipelineActive = false;
    this.playing = false;
    this.textPlan.reset();
    return true;
  }

  enqueue(segment, reason) {
    const content = String(segment || "").replace(/[#*_`>-]/g, " ").trim();
    if (!content) return false;
    const url = buildTtsUrl({
      websocketPath: this.websocketPath,
      text: content,
      traceId: this.traceId,
      segment: this.scheduler.segmentCount,
      reason,
      locale: this.locale,
    });
    return this.scheduler.enqueue(content, { url, reason });
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

  speak(text, locale = "") {
    const content = String(text || "").trim();
    if (!content) return false;
    this.begin(locale);
    this.append(content, locale);
    return this.finish("", locale);
  }
}
