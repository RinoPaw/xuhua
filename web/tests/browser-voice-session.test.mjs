import assert from "node:assert/strict";
import test from "node:test";

import { BrowserVoiceSession } from "../src/lib/browserVoiceSession.js";
import {
  createVoiceMachineState,
  deriveVoiceStatus,
  reduceVoiceMachine,
} from "../src/hooks/voiceState.js";

function createHarness() {
  const sent = [];
  const calls = [];
  let machine = createVoiceMachineState();
  const connection = {
    starting: false,
    connected: false,
    inputActive: false,
    sendJson(payload) {
      if (!this.connected) return false;
      sent.push(payload);
      return true;
    },
    stop() {
      this.starting = false;
      this.connected = false;
      this.inputActive = false;
      calls.push(["connection.stop"]);
    },
    pauseInput() {
      if (!this.connected) return false;
      this.inputActive = false;
      calls.push(["connection.pauseInput"]);
      return true;
    },
    async resumeInput(onSamples) {
      if (!this.connected) return false;
      this.inputActive = true;
      this.onSamples = onSamples;
      calls.push(["connection.resumeInput"]);
      return true;
    },
    async start(path, handlers) {
      calls.push(["connection.start", path]);
      this.starting = true;
      this.connected = true;
      this.inputActive = true;
      this.handlers = handlers;
      handlers.onOpen?.();
      this.starting = false;
      return true;
    },
  };
  const input = {
    state: {
      utteranceActive: false,
      latestUtteranceId: 0,
      activeUtteranceId: 0,
      nextUtteranceId: 0,
      lastVoiceAt: 0,
    },
    bargeInPhase: "idle",
    get utteranceActive() { return this.state.utteranceActive; },
    reset() { calls.push(["input.reset"]); this.state.utteranceActive = false; },
    supersedeUtterance() {
      calls.push(["input.supersede"]);
      this.state.utteranceActive = false;
      return this.state;
    },
    resetOnset() { calls.push(["input.resetOnset"]); },
    clearBargeInCandidate() { this.bargeInPhase = "idle"; calls.push(["input.clearBargeIn"]); return true; },
    confirmBargeInCandidate() {
      if (this.bargeInPhase !== "tentative") return false;
      this.bargeInPhase = "idle";
      calls.push(["input.confirmBargeIn"]);
      return true;
    },
    finishActiveUtterance({ connection: activeConnection, onTranscribing, onTransportFailure }) {
      calls.push(["input.finishActive"]);
      if (!this.state.utteranceActive) return true;
      if (!activeConnection.sendJson({ type: "utterance.end" })) {
        onTransportFailure?.();
        return false;
      }
      this.state.utteranceActive = false;
      onTranscribing?.();
      return true;
    },
    blockFor(ms) { calls.push(["input.block", ms]); },
    unblock() { calls.push(["input.unblock"]); },
    process() { calls.push(["input.process"]); return {}; },
  };
  const output = {
    pipelineActive: false,
    playing: false,
    traceId: "",
    setWebsocketPath(path) { this.websocketPath = path; },
    prewarm(text, locale) { calls.push(["output.prewarm", text, locale]); return Promise.resolve("blob:ack"); },
    begin(locale) { this.pipelineActive = true; calls.push(["output.begin", locale]); return 1; },
    append(text, locale) { calls.push(["output.append", text, locale]); return true; },
    finish(text, locale) { calls.push(["output.finish", text, locale]); return true; },
    stop() { this.pipelineActive = false; this.playing = false; calls.push(["output.stop"]); return true; },
    dispose() { calls.push(["output.dispose"]); },
  };
  const turns = {
    current: "turn-1",
    ignoredTurns: new Set(["old-turn"]),
    ignoreActive() { calls.push(["turn.ignore", this.current]); this.current = ""; return true; },
    accept(message) { if (!message?.turn_id) return false; this.current = message.turn_id; return true; },
    setActive(id) { this.current = id; return true; },
    ignore(id) { this.ignoredTurns.add(id); if (this.current === id) this.current = ""; return true; },
    reset() { this.current = ""; this.ignoredTurns.clear(); calls.push(["turn.reset"]); },
  };
  const transcript = {
    clear(reset) { calls.push(["transcript.clear", reset]); },
    publishPartial() { return true; },
    publishTranscript() { return true; },
    reject() { return true; },
  };
  const callbacks = {
    onBargeIn: () => calls.push(["callback.bargeIn"]),
    onError: (error) => calls.push(["callback.error", error.message]),
  };
  const errors = [];

  const session = new BrowserVoiceSession({
    websocketPath: "/api/voice",
    getMachine: () => machine,
    dispatchVoice(action) {
      machine = reduceVoiceMachine(machine, action);
      calls.push(["dispatch", action.type]);
    },
    dispatchMany(actions) {
      for (const action of actions) machine = reduceVoiceMachine(machine, action);
      calls.push(["dispatchMany", actions.map((action) => action.type)]);
    },
    getRecognitionContext: () => ({
      sessionId: "session-1",
      category: "传统技艺",
      localeHint: "zh-CN",
    }),
    getCallbacks: () => callbacks,
    onErrorState: (error) => errors.push(error?.message || null),
    onSpectrum: () => {},
    onMicrophoneEnabledChange: (enabled) => calls.push(["microphone", enabled]),
    connection,
    input,
    turns,
    transcript,
    createOutput: () => output,
    log: { info() {} },
  });

  return {
    session,
    connection,
    input,
    output,
    turns,
    calls,
    sent,
    errors,
    get machine() { return machine; },
  };
}

