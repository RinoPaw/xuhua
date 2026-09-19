import assert from "node:assert/strict";
import test from "node:test";

import { VoiceMediaController } from "../src/lib/voiceMedia.js";

function makeHarness() {
  const track = { enabled: true, stopped: false, stop() { this.stopped = true; } };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  };
  const source = {
    disconnected: false,
    connect(next) { this.next = next; return next; },
    disconnect() { this.disconnected = true; },
  };
  const processor = {
    disconnected: false,
    port: { onmessage: null },
    connect(next) { this.next = next; return next; },
    disconnect() { this.disconnected = true; },
  };
  const silent = {
    gain: { value: 1 },
    connect(next) { this.next = next; return next; },
  };
  class FakeAudioContext {
    constructor(options) {
      this.options = options;
      this.sampleRate = 48000;
      this.state = "running";
      this.destination = {};
      this.audioWorklet = {
        added: [],
        addModule: async (url) => { this.audioWorklet.added.push(url); },
      };
    }
    createMediaStreamSource(value) {
      assert.equal(value, stream);
      return source;
    }
    createGain() { return silent; }
    async close() { this.state = "closed"; }
  }
  class FakeWorkletNode {
    constructor(context, name) {
      assert.equal(context.sampleRate, 48000);
      assert.equal(name, "xuhua-pcm-capture");
      return processor;
    }
  }
  const mediaDevices = {
    request: null,
    async getUserMedia(value) {
      this.request = value;
      return stream;
    },
  };
  return { track, stream, source, processor, silent, FakeAudioContext, FakeWorkletNode, mediaDevices };
}

test("voice media controller requests the expected microphone constraints", async () => {
  const harness = makeHarness();
  const media = new VoiceMediaController({
    mediaDevices: harness.mediaDevices,
    AudioContextImpl: harness.FakeAudioContext,
    AudioWorkletNodeImpl: harness.FakeWorkletNode,
  });
  assert.equal(await media.requestStream(), harness.stream);
  assert.deepEqual(harness.mediaDevices.request, {
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
});

test("voice media controller wires worklet samples and releases resources", async () => {
  const harness = makeHarness();
  const media = new VoiceMediaController({
    mediaDevices: harness.mediaDevices,
    AudioContextImpl: harness.FakeAudioContext,
    AudioWorkletNodeImpl: harness.FakeWorkletNode,
  });
  await media.requestStream();
  const captured = [];
  const context = await media.attachProcessor((samples, rate) => captured.push([samples, rate]));
  assert.deepEqual(context.audioWorklet.added, ["/audio-capture-worklet.js"]);
  assert.equal(harness.silent.gain.value, 0);
  harness.processor.port.onmessage({ data: "pcm" });
  assert.deepEqual(captured, [["pcm", 48000]]);

  media.setMuted(true);
  assert.equal(harness.track.enabled, false);
  media.setMuted(false);
  assert.equal(harness.track.enabled, true);

  await media.stop();
  assert.equal(harness.processor.disconnected, true);
  assert.equal(harness.source.disconnected, true);
  assert.equal(harness.track.stopped, true);
  assert.equal(context.state, "closed");
});
