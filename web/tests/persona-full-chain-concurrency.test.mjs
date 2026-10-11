import assert from "node:assert/strict";
import test from "node:test";

import { createVoiceMachineState, deriveVoiceStatus, reduceVoiceMachine } from "../src/hooks/voiceState.js";
import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";
import { PersonaVoiceGate } from "../src/lib/personaVoiceGate.js";
import { VoiceOutputController } from "../src/lib/voiceOutput.js";
import { TtsScheduler } from "../src/lib/ttsScheduler.js";

class FakeAudio extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.src = url;
    this.playCalls = 0;
    this.pauseCalls = 0;
  }
  play() { this.playCalls += 1; return Promise.resolve(); }
  pause() { this.pauseCalls += 1; }
  load() {}
  removeAttribute() {}
  emit(type) { this.dispatchEvent(new Event(type)); }
}

function makeFullChain() {
  const timers = new Map();
  let nextTimer = 0;
  const emitted = [];
  const audios = [];
  const activity = [];
  const errors = [];
  const sent = [];
  let machine = createVoiceMachineState();
  const gate = new PersonaVoiceGate({
    log: { info() {} },
    setTimeoutFn(callback) {
      const id = ++nextTimer;
      timers.set(id, callback);
      return id;
    },
    clearTimeoutFn(id) { timers.delete(id); },
  });
  const wakeDetector = {
    active: false,
    starts: 0,
    stops: 0,
    callback: null,
    async start(callback) {
      this.callback = callback;
      this.starts += 1;
      this.active = true;
      activity.push("wake.start");
      return true;
    },
    stop() {
      if (this.active) activity.push("wake.stop");
      this.active = false;
      this.stops += 1;
    },
    dispose() { this.stop(); },
    trigger() { return this.callback?.("叙华"); },
  };
  const connection = {
    connected: false,
    starting: false,
    inputActive: false,
    handlers: null,
    startCount: 0,
    stopCount: 0,
    async start(_path, handlers) {
      this.starting = true;
      this.connected = true;
      this.inputActive = true;
      this.handlers = handlers;
      this.startCount += 1;
      activity.push("remote.start");
      handlers.onOpen();
      this.starting = false;
      return true;
    },
    stop() {
      this.connected = false;
      this.inputActive = false;
      this.stopCount += 1;
      activity.push("remote.stop");
    },
    sendJson(value) {
      if (!this.connected) return false;
      sent.push(value);
      return true;
    },
    sendRaw() { return this.connected; },
    pauseInput() {
      if (!this.connected) return false;
      this.inputActive = false;
      return true;
    },
    async resumeInput() {
      if (!this.connected) return false;
      this.inputActive = true;
      return true;
    },
    closeUnexpectedly() {
      if (!this.connected) return false;
      this.connected = false;
      this.inputActive = false;
      this.handlers.onClose({ code: 1006 });
      return true;
    },
  };

  const session = new PersonaBrowserVoiceSession({
    gate,
    wakeDetector,
    connection,
    getMachine: () => machine,
    dispatchVoice(action) { machine = reduceVoiceMachine(machine, action); },
    dispatchMany(actions) {
      for (const action of actions) machine = reduceVoiceMachine(machine, action);
    },
    getRecognitionContext: () => ({ localeHint: "zh-CN", sessionId: "full-chain" }),
    getCallbacks: () => ({
      onUserPartial(text) { emitted.push(["partial", text]); },
      onUserTranscript(text) { emitted.push(["user", text]); },
      onAssistantTranscript(text, meta) { emitted.push([meta.done ? "done" : "delta", text]); },
      onBargeIn() { activity.push("barge.in"); },
      onError(error) { errors.push(error.message); },
    }),
    onErrorState() {},
    onSpectrum() {},
    onMicrophoneEnabledChange(value) { activity.push(value ? "microphone.on" : "microphone.off"); },
    onWakeListeningChange(value) { activity.push(value ? "wake.ui.on" : "wake.ui.off"); },
    onWakeStartingChange(value) { activity.push(value ? "wake.preparing" : "wake.ready"); },
    createOutput: (options) => new VoiceOutputController({
      ...options,
      createTraceId: (() => {
        let id = 0;
        return () => `trace-${++id}`;
      })(),
      createClipCache: () => ({
        prewarm: () => Promise.resolve(""),
        sourceFor: () => Promise.resolve(""),
        dispose() {},
      }),
      createScheduler: (callbacks) => new TtsScheduler({
        ...callbacks,
        prepareSource: ({ segment }) => `/tts/${segment}`,
        createAudio(url) {
          const audio = new FakeAudio(url);
          audios.push(audio);
          return audio;
        },
      }),
    }),
    log: { info() {}, warn() {}, error() {} },
  });

  return {
    session, gate, wakeDetector, connection, timers, sent, emitted, audios, activity, errors,
    get machine() { return machine; },
    get status() { return deriveVoiceStatus(machine); },
    currentTimer() {
      const id = [...timers.keys()].at(-1);
      assert.ok(id !== undefined, "sleep timer must exist");
      return timers.get(id);
    },
    async sleep() {
      const callback = this.currentTimer();
      timers.clear();
      callback();
      for (let n = 0; n < 20 && !wakeDetector.active; n += 1) await Promise.resolve();
    },
    async wake() {
      assert.equal(wakeDetector.active, true);
      assert.equal(await wakeDetector.trigger(), true);
      assert.equal(connection.connected, true);
      assert.equal(wakeDetector.active, false);
      assert.equal(session.wakeListening, false);
    },
    question(id, turnId, text = "请介绍汴绣") {
      assert.equal(session.routeServerEvent({
        type: "user.transcript", utterance_id: id, text,
        revision: 1, locale: "zh-CN",
      }), true);
      assert.equal(session.routeServerEvent({
        type: "status", status: "thinking", turn_id: turnId,
      }), true);
      assert.equal(session.routeServerEvent({
        type: "assistant.delta", turn_id: turnId, text: "这是一段传统文化讲解。",
      }), true);
      assert.equal(audios.length > 0, true);
      const audio = audios.at(-1);
      audio.emit("playing");
      assert.equal(session.output.playing, true);
      assert.equal(this.status, "responding");
      assert.equal(session.routeServerEvent({
        type: "assistant.done", turn_id: turnId, text: "这是一段传统文化讲解。",
      }), true);
      return audio;
    },
  };
}

