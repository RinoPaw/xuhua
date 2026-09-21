const MAX_SEGMENTS = 2;
const MAX_AUDIO_RETRIES = 2;
const RETRY_DELAYS_MS = [300, 800];

function now() {
  return typeof performance !== "undefined" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
}

function noop() {}

function callSafely(callback, value) {
  try {
    callback(value);
  } catch {
    // Observability must never break audio scheduling.
  }
}

function withRetryMarker(url, retry) {
  const separator = String(url).includes("?") ? "&" : "?";
  return `${url}${separator}tts_retry=${retry}`;
}

function guessSpeechLocale(text) {
  const value = String(text || "");
  if (/[\u3040-\u30ff]/u.test(value)) return "ja-JP";
  if (/[\uac00-\ud7af]/u.test(value)) return "ko-KR";
  if (/[\u3400-\u9fff]/u.test(value)) return "zh-CN";
  return "en-US";
}

function browserFallbackSpeak(
  text,
  { onStart = noop, onEnd = noop, onError = noop, locale = "" } = {},
) {
  const synthesis = globalThis?.speechSynthesis;
  const Utterance = globalThis?.SpeechSynthesisUtterance;
  if (!synthesis || typeof synthesis.speak !== "function" || typeof Utterance !== "function") return null;

  let utterance;
  try {
    utterance = new Utterance(String(text || ""));
    utterance.lang = String(locale || "").trim() || guessSpeechLocale(text);
    utterance.onstart = () => onStart();
    utterance.onend = () => onEnd();
    utterance.onerror = (event) => onError(event || new Error("speech_synthesis_failed"));
    synthesis.speak(utterance);
  } catch (error) {
    onError(error);
    return null;
  }

  return () => {
    utterance.onstart = null;
    utterance.onend = null;
    utterance.onerror = null;
    try {
      synthesis.cancel();
    } catch {
      // Browser speech synthesis may already have stopped itself.
    }
  };
}

/**
 * Schedules the two browser TTS segments produced by TtsTextPlan.
 *
 * A source may be prepared asynchronously before the Audio element is created.
 * This lets the browser POST private speech text for a short-lived stream URL,
 * while preserving native streaming playback from the resulting GET source.
 */
export class TtsScheduler {
  constructor({
    createAudio = (url) => new Audio(url),
    prepareSource = () => "",
    onEvent = noop,
    onPlayingChange = noop,
    onTerminal = noop,
    fallbackSpeak = browserFallbackSpeak,
    scheduleRetry = (callback, delay) => setTimeout(callback, delay),
    cancelRetry = (timer) => clearTimeout(timer),
  } = {}) {
    this.createAudio = createAudio;
    this.prepareSource = prepareSource;
    this.onEvent = onEvent;
    this.onPlayingChange = onPlayingChange;
    this.onTerminal = onTerminal;
    this.fallbackSpeak = fallbackSpeak;
    this.scheduleRetry = scheduleRetry;
    this.cancelRetry = cancelRetry;
    this.generation = 0;
    this.activeGeneration = 0;
    this.entries = new Map();
    this.nextSegment = 0;
    this.completed = false;
    this.current = null;
    this.playing = false;
    this.terminal = false;
  }

  get isPlaying() {
    return this.playing;
  }

  get segmentCount() {
    return this.entries.size;
  }

  get hasSegments() {
    return this.entries.size > 0;
  }

  begin() {
    this.stop();
    this.generation += 1;
    this.activeGeneration = this.generation;
    this.entries = new Map();
    this.nextSegment = 0;
    this.completed = false;
    this.current = null;
    this.terminal = false;
    return this.activeGeneration;
  }

  enqueue(text, { reason = "text_complete", locale = "" } = {}) {
    const content = String(text || "").trim();
    if (!content || this.completed || this.terminal || this.entries.size >= MAX_SEGMENTS) {
      return false;
    }

    const segment = this.nextSegment;
    this.nextSegment += 1;
    if (segment >= MAX_SEGMENTS) return false;

    const entry = {
      audio: null,
      url: "",
      content,
      locale: String(locale || ""),
      generation: this.activeGeneration,
      segment,
      reason,
      startedAt: now(),
      started: false,
      ended: false,
      firstChunk: false,
      handlers: null,
      retryCount: 0,
      retryTimer: null,
      useFallback: false,
      fallbackCancel: null,
      prepareController: new AbortController(),
    };
    this.entries.set(segment, entry);
    this.emit({ type: "request.start", segment, reason, elapsedMs: 0 });
    this.prepare(entry);
    return true;
  }

  prepare(entry) {
    let source;
    try {
      source = this.prepareSource({
        text: entry.content,
        segment: entry.segment,
        reason: entry.reason,
        locale: entry.locale,
        signal: entry.prepareController.signal,
      });
    } catch (error) {
      this.prepareFallback(entry, error);
      return;
    }

    if (source?.then) {
      Promise.resolve(source)
        .then((url) => this.activate(entry, url))
        .catch((error) => {
          if (!this.isCurrent(entry)) return;
          this.prepareFallback(entry, error);
        });
      return;
    }
    this.activate(entry, source);
  }

