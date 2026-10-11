import { VoiceMediaController } from "./voiceMedia.js";
import { StatefulPcmResampler } from "./pcmResampler.js";

const WAKE_WORD = "叙华";
const WAKE_KEYWORDS = "x ù h uá @叙华";
const TARGET_SAMPLE_RATE = 16000;
const SHERPA_WASM_BASE = "/wake/runtime/";
const SHERPA_MODEL_BASE = "/wake/model";
const SHERPA_MODEL_DIR = "/xuhua-kws";

let runtimePromise = null;

function loadScriptOnce(url) {
  const absoluteUrl = new URL(url, globalThis.location?.href || "http://localhost/").href;
  const existing = Array.from(globalThis.document?.scripts || [])
    .find((script) => script.src === absoluteUrl);
  if (existing?.dataset?.loaded === "true") return Promise.resolve();
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", () => reject(new Error(`wake_script_failed:${url}`)), { once: true });
    });
  }
  if (!globalThis.document?.head) return Promise.reject(new Error("wake_browser_required"));
  return new Promise((resolve, reject) => {
    const script = globalThis.document.createElement("script");
    script.src = url;
    script.async = false;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", () => reject(new Error(`wake_script_failed:${url}`)), { once: true });
    globalThis.document.head.appendChild(script);
  });
}

function sherpaKwsReady() {
  return Boolean(globalThis.Module?.FS && globalThis.SherpaOnnx?.KWS);
}

function waitForSherpaReady(timeoutMs = 180000) {
  if (sherpaKwsReady()) return Promise.resolve(globalThis.SherpaOnnx);
  return new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const previousReady = globalThis.onSherpaOnnxReady;
    let timer = null;
    let finished = false;
    const finish = (value, error = null) => {
      if (finished) return;
      finished = true;
      if (timer !== null) globalThis.clearTimeout.call(globalThis, timer);
      if (globalThis.onSherpaOnnxReady === onReady) globalThis.onSherpaOnnxReady = previousReady;
      if (error) reject(error);
      else resolve(value);
    };
    const poll = () => {
      if (sherpaKwsReady()) return finish(globalThis.SherpaOnnx);
      if (Date.now() - startedAt >= timeoutMs) {
        return finish(null, new Error("wake_runtime_timeout"));
      }
      timer = globalThis.setTimeout.call(globalThis, poll, 100);
    };
    const onReady = (loaded) => {
      previousReady?.(loaded);
      if (loaded && sherpaKwsReady()) finish(globalThis.SherpaOnnx);
    };
    globalThis.onSherpaOnnxReady = onReady;
    poll();
  });
}

export function loadLocalWakeRuntime() {
  if (sherpaKwsReady()) return Promise.resolve(globalThis.SherpaOnnx);
  if (runtimePromise) return runtimePromise;
  runtimePromise = (async () => {
    const base = SHERPA_WASM_BASE;
    globalThis.sherpaOnnxModulePaths = [
      `${base}sherpa-onnx-core.js`,
      `${base}sherpa-onnx-kws.js`,
    ];
    await loadScriptOnce(`${base}sherpa-onnx-wasm-combined.js`);
    const ready = waitForSherpaReady();
    await loadScriptOnce(`${base}sherpa-onnx-combined.js`);
    return ready;
  })().catch((error) => {
    runtimePromise = null;
    throw error;
  });
  return runtimePromise;
}

function pcm16ToFloat32(buffer) {
  const pcm = new Int16Array(buffer);
  const samples = new Float32Array(pcm.length);
  for (let index = 0; index < pcm.length; index += 1) {
    samples[index] = pcm[index] / 32768;
  }
  return samples;
}

export class LocalWakeWordDetector {
  constructor({
    runtimeLoader = loadLocalWakeRuntime,
    media = new VoiceMediaController(),
    createResampler = (inputRate) => new StatefulPcmResampler(inputRate, TARGET_SAMPLE_RATE),
    modelBase = SHERPA_MODEL_BASE,
    log = console,
  } = {}) {
    this.runtimeLoader = runtimeLoader;
    this.media = media;
    this.createResampler = createResampler;
    this.modelBase = modelBase.replace(/\/+$/u, "");
    this.log = log;
    this.spotter = null;
    this.stream = null;
    this.resampler = null;
    this.inputRate = 0;
    this.initializing = null;
    this.starting = null;
    this.startGeneration = 0;
    this.disposed = false;
    this.active = false;
    this.triggered = false;
    this.onWake = null;
  }

