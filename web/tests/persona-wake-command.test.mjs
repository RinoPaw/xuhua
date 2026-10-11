import assert from "node:assert/strict";
import test from "node:test";

import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";
import { PersonaVoiceGate } from "../src/lib/personaVoiceGate.js";
import { VoiceInputController } from "../src/lib/voiceInputController.js";
import { VoiceTurnTracker } from "../src/lib/voiceProtocol.js";
import { createVoiceMachineState, reduceVoiceMachine } from "../src/hooks/voiceState.js";

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
    async start(_path, handlers) {
      this.starting = true;
      this.connected = true;
      this.handlers = handlers;
      calls.push("remote.start");
      handlers.onOpen();
      this.starting = false;
      return true;
    },
    serverClose(code = 1006) {
      this.connected = false;
      this.handlers?.onClose({ code });
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
      resetOnset() {},
      blockFor() {},
      clearBargeInCandidate() {},
      supersedeUtterance() {},
      finishActiveUtterance() { return true; },
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
  session.turns = { setActive() {} };
  session.markThinking = () => {};
  session.gate = { wake(trigger) { wakes.push(trigger); } };

  assert.equal(session.sendText("皮影戏是什么？"), true);
  assert.equal(sent[0].type, "text");
  assert.equal(sent[0].text, "皮影戏是什么？");
  assert.match(sent[0].turn_id, /^[0-9a-f]{32}$/u);
  assert.deepEqual(wakes, ["文字提问"]);

  session.connection.connected = false;
  assert.equal(session.sendText("再次提问"), false);
  assert.deepEqual(wakes, ["文字提问"]);
});


test("concurrent wake arming shares the same local microphone request", async () => {
  const { session, detector, connection } = makeSession();
  let resolveStart;
  let starts = 0;
  detector.start = (callback) => {
    starts += 1;
    detector.callback = callback;
    return new Promise((resolve) => {
      resolveStart = () => { detector.active = true; resolve(true); };
    });
  };

  const first = session.armWake();
  const second = session.armWake();
  assert.equal(starts, 1);
  resolveStart();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(detector.active, true);
  assert.equal(connection.connected, false);
  session.destroy();
});

test("stale wake startup cannot stop a newer listening generation", async () => {
  const { session, detector } = makeSession();
  let finishFirst;
  let starts = 0;
  detector.start = () => {
    starts += 1;
    if (starts === 1) return new Promise((resolve) => { finishFirst = resolve; });
    detector.active = true;
    return Promise.resolve(true);
  };

  const oldStart = session.armWake();
  session.stop();
  // Allow the earlier generation to finish before a new arming request.
  const replacement = session.armWake();
  finishFirst(true);
  assert.equal(await oldStart, false);
  assert.equal(await replacement, true);
  assert.equal(detector.active, true);
  session.destroy();
});

function makeLifecycleHarness() {
  const scheduled = new Map();
  const activeTimers = new Set();
  let nextTimer = 0;
  const gate = new PersonaVoiceGate({
    log: { info() {} },
    setTimeoutFn(callback, delay) {
      assert.equal(delay, 7000);
      const id = ++nextTimer;
      scheduled.set(id, callback);
      activeTimers.add(id);
      return id;
    },
    clearTimeoutFn(id) { activeTimers.delete(id); },
  });
  const harness = makeSession({ gate });
  const { session } = harness;
  let machine = createVoiceMachineState();
  const transcriptEvents = [];
  const answerEvents = [];
  session.getMachine = () => machine;
  session.dispatchVoice = (action) => { machine = reduceVoiceMachine(machine, action); };
  session.dispatchMany = (actions) => {
    for (const action of actions) machine = reduceVoiceMachine(machine, action);
  };
  session.input = new VoiceInputController();
  session.latency = {
    clear() {}, markTranscript() {}, markFirstDelta() {}, markSpeechEnd() {}, noteTurn() {},
  };
  session.turns = new VoiceTurnTracker();
  session.transcript = {
    clear() {},
    publishPartial(event) { transcriptEvents.push(["partial", event.text]); return true; },
    publishTranscript(event, text) { transcriptEvents.push(["final", text]); return true; },
    reject() { return true; },
  };
  const output = {
    pipelineActive: false,
    playing: false,
    prewarm() {},
    stop() { this.pipelineActive = false; this.playing = false; },
    dispose() {},
    begin() { this.pipelineActive = true; },
    append(text) { answerEvents.push(["delta", text]); return true; },
    finish(text) { answerEvents.push(["done", text]); return true; },
    settle() { this.pipelineActive = false; session.handleOutputTerminal({ failed: false }); },
  };
  session.output = output;
  return {
    ...harness,
    output,
    transcriptEvents,
    answerEvents,
    activeTimers,
    expireTimer() {
      const id = [...activeTimers][0];
      assert.ok(id, "expected a scheduled sleep countdown");
      activeTimers.delete(id);
      scheduled.get(id)();
    },
  };
}

