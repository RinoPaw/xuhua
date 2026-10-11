import assert from "node:assert/strict";
import test from "node:test";

import { LocalWakeWordDetector } from "../src/lib/localWakeWordDetector.js";

test("local wake detector triggers once for 叙华", async () => {
  const calls = [];
  const stream = {
    handle: 1,
    acceptWaveform(sampleRate, samples) {
      calls.push(["waveform", sampleRate, samples.length]);
    },
    free() {},
  };
  let ready = true;
  const spotter = {
    handle: 1,
    createStream: () => stream,
    isReady: () => ready,
    decode() { calls.push(["decode"]); },
    getResult() {
      ready = false;
      return { keyword: "叙华" };
    },
    reset() { calls.push(["reset"]); },
    free() {},
  };
  const runtimeLoader = async () => ({
    KWS: {
      async loadModel() {
        return { modelDir: "/xuhua-kws", paths: {} };
      },
      createKeywordSpotter() {
        return spotter;
      },
    },
  });
  let onSamples = null;
  const media = {
    async requestStream() { return {}; },
    async attachProcessor(callback) { onSamples = callback; },
    stop() { calls.push(["media.stop"]); },
  };
  const detector = new LocalWakeWordDetector({
    runtimeLoader,
    media,
    createResampler: () => ({
      process() { return new Int16Array([0, 1000, -1000]).buffer; },
      reset() {},
    }),
    log: { info() {}, error() {} },
  });

  const detected = [];
  await detector.start((keyword) => detected.push(keyword));
  onSamples(new Float32Array([0, 0.1, -0.1]), 48000);
  onSamples(new Float32Array([0, 0.1, -0.1]), 48000);

  assert.deepEqual(detected, ["叙华"]);
  assert.equal(calls.filter((entry) => entry[0] === "decode").length, 1);
  detector.stop();
  assert.equal(calls.some((entry) => entry[0] === "media.stop"), true);
});


// Stopping while the worklet is being attached must not resurrect capture.
test("cancelled local wake startup releases the microphone", async () => {
  let completeProcessor;
  const calls = [];
  const media = {
    async requestStream() { calls.push("request"); },
    async attachProcessor() {
      await new Promise((resolve) => { completeProcessor = resolve; });
      calls.push("attach");
    },
    stop() { calls.push("stop"); },
  };
  const detector = new LocalWakeWordDetector({
    runtimeLoader: async () => ({
      KWS: {
        async loadModel() { return {}; },
        createKeywordSpotter() {
          return { handle: 1, createStream: () => ({ handle: 1 }), free() {} };
        },
      },
    }),
    media,
    log: { info() {} },
  });
  const pending = detector.start(() => {});
  for (let i = 0; i < 10 && !completeProcessor; i += 1) await Promise.resolve();
  assert.equal(typeof completeProcessor, "function");
  detector.stop();
  completeProcessor();
  assert.equal(await pending, false);
  assert.equal(detector.active, false);
  assert.equal(calls.at(-1), "attach");
  detector.dispose();
});



test("a queued local wake start cannot revive capture after stop", async () => {
  let finishProcessor;
  let mediaRequests = 0;
  const media = {
    async requestStream() { mediaRequests += 1; },
    async attachProcessor() {
      await new Promise((resolve) => { finishProcessor = resolve; });
    },
    stop() {},
  };
  const detector = new LocalWakeWordDetector({
    runtimeLoader: async () => ({
      KWS: {
        async loadModel() { return {}; },
        createKeywordSpotter() {
          return { handle: 1, createStream: () => ({ handle: 1 }), free() {} };
        },
      },
    }),
    media,
    log: { info() {} },
  });
  const first = detector.start(() => {});
  for (let i = 0; i < 12 && !finishProcessor; i += 1) await Promise.resolve();
  assert.equal(typeof finishProcessor, "function");
  const queued = detector.start(() => {});
  detector.stop();
  finishProcessor();

  assert.deepEqual(await Promise.all([first, queued]), [false, false]);
  assert.equal(mediaRequests, 1);
  assert.equal(detector.active, false);
  detector.dispose();
});


test("disposing during a slow model load cannot allocate a late WASM spotter", async () => {
  let finishModel;
  let spottersCreated = 0;
  let mediaRequests = 0;
  let modelFreed = 0;
  const detector = new LocalWakeWordDetector({
    runtimeLoader: async () => ({
      KWS: {
        loadModel() {
          return new Promise((resolve) => { finishModel = resolve; });
        },
        createKeywordSpotter() {
          spottersCreated += 1;
          return { handle: 1, createStream: () => ({ handle: 1 }), free() {} };
        },
      },
    }),
    media: {
      async requestStream() { mediaRequests += 1; },
      async attachProcessor() {},
      stop() {},
    },
    log: { info() {} },
  });
  const pending = detector.start(() => {});
  for (let i = 0; i < 12 && !finishModel; i += 1) await Promise.resolve();
  assert.equal(typeof finishModel, "function");

  detector.dispose();
  finishModel({ free() { modelFreed += 1; } });
  assert.equal(await pending, false);
  assert.equal(spottersCreated, 0);
  assert.equal(mediaRequests, 0);
  assert.equal(modelFreed, 1);
  assert.equal(await detector.start(() => {}), false);
});
