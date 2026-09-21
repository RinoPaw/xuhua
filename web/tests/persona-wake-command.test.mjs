import assert from "node:assert/strict";
import test from "node:test";

import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";

function makeSession() {
  const sent = [];
  const calls = [];
  const connection = {
    connected: true,
    sendJson(payload) {
      sent.push(payload);
      return true;
    },
  };
  const gate = {
    sleeping: false,
    setOnSleep(callback) { this.onSleep = callback; },
    wake(keyword) { calls.push(["gate.wake", keyword]); },
    responseSettled() {},
    noteUserActivity() {},
    allowAssistantResponse() { return true; },
    reset() {},
    dispose() {},
  };
  const wakeDetector = {
    active: false,
    stop() { calls.push(["wake.stop"]); },
    dispose() {},
  };
  const input = {
    state: { utteranceActive: false, lastVoiceAt: 0 },
    get utteranceActive() { return this.state.utteranceActive; },
    supersedeUtterance() { calls.push(["input.supersede"]); },
    clearBargeInCandidate() { return true; },
    unblock() {},
  };
  const output = {
    pipelineActive: false,
    playing: false,
    stop() { calls.push(["output.stop"]); return true; },
    prewarm() { return Promise.resolve(""); },
    dispose() {},
  };
  const transcript = {
    clear(reset) { calls.push(["transcript.clear", reset]); },
  };
  const latency = {
    clear() { calls.push(["latency.clear"]); },
  };
  const session = new PersonaBrowserVoiceSession({
    gate,
    wakeDetector,
    connection,
    input,
    transcript,
    latency,
    turns: { ignoreActive() {}, ignore() {}, reset() {} },
    createOutput: () => output,
    getMachine: () => ({}),
    dispatchVoice(action) { calls.push(["dispatch", action.type]); },
    dispatchMany(actions) { calls.push(["dispatchMany", actions.map((action) => action.type)]); },
    getRecognitionContext: () => ({ localeHint: "zh-CN" }),
    getCallbacks: () => ({ onBargeIn() {} }),
    onErrorState() {},
    onSpectrum() {},
    onMicrophoneEnabledChange() {},
    log: { info() {}, error() {} },
  });
  session.microphoneEnabled = true;
  return { session, sent, calls };
}

test("local wake uses the dedicated wake control command", async () => {
  const { session, sent, calls } = makeSession();

  assert.equal(await session.handleLocalWake("叙华"), true);
  assert.deepEqual(sent, [{ type: "wake" }]);
  assert.equal(sent.some((payload) => payload.type === "text"), false);
  assert.equal(calls.some(([name]) => name === "input.supersede"), true);
  assert.equal(calls.some(([name]) => name === "latency.clear"), true);
});
