const DEFAULT_AUDIO_CONSTRAINTS = Object.freeze({
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
});

export class VoiceMediaController {
  constructor({
    mediaDevices = globalThis.navigator?.mediaDevices,
    AudioContextImpl = globalThis.AudioContext,
    AudioWorkletNodeImpl = globalThis.AudioWorkletNode,
    workletUrl = "/audio-capture-worklet.js",
    processorName = "xuhua-pcm-capture",
  } = {}) {
    this.mediaDevices = mediaDevices;
    this.AudioContextImpl = AudioContextImpl;
    this.AudioWorkletNodeImpl = AudioWorkletNodeImpl;
    this.workletUrl = workletUrl;
    this.processorName = processorName;
    this.stream = null;
    this.context = null;
    this.source = null;
    this.processor = null;
    this.muted = false;
  }

  async requestStream() {
    if (!this.mediaDevices?.getUserMedia) throw new Error("voice_media_unavailable");
    const stream = await this.mediaDevices.getUserMedia({
      audio: { ...DEFAULT_AUDIO_CONSTRAINTS },
    });
    this.stream = stream;
    this.applyMuteState();
    return stream;
  }

  async attachProcessor(onSamples) {
    if (!this.stream) throw new Error("voice_media_stream_missing");
    if (typeof this.AudioContextImpl !== "function" || typeof this.AudioWorkletNodeImpl !== "function") {
      throw new Error("voice_audio_worklet_unavailable");
    }

    const context = new this.AudioContextImpl({ latencyHint: "interactive" });
    this.context = context;
    await context.audioWorklet.addModule(this.workletUrl);

    const source = context.createMediaStreamSource(this.stream);
    const processor = new this.AudioWorkletNodeImpl(context, this.processorName);
    const silent = context.createGain();
    silent.gain.value = 0;
    processor.port.onmessage = (event) => onSamples?.(event.data, context.sampleRate);
    source.connect(processor).connect(silent).connect(context.destination);
    this.source = source;
    this.processor = processor;
    return context;
  }

  applyMuteState() {
    this.stream?.getAudioTracks?.().forEach((track) => {
      track.enabled = !this.muted;
    });
  }

  setMuted(muted) {
    this.muted = Boolean(muted);
    this.applyMuteState();
    return this.muted;
  }

  stop() {
    this.processor?.disconnect?.();
    this.source?.disconnect?.();
    this.processor = null;
    this.source = null;

    const context = this.context;
    this.context = null;
    let closing = null;
    if (context && context.state !== "closed") {
      try { closing = context.close(); } catch { /* noop */ }
    }

    this.stream?.getTracks?.().forEach((track) => track.stop?.());
    this.stream = null;
    if (closing?.catch) void closing.catch(() => {});
  }
}

export { DEFAULT_AUDIO_CONSTRAINTS };
