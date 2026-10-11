import assert from "node:assert/strict";
import test from "node:test";

import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";
import { PersonaVoiceGate } from "../src/lib/personaVoiceGate.js";

function makeSession({ gate = new PersonaVoiceGate({ log: { info() {} } }) } = {}) {
  const sent = [];
  const calls = [];
  const detector = {
    active: false,
    async start(onWake) {
      this.callback = onWake;
      this.active = true;
      calls.push("local.start");
      return true;
    },
    stop() {
      this.active = false;
      calls.push("local.stop");
    },
    dispose() {
      this.stop();
      calls.push("local.dispose");
    },
    wake() { return this.callback?.("叙华"); },
  };
  const connection = {
    connected: false,
    starting: false,
    async start(_path, { onOpen }) {
      this.starting = true;
      this.connected = true;
      calls.push("remote.start");
      onOpen();
      this.starting = false;
      return true;
    },
    stop() {
      this.connected = false;
      calls.push("remote.stop");
    },
    sendJson(payload) {
      sent.push(payload);
      return true;
    },
    pauseInput() { calls.push("remote.pause"); return true; },
    async resumeInput() { calls.push("remote.resume"); return true; },
  };
  const session = new PersonaBrowserVoiceSession({
    gate,
    wakeDetector: detector,
    connection,
    input: {
      reset() {},
      clearBargeInCandidate() {},
      supersedeUtterance() {},
      state: { utteranceActive: false },
    },
    turns: { ignoreActive() {}, reset() {} },
    transcript: { clear() {} },
    latency: { clear() {} },
    createOutput: () => ({
      prewarm() {},
      pipelineActive: false,
      stop() {},
      dispose() {},
    }),
    getMachine: () => ({}),
    dispatchVoice() {},
    dispatchMany() {},
    getRecognitionContext: () => ({ localeHint: "zh-CN" }),
    onErrorState() {},
    onSpectrum() {},
    onMicrophoneEnabledChange() {},
    log: { info() {} },
  });
  return { session, connection, detector, calls, sent, gate };
}

test("persona starts with local wake only, no websocket or remote ASR", async () => {
  const { session, detector, connection, calls, sent } = makeSession();

  assert.equal(await session.armWake(), true);
  assert.equal(detector.active, true);
  assert.equal(connection.connected, false);
  assert.equal(calls.includes("remote.start"), false);
  assert.deepEqual(sent, []);
  session.destroy();
});

test("local wake hands off microphone and starts remote voice without LLM turn", async () => {
  const { session, detector, connection, calls, sent, gate } = makeSession();
  await session.armWake();

  assert.equal(await detector.wake(), true);
  assert.equal(gate.sleeping, false);
  assert.equal(detector.active, false);
  assert.equal(connection.connected, true);
  assert.deepEqual(sent.map((packet) => packet.type), ["context", "wake"]);
  assert.equal(calls.indexOf("local.stop") < calls.indexOf("remote.start"), true);
  session.destroy();
});

test("persona returns to local wake when grace period expires", async () => {
  let sleepNow;
  const gate = new PersonaVoiceGate({
    log: { info() {} },
    setTimeoutFn(callback) { sleepNow = callback; return 1; },
    clearTimeoutFn() {},
  });
  const { session, detector, connection, calls } = makeSession({ gate });
  await session.armWake();
  await detector.wake();

  gate.responseSettled();
  sleepNow();
  // onSleep is async; observe its remote->local handoff.
  for (let i = 0; i < 10 && !detector.active; i += 1) await Promise.resolve();

  assert.equal(connection.connected, false);
  assert.equal(detector.active, true);
  assert.equal(gate.sleeping, true);
  assert.equal(calls.filter((call) => call === "remote.stop").length, 1);
  session.destroy();
});

test("stale local wake initialization cannot open a socket after manual stop", async () => {
  const { session, connection, detector, sent } = makeSession();
  let resolveStart;
  detector.start = (callback) => {
    detector.callback = callback;
    return new Promise((resolve) => { resolveStart = resolve; });
  };

  const pending = session.armWake();
  session.stop();
  resolveStart(true);
  assert.equal(await pending, false);
  assert.equal(connection.connected, false);
  assert.deepEqual(sent, []);
  session.destroy();
});

test("explicit microphone pause prevents automatically reopening local wake", async () => {
  const { session, detector, gate, connection } = makeSession();
  assert.equal(await session.start(), true);
  assert.equal(session.pauseMicrophone(), true);
  assert.equal(connection.connected, true);
  assert.equal(session.autoWakeEnabled, false);

  gate.responseSettled();
  assert.equal(await session.enterSleep(), false);
  assert.equal(detector.active, false);
  session.destroy();
});

test("typed persona questions wake the gate after a successful send", () => {
  const sent = [];
  const wakes = [];
  const session = Object.create(PersonaBrowserVoiceSession.prototype);
  session.connection = { connected: true };
  session.send = (payload) => { sent.push(payload); return true; };
  session.latency = { clear() {} };
  session.transcript = { clear() {} };
  session.input = { supersedeUtterance() {} };
  session.stopSpeech = () => true;
  session.markThinking = () => {};
  session.gate = { wake(trigger) { wakes.push(trigger); } };

  assert.equal(session.sendText("皮影戏是什么？"), true);
  assert.deepEqual(sent, [{ type: "text", text: "皮影戏是什么？" }]);
  assert.deepEqual(wakes, ["文字提问"]);

  session.connection.connected = false;
  assert.equal(session.sendText("再次提问"), false);
  assert.deepEqual(wakes, ["文字提问"]);
});
