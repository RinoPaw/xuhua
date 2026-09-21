import assert from "node:assert/strict";
import test from "node:test";

import { VoiceMediaController } from "../src/lib/voiceMedia.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function makeStream() {
  const track = { stopped: false, stop() { this.stopped = true; } };
  const stream = {
    getTracks: () => [track],
  };
  return { track, stream };
}

function makeHarness() {
  const { track, stream } = makeStream();
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

  await media.stop();
  assert.equal(harness.processor.disconnected, true);
  assert.equal(harness.source.disconnected, true);
  assert.equal(harness.track.stopped, true);
  assert.equal(context.state, "closed");
});

test("late stale microphone requests cannot replace a newer stream", async () => {
  const requests = [];
  const mediaDevices = {
    getUserMedia() {
      const request = deferred();
      requests.push(request);
      return request.promise;
    },
  };
  const media = new VoiceMediaController({ mediaDevices });

  const firstPromise = media.requestStream();
  media.stop();
  const secondPromise = media.requestStream();

  const second = makeStream();
  requests[1].resolve(second.stream);
  assert.equal(await secondPromise, second.stream);
  assert.equal(media.stream, second.stream);

  const first = makeStream();
  requests[0].resolve(first.stream);
  await assert.rejects(firstPromise, /voice_media_request_stale/);
  assert.equal(first.track.stopped, true);
  assert.equal(second.track.stopped, false);
  assert.equal(media.stream, second.stream);
});

test("stale worklet attachment cannot bind to a replacement stream", async () => {
  const first = makeStream();
  const second = makeStream();
  const streams = [first.stream, second.stream];
  const moduleGate = deferred();
  let sourceCreations = 0;

  class SlowAudioContext {
    constructor() {
      this.sampleRate = 48000;
      this.state = "running";
      this.destination = {};
      this.audioWorklet = { addModule: () => moduleGate.promise };
    }
    createMediaStreamSource() {
      sourceCreations += 1;
      return { connect(next) { return next; }, disconnect() {} };
    }
    createGain() {
      return { gain: { value: 1 }, connect(next) { return next; } };
    }
    async close() { this.state = "closed"; }
  }

  class FakeWorkletNode {
    constructor() {
      this.port = { onmessage: null };
    }
    connect(next) { return next; }
    disconnect() {}
  }

  const media = new VoiceMediaController({
    mediaDevices: { async getUserMedia() { return streams.shift(); } },
    AudioContextImpl: SlowAudioContext,
    AudioWorkletNodeImpl: FakeWorkletNode,
  });

  await media.requestStream();
  const attachPromise = media.attachProcessor(() => {});
  media.stop();
  await media.requestStream();
  moduleGate.resolve();

  await assert.rejects(attachPromise, /voice_media_request_stale/);
  assert.equal(sourceCreations, 0);
  assert.equal(first.track.stopped, true);
  assert.equal(second.track.stopped, false);
  assert.equal(media.stream, second.stream);
});

test("releasing a stale stream cannot stop the current stream", async () => {
  const current = makeStream();
  const stale = makeStream();
  const media = new VoiceMediaController({
    mediaDevices: { async getUserMedia() { return current.stream; } },
  });

  await media.requestStream();
  assert.equal(media.release(stale.stream), false);
  assert.equal(stale.track.stopped, true);
  assert.equal(current.track.stopped, false);
  assert.equal(media.stream, current.stream);
});