  activate(entry, url) {
    if (!this.isCurrent(entry) || entry.ended || entry.useFallback) return false;
    const source = String(url || "").trim();
    if (!source) return this.prepareFallback(entry, new Error("tts_source_unavailable"));

    entry.url = source;
    entry.prepareController = null;
    let audio;
    try {
      audio = this.createAudio(source, entry.segment, 0);
      if (!audio) throw new Error("tts_audio_unavailable");
      audio.preload = "auto";
    } catch (error) {
      return this.prepareFallback(entry, error);
    }

    entry.audio = audio;
    this.bind(entry);
    if (entry.segment === 0) {
      this.start(entry);
    } else {
      try {
        audio.load?.();
      } catch (error) {
        this.handleAudioError(entry, error);
      }
      if (!this.current && this.entries.get(0)?.ended) this.start(entry);
    }
    return true;
  }

  complete() {
    if (this.terminal) return false;
    this.completed = true;
    if (!this.entries.size) return this.finishSuccessfully();
    this.maybeFinish();
    return true;
  }

  stop() {
    return this.confirmStop();
  }

  /** Confirm cancellation and release every current/prefetched resource. */
  confirmStop() {
    this.generation += 1;
    this.activeGeneration = this.generation;
    for (const entry of this.entries.values()) this.release(entry);
    this.entries.clear();
    this.current = null;
    this.completed = false;
    this.terminal = true;
    this.setPlaying(false);
    return true;
  }

  dispose() {
    this.stop();
  }

  isCurrent(entry) {
    return entry.generation === this.activeGeneration && this.entries.get(entry.segment) === entry;
  }

  bind(entry) {
    const { audio } = entry;
    if (!audio) return;
    const handlers = {
      loadeddata: () => {
        if (!this.isCurrent(entry) || entry.firstChunk) return;
        entry.firstChunk = true;
        this.emit({ type: "first_audio_chunk", segment: entry.segment, elapsedMs: now() - entry.startedAt });
      },
      playing: () => {
        if (!this.isCurrent(entry)) return;
        this.current = entry;
        this.setPlaying(true);
        this.emit({ type: "playing", segment: entry.segment, elapsedMs: now() - entry.startedAt });
      },
      ended: () => this.end(entry),
      error: (event) => this.handleAudioError(entry, event || new Error("tts_audio_error")),
    };
    entry.handlers = handlers;
    Object.entries(handlers).forEach(([type, handler]) => audio.addEventListener?.(type, handler));
  }

  start(entry) {
    if (!this.isCurrent(entry) || entry.started || this.current) return false;
    if (entry.useFallback) return this.startFallback(entry);
    if (!entry.audio) return false;

    entry.started = true;
    this.current = entry;
    let result;
    try {
      result = entry.audio.play?.();
    } catch (error) {
      this.handleAudioError(entry, error);
      return false;
    }
    if (result?.catch) result.catch((error) => this.handleAudioError(entry, error));
    return true;
  }

  startFallback(entry) {
    if (!this.isCurrent(entry) || entry.started || this.current) return false;
    entry.started = true;
    this.current = entry;
    this.emit({ type: "fallback.start", segment: entry.segment, elapsedMs: now() - entry.startedAt });

    const onStart = () => {
      if (!this.isCurrent(entry) || this.current !== entry) return;
      this.setPlaying(true);
      this.emit({ type: "fallback.playing", segment: entry.segment, elapsedMs: now() - entry.startedAt });
    };
    const onEnd = () => {
      if (!this.isCurrent(entry)) return;
      this.end(entry);
    };
    const onError = () => {
      if (!this.isCurrent(entry)) return;
      this.emit({ type: "fallback.failed", segment: entry.segment, elapsedMs: now() - entry.startedAt });
      this.end(entry);
    };

    const cancel = callFallback(this.fallbackSpeak, entry.content, {
      onStart,
      onEnd,
      onError,
      locale: entry.locale || guessSpeechLocale(entry.content),
    });
    if (!cancel) {
      this.emit({ type: "fallback.unavailable", segment: entry.segment, elapsedMs: now() - entry.startedAt });
      this.end(entry);
      return false;
    }
    entry.fallbackCancel = typeof cancel === "function" ? cancel : null;
    return true;
  }

  end(entry) {
    if (!this.isCurrent(entry) || entry.ended) return;
    entry.ended = true;
    const wasCurrent = this.current === entry;
    if (wasCurrent) this.current = null;
    if (wasCurrent) this.setPlaying(false);
    entry.fallbackCancel = null;
    this.emit({ type: "segment.complete", segment: entry.segment, elapsedMs: now() - entry.startedAt });

    const next = this.entries.get(entry.segment + 1);
    if (next && !next.started) this.start(next);
    this.maybeFinish();
  }

