import { VoiceMediaController } from "./voiceMedia.js";

/** Leases share one stream/worklet; releasing a lease cannot stop another owner. */
export class SharedVoiceMedia {
  constructor(media = new VoiceMediaController()) {
    this.media = media;
    this.owners = new Set();
    this.callbacks = new Map();
    this.pending = null;
    this.processor = null;
    this.generation = 0;
  }

  createLease() {
    const hub = this;
    const lease = {
      generation: 0,
      get stream() { return hub.owners.has(lease) ? hub.media.stream : null; },
      async requestStream() {
        hub.owners.add(lease);
        const request = ++lease.generation;
        const generation = hub.generation;
        if (!hub.pending) hub.pending = hub.media.requestStream();
        try {
          const stream = await hub.pending;
          if (generation !== hub.generation || request !== lease.generation || !hub.owners.has(lease)) throw new Error("voice_media_request_stale");
          return stream;
        } catch (error) {
          if (request === lease.generation) lease.stop();
          throw error;
        }
      },
      async attachProcessor(onSamples) {
        hub.callbacks.set(lease, onSamples);
        if (!hub.processor) hub.processor = hub.media.attachProcessor((samples, rate) => {
          for (const callback of hub.callbacks.values()) callback?.(samples, rate);
        });
        const context = await hub.processor;
        if (!hub.owners.has(lease)) throw new Error("voice_media_request_stale");
        if (context.state === "suspended") await context.resume();
        return context;
      },
      stop() {
        lease.generation++;
        hub.callbacks.delete(lease);
        hub.owners.delete(lease);
        if (!hub.owners.size) hub.stop();
      },
      release() { lease.stop(); return true; },
    };
    return lease;
  }

  stop() {
    this.generation++;
    this.callbacks.clear();
    this.owners.clear();
    this.pending = this.processor = null;
    this.media.stop();
  }
}