test("two complete real-state-machine voice cycles release remote capture during sleep", async () => {
  const h = makeFullChain();
  try {
    assert.equal(await h.session.armWake(), true);
    for (let cycle = 1; cycle <= 2; cycle += 1) {
      assert.equal(h.gate.sleeping, true);
      assert.equal(h.session.wakeListening, true);
      assert.equal(h.connection.connected, false);
      await h.wake();
      assert.equal(h.status, "listening");
      assert.equal(h.session.microphoneEnabled, true);
      const audio = h.question(1, `turn-${cycle}`);
      audio.emit("ended");
      assert.equal(h.session.output.pipelineActive, false);
      assert.equal(h.status, "listening");
      assert.equal(h.timers.size, 1);
      await h.sleep();
      assert.equal(h.connection.connected, false);
      assert.equal(h.gate.sleeping, true);
      assert.equal(h.session.wakeListening, true);
      assert.equal(h.session.microphoneEnabled, false);
    }
    assert.equal(h.connection.startCount, 2);
    assert.equal(h.wakeDetector.starts, 3);
    assert.deepEqual(h.emitted.filter(([type]) => type === "user").length, 2);
    assert.equal(h.errors.length, 0);
  } finally {
    h.session.destroy();
  }
});

test("barge-in cancels old TTS without letting late audio or acknowledgement break the next turn", async () => {
  const h = makeFullChain();
  try {
    await h.session.armWake();
    await h.wake();
    const first = h.question(1, "first-turn");
    h.session.input.state.utteranceActive = true;
    h.session.input.beginBargeInCandidate(2, 10);
    assert.equal(h.session.routeServerEvent({
      type: "user.partial", utterance_id: 2,
      revision: 1, text: "请介绍第二个传统技艺",
    }), true);
    const interrupt = h.sent.find((p) => p.type === "barge_in");
    assert.ok(interrupt);
    assert.match(interrupt.request_id, /^[0-9a-f]{32}$/u);
    assert.equal(h.session.output.playing, false);
    assert.equal(h.session.output.pipelineActive, false);
    assert.equal(first.pauseCalls > 0, true);
    assert.equal(h.session.routeServerEvent({
      type: "assistant.delta", turn_id: "first-turn", text: "旧答案。",
    }), false);

    h.session.input.state.utteranceActive = false;
    const second = h.question(2, "second-turn", "第二个传统技艺是什么");
    first.emit("playing");
    first.emit("ended");
    assert.equal(h.session.output.playing, true);
    assert.equal(h.status, "responding");

    assert.equal(h.session.routeServerEvent({
      type: "interrupt.ack", request_id: interrupt.request_id,
      reason: "barge_in", turn_id: "first-turn", cancelled: true,
    }), true);
    assert.equal(h.session.routeServerEvent({
      type: "interrupt.ack", request_id: interrupt.request_id,
      reason: "barge_in", turn_id: "first-turn", cancelled: true,
    }), false);
    assert.equal(h.session.output.playing, true);
    assert.equal(h.session.routeServerEvent({
      type: "assistant.done", turn_id: "first-turn", text: "旧答案。",
    }), false);

    second.emit("ended");
    assert.equal(h.timers.size, 1);
    await h.sleep();
    assert.equal(h.gate.sleeping, true);
    assert.equal(h.wakeDetector.active, true);
    assert.deepEqual(h.emitted.filter(([type]) => type === "user").map(([, t]) => t),
      ["请介绍汴绣", "第二个传统技艺是什么"]);
  } finally {
    h.session.destroy();
  }
});

test("unexpected disconnect during TTS releases media and restores only local keyword capture", async () => {
  const h = makeFullChain();
  try {
    await h.session.armWake();
    await h.wake();
    const audio = h.question(1, "before-disconnect");
    const oldSocketMessage = h.connection.handlers.onMessage;
    assert.equal(h.connection.closeUnexpectedly(), true);
    for (let tick = 0; tick < 20 && !h.session.wakeListening; tick += 1) await Promise.resolve();
    assert.equal(h.wakeDetector.active, true);
    assert.equal(h.session.wakeListening, true);
    assert.equal(h.connection.connected, false);
    assert.equal(h.session.microphoneEnabled, false);
    assert.equal(h.session.output.pipelineActive, false);
    assert.equal(audio.pauseCalls > 0, true);
    assert.equal(h.status, "idle");
    assert.equal(h.machine.fault, false);
    audio.emit("ended");
    assert.equal(h.timers.size, 0);

    // The transport adapter suppresses stale socket messages. Simulate only
    // events from the newly connected socket after the local wake handoff.
    assert.equal(typeof oldSocketMessage, "function");
    await h.wake();
    const current = h.question(1, "after-disconnect");
    current.emit("ended");
    assert.equal(h.timers.size, 1);
  } finally {
    h.session.destroy();
  }
});