  finishSuccessfully() {
    if (this.terminal) return false;
    const generation = this.activeGeneration;
    this.terminal = true;
    for (const entry of this.entries.values()) this.release(entry);
    this.entries.clear();
    this.current = null;
    this.setPlaying(false);
    callSafely(this.onTerminal, { generation, failed: false });
    return true;
  }

  maybeFinish() {
    if (this.terminal || !this.completed || this.current || !this.entries.size) return;
    const allEnded = [...this.entries.values()].every((entry) => entry.ended);
    if (!allEnded) return;
    this.finishSuccessfully();
  }

  handleAudioError(entry, reason) {
    if (!this.isCurrent(entry) || this.terminal || entry.ended || entry.useFallback) return;
    if (!entry.firstChunk && entry.retryCount < MAX_AUDIO_RETRIES) {
      this.retry(entry, reason);
      return;
    }
    this.prepareFallback(entry, reason);
  }

  retry(entry, reason) {
    if (!this.isCurrent(entry) || entry.retryTimer !== null || !entry.audio) return false;
    entry.retryCount += 1;
    const retry = entry.retryCount;
    const delay = RETRY_DELAYS_MS[Math.min(retry - 1, RETRY_DELAYS_MS.length - 1)] || 0;
    const wasCurrent = this.current === entry;
    if (wasCurrent) this.current = null;
    if (wasCurrent) this.setPlaying(false);
    entry.started = false;
    entry.firstChunk = false;
    this.emit({
      type: "request.retry",
      segment: entry.segment,
      retry,
      delayMs: delay,
      elapsedMs: now() - entry.startedAt,
      reason,
    });

    entry.retryTimer = this.scheduleRetry(() => {
      entry.retryTimer = null;
      if (!this.isCurrent(entry) || this.terminal || entry.ended || !entry.audio) return;
      try {
        entry.audio.src = withRetryMarker(entry.url, retry);
        entry.audio.preload = "auto";
        entry.audio.load?.();
      } catch (error) {
        this.handleAudioError(entry, error);
        return;
      }

      const previous = this.entries.get(entry.segment - 1);
      if (entry.segment === 0 || previous?.ended) this.start(entry);
    }, delay);
    return true;
  }

  prepareFallback(entry, reason) {
    if (!this.isCurrent(entry) || entry.ended) return false;
    entry.prepareController?.abort();
    entry.prepareController = null;
    if (entry.retryTimer !== null) {
      this.cancelRetry(entry.retryTimer);
      entry.retryTimer = null;
    }
    const wasCurrent = this.current === entry;
    if (wasCurrent) this.current = null;
    if (wasCurrent) this.setPlaying(false);
    entry.started = false;
    entry.useFallback = true;
    const audio = entry.audio;
    if (audio) {
      try {
        audio.pause?.();
        audio.removeAttribute?.("src");
        audio.src = "";
        audio.load?.();
      } catch {
        // The network media element is no longer required once fallback begins.
      }
    }
    this.emit({
      type: "request.degraded",
      segment: entry.segment,
      retries: entry.retryCount,
      elapsedMs: now() - entry.startedAt,
      reason,
    });

    const previous = this.entries.get(entry.segment - 1);
    if (entry.segment === 0 || previous?.ended) this.start(entry);
    return true;
  }

  fail(generation, reason) {
    if (generation !== this.activeGeneration || this.terminal) return;
    this.terminal = true;
    for (const entry of this.entries.values()) this.release(entry);
    this.entries.clear();
    this.current = null;
    this.setPlaying(false);
    callSafely(this.onTerminal, { generation, failed: true, reason });
  }

  release(entry) {
    entry.prepareController?.abort();
    entry.prepareController = null;
    if (entry.retryTimer !== null) {
      this.cancelRetry(entry.retryTimer);
      entry.retryTimer = null;
    }
    if (entry.fallbackCancel) {
      try {
        entry.fallbackCancel();
      } catch {
        // The local speech synthesizer may already have completed.
      }
      entry.fallbackCancel = null;
    }

    const { audio, handlers } = entry;
    if (!audio) return;
    if (handlers) {
      Object.entries(handlers).forEach(([type, handler]) => audio.removeEventListener?.(type, handler));
    }
    try {
      audio.pause?.();
    } catch {
      // A stale media element is already being torn down.
    }
    try {
      audio.removeAttribute?.("src");
      audio.src = "";
      audio.load?.();
    } catch {
      // Test doubles and partially initialized media elements may not expose all APIs.
    }
  }

  setPlaying(value) {
    const next = Boolean(value);
    if (this.playing === next) return;
    this.playing = next;
    callSafely(this.onPlayingChange, next);
  }

  emit(event) {
    callSafely(this.onEvent, { ...event, generation: this.activeGeneration });
  }
}

function callFallback(fallbackSpeak, text, callbacks) {
  try {
    return fallbackSpeak?.(text, callbacks) || null;
  } catch (error) {
    callbacks.onError?.(error);
    return null;
  }
}

export default TtsScheduler;