test("browser voice session owns startup, context sync, and transport state", async () => {
  const harness = createHarness();

  assert.equal(await harness.session.start(), true);
  assert.equal(harness.machine.transport, "connected");
  assert.equal(harness.session.microphoneEnabled, true);
  assert.deepEqual(harness.sent[0], {
    type: "context",
    category: "传统技艺",
    titles: [],
    selected_title: "",
    session_id: "session-1",
    locale_hint: "zh-CN",
    preferred_locales: ["zh-CN"],
  });
  assert.equal(harness.calls.some((entry) => entry[0] === "connection.start"), true);
  assert.equal(
    harness.calls.some((entry) => entry[0] === "output.prewarm" && entry[1] === "我在。" && entry[2] === "zh-CN"),
    true,
  );
});

test("voice startup fails if the initial context frame cannot be sent", async () => {
  const harness = createHarness();
  harness.connection.sendJson = () => false;

  assert.equal(await harness.session.start(), false);
  assert.equal(harness.connection.connected, false);
  assert.equal(harness.machine.transport, "idle");
  assert.equal(harness.errors.at(-1), "voice_socket_send_failed");
});

test("microphone pause keeps socket, output, and active agent turn alive", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.output.pipelineActive = true;
  harness.output.playing = true;
  harness.turns.current = "turn-live";
  const stopCount = harness.calls.filter((entry) => entry[0] === "output.stop").length;

  assert.equal(harness.session.pauseMicrophone(), true);
  assert.equal(harness.connection.connected, true);
  assert.equal(harness.connection.inputActive, false);
  assert.equal(harness.session.microphoneEnabled, false);
  assert.equal(harness.output.pipelineActive, true);
  assert.equal(harness.output.playing, true);
  assert.equal(harness.turns.current, "turn-live");
  assert.equal(harness.calls.filter((entry) => entry[0] === "output.stop").length, stopCount);
  assert.equal(harness.calls.some((entry) => entry[0] === "callback.bargeIn"), false);
});

test("microphone pause finalizes an active utterance before releasing capture", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.input.state.utteranceActive = true;
  harness.input.state.lastVoiceAt = 123;

  assert.equal(harness.session.pauseMicrophone(), true);
  assert.equal(harness.input.state.utteranceActive, false);
  assert.deepEqual(harness.sent.at(-1), { type: "utterance.end" });
  assert.equal(harness.calls.some((entry) => entry[0] === "connection.pauseInput"), true);
  assert.equal(harness.calls.some((entry) => entry[0] === "dispatch" && entry[1] === "input.transcribing"), true);
});

test("microphone can resume without reopening the voice socket", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.session.pauseMicrophone();
  const starts = harness.calls.filter((entry) => entry[0] === "connection.start").length;

  assert.equal(await harness.session.resumeMicrophone(), true);
  assert.equal(harness.connection.connected, true);
  assert.equal(harness.connection.inputActive, true);
  assert.equal(harness.session.microphoneEnabled, true);
  assert.equal(harness.calls.filter((entry) => entry[0] === "connection.start").length, starts);
  assert.equal(harness.calls.some((entry) => entry[0] === "connection.resumeInput"), true);
});

test("browser voice session centralizes barge-in output cancellation", () => {
  const harness = createHarness();
  harness.connection.connected = true;
  harness.output.pipelineActive = true;
  harness.input.bargeInPhase = "tentative";

  assert.equal(harness.session.confirmBargeInFromAsr(), true);
  assert.equal(harness.output.pipelineActive, false);
  assert.equal(harness.turns.current, "");
  assert.deepEqual(harness.sent.at(-1), { type: "barge_in" });
  assert.equal(harness.calls.some((entry) => entry[0] === "callback.bargeIn"), true);
});

