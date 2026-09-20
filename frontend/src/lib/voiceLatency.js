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

export class VoiceLatencyTrace {
  constructor({ now = defaultNow, log = console } = {}) {
    this.now = now;
    this.log = log;
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
  }

  markSpeechEnd(lastVoiceAt) {
    const speechEnd = Number(lastVoiceAt);
    if (!(speechEnd > 0)) return false;
    this.clear();
    this.marks.speechEnd = speechEnd;
    this.marks.utteranceEnd = this.now();
    return true;
  }

  markTranscript() {
    if (this.marks.speechEnd === null || this.marks.transcript !== null) return false;
    this.marks.transcript = this.now();
    return true;
  }

  markFirstDelta() {
    if (this.marks.speechEnd === null || this.marks.firstDelta !== null) return false;
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
    if (this.marks.speechEnd === null || this.reported) return null;
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
      `[叙华][latency trace=${traceId || "-"}] total=${format(metrics.totalMs)} `
      + `eou=${format(metrics.eouMs)} asr_final=${format(metrics.asrFinalMs)} `
      + `agent_first_delta=${format(metrics.agentFirstDeltaMs)} first_phrase=${format(metrics.firstPhraseMs)} `
      + `tts_first_audio=${format(metrics.ttsFirstAudioMs)} audio_start=${format(metrics.audioStartMs)}`,
    );
    return metrics;
  }
}
