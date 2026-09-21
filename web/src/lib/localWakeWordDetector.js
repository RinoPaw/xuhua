import { VoiceMediaController } from "./voiceMedia.js";
import { StatefulPcmResampler } from "./pcmResampler.js";

const WAKE_WORD = "叙华";
const WAKE_KEYWORDS = "x ù h uá @叙华";
const TARGET_SAMPLE_RATE = 16000;
const SHERPA_WASM_BASE = "https://cdn.jsdelivr.net/npm/@siteed/sherpa-onnx.rn@1.3.1/wasm/";
const SHERPA_MODEL_BASE = "https://huggingface.co/openEuler/sherpa-kws/resolve/main/assets";
const SHERPA_MODEL_DIR = "/xuhua-kws";

let runtimePromise = null;

function loadScriptOnce(url) {
  const existing = Array.from(globalThis.document?.scripts || [])
    .find((script) => script.src === url);
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
    const finish = (value, error = null) => {
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
    this.active = false;
    this.triggered = false;
    this.onWake = null;
  }

  async initialize() {
    if (this.spotter && this.stream) return true;
    if (this.initializing) return this.initializing;
    this.initializing = (async () => {
      this.log.info?.("[叙华][wake] loading local KWS");
      const sherpa = await this.runtimeLoader();
      const loadedModel = await sherpa.KWS.loadModel({
        modelDir: SHERPA_MODEL_DIR,
        encoder: `${this.modelBase}/onnx/encoder.onnx`,
        decoder: `${this.modelBase}/onnx/decoder.onnx`,
        joiner: `${this.modelBase}/onnx/joiner.onnx`,
        tokens: `${this.modelBase}/tokens.txt`,
        debug: false,
      });
      this.spotter = sherpa.KWS.createKeywordSpotter(loadedModel, {
        keywords: WAKE_KEYWORDS,
        sampleRate: TARGET_SAMPLE_RATE,
        numThreads: 1,
        maxActivePaths: 4,
        numTrailingBlanks: 1,
        keywordsScore: 1.5,
        keywordsThreshold: 0.25,
        debug: false,
      });
      if (!this.spotter?.handle) throw new Error("wake_spotter_create_failed");
      this.stream = this.spotter.createStream();
      if (!this.stream?.handle) throw new Error("wake_stream_create_failed");
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
    this.onWake = onWake || null;
    if (this.active) return true;
    await this.initialize();
    this.triggered = false;
    this.resampler = null;
    this.inputRate = 0;
    await this.media.requestStream();
    await this.media.attachProcessor((samples, inputRate) => this.process(samples, inputRate));
    this.active = true;
    this.log.info?.("[叙华][wake] listening locally");
    return true;
  }

  stop() {
    const wasActive = this.active;
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
