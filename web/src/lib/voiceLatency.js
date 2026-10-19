function defaultNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function elapsed(start, end) {
  if (!(Number.isFinite(start) && Number.isFinite(end)) || end < start) return null;
  return Math.round((end - start) * 10) / 10;
}

function format(value) {
  return value === null ? "-" : `${value.toFixed(1)}ms`;
}

// Never place provider exception messages, transcript contents, or arbitrary
// server strings into diagnostics; only operational result codes are useful.
function resultCode(value) {
  const code = String(value || "").trim();
  return /^[a-z][a-z0-9_]{0,63}$/u.test(code) ? code : "unknown";
}

const TERMINAL_OUTCOMES = new Set([
  "completed", "failed", "cancelled", "interrupted", "disconnected",
  "superseded", "rejected",
]);

export class VoiceLatencyTrace {
  constructor({ now = defaultNow, log = console, onFinish = () => {} } = {}) {
    this.now = now;
    this.log = log;
    this.onFinish = onFinish;
    this.clear();
  }

  clear() {
    this.marks = {
      speechEnd: null,
      utteranceEnd: null,
      transcript: null,
      firstDelta: null,
      ttsRequest: null,
      firstAudio: null,
      playing: null,
    };
    this.reported = false;
    this.finished = false;
    this.context = {
      connectionId: "",
      utteranceId: null,
      turnId: "",
    };
  }

  markSpeechEnd(lastVoiceAt) {
    const speechEnd = Number(lastVoiceAt);
    if (!(speechEnd > 0)) return false;
    this.finish("superseded");
    this.clear();
    this.marks.speechEnd = speechEnd;
    this.marks.utteranceEnd = this.now();
    return true;
  }

  markTranscript(event = {}) {
    if (this.marks.speechEnd === null || this.marks.transcript !== null) return false;
    this.context.connectionId = String(event.connection_id || "");
    this.context.utteranceId = event.utterance_id ?? null;
    this.marks.transcript = this.now();
    return true;
  }

  noteTurn(event = {}) {
    if (this.marks.speechEnd === null) return false;
    this.context.connectionId ||= String(event.connection_id || "");
    this.context.turnId ||= String(event.turn_id || "");
    return true;
  }

  markFirstDelta(event = {}) {
    if (this.marks.speechEnd === null || this.marks.firstDelta !== null) return false;
    this.noteTurn(event);
    this.marks.firstDelta = this.now();
    return true;
  }

  markTtsRequest() {
    if (this.marks.speechEnd === null || this.marks.ttsRequest !== null) return false;
    this.marks.ttsRequest = this.now();
    return true;
  }

  markFirstAudio() {
    if (this.marks.speechEnd === null || this.marks.firstAudio !== null) return false;
    this.marks.firstAudio = this.now();
    return true;
  }

  markPlaying(traceId = "-") {
    if (this.marks.speechEnd === null || this.reported || this.finished) return null;
    if (this.marks.playing === null) this.marks.playing = this.now();
    const metrics = {
      totalMs: elapsed(this.marks.speechEnd, this.marks.playing),
      eouMs: elapsed(this.marks.speechEnd, this.marks.utteranceEnd),
      asrFinalMs: elapsed(this.marks.utteranceEnd, this.marks.transcript),
      agentFirstDeltaMs: elapsed(this.marks.transcript, this.marks.firstDelta),
      firstPhraseMs: elapsed(this.marks.firstDelta, this.marks.ttsRequest),
      ttsFirstAudioMs: elapsed(this.marks.ttsRequest, this.marks.firstAudio),
      audioStartMs: elapsed(this.marks.firstAudio, this.marks.playing),
    };
    this.reported = true;
    this.log.info?.(
      `[叙华][latency connection=${this.context.connectionId || "-"} `
      + `utterance=${this.context.utteranceId ?? "-"} turn=${this.context.turnId || "-"} `
      + `tts_trace=${traceId || "-"}] total=${format(metrics.totalMs)} `
      + `eou=${format(metrics.eouMs)} asr_final=${format(metrics.asrFinalMs)} `
      + `agent_first_delta=${format(metrics.agentFirstDeltaMs)} first_phrase=${format(metrics.firstPhraseMs)} `
      + `tts_first_audio=${format(metrics.ttsFirstAudioMs)} audio_start=${format(metrics.audioStartMs)}`,
    );
    return metrics;
  }

  /** Exactly one privacy-safe terminal record per speech attempt.

      This deliberately logs failed, rejected and interrupted attempts as well
      as successful ones, so latency analyses are not success-only samples. */
  finish(outcome, { reason = "" } = {}) {
    if (this.marks.speechEnd === null || this.finished) return false;
    this.finished = true;
    const result = TERMINAL_OUTCOMES.has(outcome) ? outcome : "failed";
    const terminalMs = elapsed(this.marks.speechEnd, this.now());
    this.onFinish({ outcome: result, played: this.marks.playing !== null,
      elapsedMs: this.marks.playing !== null ? elapsed(this.marks.speechEnd, this.marks.playing) : terminalMs,
      attempt: `${this.context.connectionId || "voice"}_${this.marks.speechEnd}`.replace(/[^A-Za-z0-9_-]/gu, "_").slice(-72) });
    this.log.info?.(
      `[叙华][voice.outcome connection=${this.context.connectionId || "-"} `
      + `utterance=${this.context.utteranceId ?? "-"} turn=${this.context.turnId || "-"}] `
      + `result=${result} reason=${resultCode(reason)} `
      + `elapsed=${format(terminalMs)} `
      + `transcribed=${this.marks.transcript !== null} `
      + `first_delta=${this.marks.firstDelta !== null} `
      + `first_audio=${this.marks.firstAudio !== null} `
      + `playing=${this.marks.playing !== null}`,
    );
    return true;
  }
}