  async initialize() {
    if (this.disposed) return false;
    if (this.spotter && this.stream) return true;
    if (this.initializing) return this.initializing;
    this.initializing = (async () => {
      this.log.info?.("[叙华][wake] loading local KWS");
      const sherpa = await this.runtimeLoader();
      if (this.disposed) return false;
      const loadedModel = await sherpa.KWS.loadModel({
        modelDir: SHERPA_MODEL_DIR,
        encoder: `${this.modelBase}/encoder.onnx`,
        decoder: `${this.modelBase}/decoder.onnx`,
        joiner: `${this.modelBase}/joiner.onnx`,
        tokens: `${this.modelBase}/tokens.txt`,
        debug: false,
      });
      if (this.disposed) {
        loadedModel?.free?.();
        return false;
      }
      const spotter = sherpa.KWS.createKeywordSpotter(loadedModel, {
        keywords: WAKE_KEYWORDS,
        sampleRate: TARGET_SAMPLE_RATE,
        numThreads: 1,
        maxActivePaths: 4,
        numTrailingBlanks: 1,
        keywordsScore: 1.5,
        keywordsThreshold: 0.25,
        debug: false,
      });
      if (!spotter?.handle) {
        spotter?.free?.();
        throw new Error("wake_spotter_create_failed");
      }
      let stream;
      try {
        stream = spotter.createStream();
        if (!stream?.handle) throw new Error("wake_stream_create_failed");
        if (this.disposed) {
          stream.free?.();
          spotter.free?.();
          return false;
        }
      } catch (error) {
        stream?.free?.();
        spotter.free?.();
        throw error;
      }
      this.spotter = spotter;
      this.stream = stream;
      this.log.info?.("[叙华][wake] local KWS ready");
      return true;
    })().finally(() => {
      this.initializing = null;
    });
    return this.initializing;
  }

  process(samples, inputRate) {
    if (!this.active || this.triggered || !this.spotter || !this.stream) return false;
    const rate = Number(inputRate);
    if (!(rate > 0)) return false;
    if (!this.resampler || this.inputRate !== rate) {
      this.inputRate = rate;
      this.resampler = this.createResampler(rate);
    }
    const pcm = this.resampler.process(samples);
    if (!pcm.byteLength) return false;
    const waveform = pcm16ToFloat32(pcm);
    this.stream.acceptWaveform(TARGET_SAMPLE_RATE, waveform);
    while (this.spotter.isReady(this.stream)) {
      this.spotter.decode(this.stream);
      const result = this.spotter.getResult(this.stream);
      const keyword = String(result?.keyword || "").trim();
      if (!keyword) continue;
      this.spotter.reset(this.stream);
      if (!keyword.includes(WAKE_WORD)) continue;
      this.triggered = true;
      this.log.info?.(`[叙华][wake] detected: ${keyword}`);
      const callback = this.onWake;
      const pending = callback?.(keyword);
      pending?.catch?.((error) => this.log.error?.("[叙华][wake] wake handoff failed", error));
      return true;
    }
    return false;
  }

  async start(onWake) {
    if (this.disposed) return false;
    const requestedGeneration = this.startGeneration;
    this.onWake = onWake || null;
    if (this.active) return true;
    // Serialize starts so an earlier cancelled getUserMedia cannot attach
    // a second AudioWorklet or resurrect local capture after stop().
    if (this.starting) {
      try { await this.starting; } catch { /* retry on the next start */ }
      // stop()/dispose() during the wait must invalidate queued starts too.
      if (this.disposed || requestedGeneration !== this.startGeneration) return false;
      if (this.active) return true;
    }
    const generation = ++this.startGeneration;
    const attempt = (async () => {
      const initialized = await this.initialize();
      if (!initialized || this.disposed || generation !== this.startGeneration) return false;
      this.triggered = false;
      this.resampler = null;
      this.inputRate = 0;
      try {
        await this.media.requestStream();
        if (generation !== this.startGeneration) return false;
        await this.media.attachProcessor((samples, inputRate) => this.process(samples, inputRate));
        if (generation !== this.startGeneration) return false;
        this.active = true;
        this.log.info?.("[叙华][wake] listening locally");
        return true;
      } catch (error) {
        if (generation === this.startGeneration) this.media.stop();
        throw error;
      }
    })();
    this.starting = attempt;
    try {
      return await attempt;
    } finally {
      if (this.starting === attempt) this.starting = null;
    }
  }

  stop() {
    const wasActive = this.active;
    this.startGeneration += 1;
    this.active = false;
    this.triggered = false;
    this.onWake = null;
    this.resampler?.reset?.();
    this.resampler = null;
    this.inputRate = 0;
    this.media.stop();
    if (wasActive) this.log.info?.("[叙华][wake] stopped");
    return wasActive;
  }

  dispose() {
    this.disposed = true;
    this.stop();
    try { this.stream?.free?.(); } catch { /* noop */ }
    try { this.spotter?.free?.(); } catch { /* noop */ }
    this.stream = null;
    this.spotter = null;
  }
}

export {
  SHERPA_MODEL_BASE,
  SHERPA_WASM_BASE,
  TARGET_SAMPLE_RATE,
  WAKE_KEYWORDS,
  WAKE_WORD,
};

export default LocalWakeWordDetector;