test("two complete wake-ASR-answer-TTS-sleep cycles reuse only local capture while sleeping", async () => {
  const h = makeLifecycleHarness();
  const { session, detector, connection, sent, transcriptEvents, answerEvents } = h;
  assert.equal(await session.armWake(), true);
  assert.equal(connection.connected, false);

  for (let cycle = 1; cycle <= 2; cycle += 1) {
    assert.equal(await detector.wake(), true);
    assert.equal(connection.connected, true);
    assert.equal(detector.active, false);
    assert.equal(sent.at(-1).type, "wake");

    assert.equal(session.routeServerEvent({
      type: "user.transcript", utterance_id: cycle,
      revision: 1, text: "介绍汴绣", raw_text: "介绍汴绣", locale: "zh-CN",
    }), true);
    assert.equal(session.routeServerEvent({
      type: "status", status: "thinking", turn_id: `turn-${cycle}`,
    }), true);
    assert.equal(session.routeServerEvent({
      type: "assistant.delta", turn_id: `turn-${cycle}`,
      session_id: "s1", locale: "zh-CN", text: "汴绣是",
    }), true);
    assert.equal(session.routeServerEvent({
      type: "assistant.done", turn_id: `turn-${cycle}`,
      session_id: "s1", locale: "zh-CN", text: "汴绣是传统美术",
    }), true);
    h.output.settle();
    assert.equal(h.activeTimers.size, 1);
    h.expireTimer();
    for (let tick = 0; tick < 20 && !detector.active; tick += 1) {
      await Promise.resolve();
    }
    assert.equal(connection.connected, false);
    assert.equal(detector.active, true);
    assert.equal(session.gate.sleeping, true);
    assert.equal(h.activeTimers.size, 0);
  }

  assert.deepEqual(transcriptEvents, [["final", "介绍汴绣"], ["final", "介绍汴绣"]]);
  assert.deepEqual(answerEvents, [
    ["delta", "汴绣是"], ["done", "汴绣是传统美术"],
    ["delta", "汴绣是"], ["done", "汴绣是传统美术"],
  ]);
  assert.equal(sent.filter((packet) => packet.type === "wake").length, 2);
  session.destroy();
});

test("activity during grace period cancels pending sleep until response settles again", async () => {
  const h = makeLifecycleHarness();
  const { session, detector, connection } = h;
  await session.armWake();
  await detector.wake();

  session.gate.responseSettled();
  assert.equal(h.activeTimers.size, 1);
  assert.equal(session.gate.noteUserActivity(), true);
  assert.equal(h.activeTimers.size, 0);
  assert.equal(connection.connected, true);
  assert.equal(detector.active, false);

  session.gate.responseSettled();
  h.expireTimer();
  for (let tick = 0; tick < 20 && !detector.active; tick += 1) {
    await Promise.resolve();
  }
  assert.equal(detector.active, true);
  assert.equal(connection.connected, false);
  session.destroy();
});