test("browser voice session supersedes microphone input before a typed turn", () => {
  const harness = createHarness();
  harness.connection.connected = true;
  harness.input.state.utteranceActive = true;

  assert.equal(harness.session.sendText("  汴绣是什么  "), true);
  assert.equal(harness.input.state.utteranceActive, false);
  assert.equal(harness.calls.some((entry) => entry[0] === "input.supersede"), true);
  assert.equal(
    harness.calls.some((entry) => entry[0] === "transcript.clear" && entry[1] === true),
    true,
  );
  assert.deepEqual(harness.sent, [{ type: "text", text: "汴绣是什么" }]);
  assert.equal(harness.calls.some((entry) => entry[0] === "callback.bargeIn"), true);
  assert.equal(harness.machine.turn, "thinking");
});

test("disconnected typed input has no voice-session side effects", () => {
  const harness = createHarness();
  harness.input.state.utteranceActive = true;

  assert.equal(harness.session.sendText("汴绣"), false);
  assert.equal(harness.input.state.utteranceActive, true);
  assert.equal(harness.sent.length, 0);
  assert.equal(harness.calls.some((entry) => entry[0] === "input.supersede"), false);
});

test("failed typed socket send does not commit a new turn and tears down transport", () => {
  const harness = createHarness();
  harness.connection.connected = true;
  harness.connection.sendJson = () => false;
  harness.input.state.utteranceActive = true;
  const callCount = harness.calls.length;

  assert.equal(harness.session.sendText("汴绣"), false);
  assert.equal(harness.connection.connected, false);
  assert.equal(harness.input.state.utteranceActive, false);
  const newCalls = harness.calls.slice(callCount);
  assert.equal(newCalls.some((entry) => entry[0] === "input.supersede"), false);
  assert.equal(newCalls.some((entry) => entry[0] === "callback.bargeIn"), false);
  assert.notEqual(harness.machine.turn, "thinking");
  assert.equal(harness.machine.transport, "idle");
  assert.equal(harness.errors.at(-1), "voice_socket_send_failed");
});

test("failed connected context sync tears down the unusable socket", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.connection.sendJson = () => false;

  assert.equal(harness.session.syncRecognitionContext(), false);
  assert.equal(harness.connection.connected, false);
  assert.equal(harness.machine.transport, "idle");
  assert.equal(harness.errors.at(-1), "voice_socket_send_failed");
});

test("runtime send failure tears down the voice transport and reports a fault", async () => {
  const harness = createHarness();
  await harness.session.start();

  assert.equal(harness.session.handleTransportFailure(), false);
  assert.equal(harness.connection.connected, false);
  assert.equal(harness.machine.transport, "idle");
  assert.equal(harness.errors.at(-1), "voice_socket_send_failed");
  assert.equal(harness.calls.filter((entry) => entry[0] === "callback.error").length, 1);
});

test("TTS terminal clears pending output machine state", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.session.dispatchMany([
    { type: "turn.idle" },
    { type: "output.pending" },
  ]);
  harness.output.pipelineActive = false;

  assert.equal(deriveVoiceStatus(harness.machine), "responding");
  harness.session.handleOutputTerminal({ failed: false });

  assert.equal(harness.machine.output, "idle");
  assert.equal(harness.machine.turn, "idle");
  assert.equal(deriveVoiceStatus(harness.machine), "listening");
  assert.equal(
    harness.calls.some((entry) => entry[0] === "input.block" && entry[1] === 450),
    true,
  );
});

test("connection cleanup resets turn identity from the old socket", () => {
  const harness = createHarness();
  harness.turns.current = "turn-2";
  harness.turns.ignoredTurns.add("turn-1");

  harness.session.stop();

  assert.equal(harness.turns.current, "");
  assert.equal(harness.turns.ignoredTurns.size, 0);
  assert.equal(harness.calls.some((entry) => entry[0] === "turn.reset"), true);
});

test("unexpected socket close is cleaned up and reported once", async () => {
  const harness = createHarness();
  await harness.session.start();
  harness.connection.handlers.onClose({ code: 1006 });

  assert.equal(harness.machine.transport, "idle");
  assert.equal(harness.errors.at(-1), "voice_socket_closed");
  assert.equal(harness.calls.filter((entry) => entry[0] === "callback.error").length, 1);
});
