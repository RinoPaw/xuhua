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