test("unexpected remote disconnect restores local wake without reconnect loops", async () => {
  const { session, detector, connection, calls, sent } = makeSession();
  await session.armWake();
  await detector.wake();
  assert.equal(connection.connected, true);
  connection.serverClose(1006);
  for (let i = 0; i < 10 && !detector.active; i += 1) await Promise.resolve();

  assert.equal(connection.connected, false);
  assert.equal(detector.active, true);
  assert.equal(session.gate.sleeping, true);
  assert.equal(calls.filter((call) => call === "remote.start").length, 1);
  assert.equal(await detector.wake(), true);
  assert.equal(connection.connected, true);
  assert.equal(sent.filter((packet) => packet.type === "wake").length, 2);
  session.destroy();
});

test("failed socket send restores local wake while reporting the transport failure", async () => {
  const { session, detector, connection, sent } = makeSession();
  await session.start();
  const originalSend = connection.sendJson.bind(connection);
  connection.sendJson = () => false;

  assert.equal(session.syncRecognitionContext(), false);
  for (let i = 0; i < 10 && !detector.active; i += 1) await Promise.resolve();
  assert.equal(detector.active, true);
  assert.equal(connection.connected, false);
  connection.sendJson = originalSend;
  assert.equal(await detector.wake(), true);
  assert.equal(connection.connected, true);
  assert.equal(sent.at(-1).type, "wake");
  session.destroy();
});

test("manual microphone pause prevents wake rearming on a later remote close", async () => {
  const { session, detector, connection } = makeSession();
  await session.start();
  assert.equal(session.pauseMicrophone(), true);
  connection.serverClose(1006);
  await Promise.resolve();
  assert.equal(detector.active, false);
  assert.equal(session.autoWakeEnabled, false);
  session.destroy();
});

test("manual stop ignores an obsolete remote close callback", async () => {
  const { session, detector, connection } = makeSession();
  await session.start();
  const stale = connection.handlers.onClose;
  session.stop();
  stale({ code: 1006 });
  await Promise.resolve();
  assert.equal(detector.active, false);
  session.destroy();
});


test("failed answer without TTS still enters a grace period and sleeps", async () => {
  const h = makeLifecycleHarness();
  const { session, detector, connection } = h;
  await session.armWake();
  await detector.wake();

  assert.equal(session.routeServerEvent({
    type: "error", code: "llm_unavailable", message: "服务不可用",
  }), true);
  assert.equal(h.activeTimers.size, 1);
  h.expireTimer();
  for (let i = 0; i < 15 && !detector.active; i += 1) await Promise.resolve();
  assert.equal(connection.connected, false);
  assert.equal(detector.active, true);
  session.destroy();
});

test("rejected utterance without an answer returns to local wake", async () => {
  const h = makeLifecycleHarness();
  const { session, detector, connection } = h;
  await session.armWake();
  await detector.wake();
  assert.equal(session.routeServerEvent({
    type: "utterance.rejected", utterance_id: 1,
  }), true);
  assert.equal(h.activeTimers.size, 1);
  h.expireTimer();
  for (let i = 0; i < 15 && !detector.active; i += 1) await Promise.resolve();
  assert.equal(connection.connected, false);
  assert.equal(detector.active, true);
  session.destroy();
});

test("delayed TTS completion does not sleep during a new utterance", async () => {
  const h = makeLifecycleHarness();
  const { session, detector, connection } = h;
  await session.armWake();
  await detector.wake();
  session.input.state.utteranceActive = true;
  session.dispatchVoice({ type: "input.speaking" });

  h.output.settle();
  assert.equal(h.activeTimers.size, 0);
  assert.equal(connection.connected, true);
  assert.equal(detector.active, false);
  session.destroy();
});

test("rejected stale ASR partial cannot cancel the idle grace countdown", async () => {
  const h = makeLifecycleHarness();
  const { session, detector } = h;
  await session.armWake();
  await detector.wake();
  session.gate.responseSettled();
  assert.equal(h.activeTimers.size, 1);
  session.input.state.minimumUtteranceId = 5;

  assert.equal(session.routeServerEvent({
    type: "user.partial", utterance_id: 1, text: "旧片段",
  }), false);
  assert.equal(h.activeTimers.size, 1);
  session.destroy();
});
