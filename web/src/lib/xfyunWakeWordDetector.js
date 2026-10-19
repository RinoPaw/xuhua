import { StatefulPcmResampler } from "./pcmResampler.js";
import { SharedVoiceMedia } from "./sharedVoiceMedia.js";

const now = () => globalThis.performance?.now?.() ?? Date.now();
const WAIT_MS = 8000;

export class XfyunWakeWordDetector {
  constructor({ hub = new SharedVoiceMedia(), WebSocketImpl = globalThis.WebSocket, onFailure = () => {} } = {}) {
    this.remote = true;
    this.hub = hub;
    this.media = hub.createLease();
    this.WebSocketImpl = WebSocketImpl;
    this.onFailure = onFailure;
    this.onDiagnostic = () => {};
    this.mode = "off";
    this.socket = null;
    this.ring = [];
    this.total = 0;
    this.generation = 0;
    this.disposed = false;
  }

  process(samples, rate) {
    if (!["listening", "handoff"].includes(this.mode)) return;
    if (!this.resampler || this.rate !== rate) {
      this.rate = rate;
      this.resampler = new StatefulPcmResampler(rate, 16000);
    }
    const pcm = this.resampler.process(samples);
    if (!pcm.byteLength) return;
    const start = this.total;
    this.total += pcm.byteLength / 2;
    this.ring.push({ start, end: this.total, pcm, at: now() });
    while (this.ring.length && this.ring[0].end < this.total - 32000) this.ring.shift();
    if (this.mode === "listening" && this.socket?.readyState === 1) {
      if (this.socket.bufferedAmount > 64000) return this.fail(new Error("wake_network_slow"));
      // Worklet blocks may be larger than a protocol frame at lower input rates.
      for (let offset = 0; offset < pcm.byteLength; offset += 6400) this.socket.send(pcm.slice(offset, offset + 6400));
    }
    if (this.mode === "handoff" && now() - this.handoffAt > 2000) this.overflow = true;
  }

  handle(event) {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "ready") {
      this.streamId = message.stream_id;
      this.total = 0;
      this.ring = [];
      this.resampler = null;
      this.mode = "listening";
      this.resolveReady?.(true);
    } else if (message.type === "error") {
      this.fail(new Error(message.code || "wake_unavailable"));
    } else if (message.type === "wake" && this.mode === "listening" && message.stream_id === this.streamId) {
      if (!["叙华", "你好叙华"].includes(message.keyword)) return;
      this.mode = "handoff";
      this.handoffAt = now();
      this.overflow = false;
      this.endSample = Number(message.end_sample);
      const block = this.ring.find(item => item.start <= this.endSample && item.end >= this.endSample);
      const wordEndAt = block ? block.at - (block.end - this.endSample) / 16 : null;
      this.socket.send(JSON.stringify({ type: "pause" }));
      void Promise.resolve(this.onWake?.(message.keyword, { detectedAt: now(), wordEndAt, streamId: this.streamId }))
        .catch(error => this.fail(error));
    }
  }

  async start(onWake) {
    if (this.disposed) return false;
    this.onWake = onWake;
    const generation = this.generation;
    await this.media.requestStream();
    await this.media.attachProcessor((samples, rate) => this.process(samples, rate));
    if (generation !== this.generation) return false;
    this.mode = "preparing";
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.fail(new Error("wake_unavailable")), WAIT_MS);
      this.resolveReady = value => { clearTimeout(timer); this.resolveReady = this.rejectReady = null; resolve(value); };
      this.rejectReady = error => { clearTimeout(timer); this.resolveReady = this.rejectReady = null; reject(error); };
      if (this.socket?.readyState === 1) {
        this.socket.send(JSON.stringify({ type: "resume" }));
        return;
      }
      const endpoint = new URL("/api/wake", globalThis.location?.href || "http://localhost/");
      endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
      const socket = new this.WebSocketImpl(endpoint.href);
      this.socket = socket;
      socket.onmessage = event => { if (this.socket === socket) this.handle(event); };
      socket.onerror = () => { if (this.socket === socket) this.fail(new Error("wake_unavailable")); };
      socket.onclose = event => { if (this.socket === socket) this.fail(new Error(event.code === 1008 ? "wake_authorization_required" : "wake_unavailable")); };
      this.heartbeat = setInterval(() => {
        if (socket.readyState === 1) socket.send(JSON.stringify({ type: "ping" }));
      }, 15000);
    });
  }

  finishHandoff(consume) {
    if (this.overflow) throw new Error("wake_handoff_overflow");
    this.mode = "paused";
    // If a validated tail isn't retained, never replay the entire wake phrase.
    if (Number.isFinite(this.endSample) && this.endSample >= (this.ring[0]?.start ?? 0)) {
      for (const item of this.ring) {
        if (item.end <= this.endSample) continue;
        const pcm = new Int16Array(item.pcm, Math.max(0, this.endSample - item.start) * 2);
        consume(Float32Array.from(pcm, value => value / 32768), 16000);
      }
    }
    this.ring = [];
  }

  fail(error) {
    const pending = this.rejectReady;
    this.resolveReady = this.rejectReady = null;
    this.stop();
    if (pending) pending(error);
    else this.onFailure(error);
  }

  stop() {
    this.generation++;
    this.mode = "off";
    clearInterval(this.heartbeat);
    const socket = this.socket;
    this.socket = null;
    if (socket) { socket.onmessage = socket.onclose = socket.onerror = null; socket.close(); }
    this.ring = [];
    this.resampler = null;
    this.media.stop();
    this.resolveReady?.(false);
  }

  dispose() { this.disposed = true; this.stop(); this.hub.stop(); }
}
