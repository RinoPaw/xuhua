import assert from "node:assert/strict";
import test from "node:test";

import { BrowserVoiceSession } from "../src/lib/browserVoiceSession.js";
import {
  createVoiceMachineState,
  reduceVoiceMachine,
} from "../src/hooks/voiceState.js";

function createHarness() {
  const sent = [];
  const calls = [];
  let machine = createVoiceMachineState();
  const connection = {
    starting: false,
    connected: false,
    sendJson(payload) {
      if (!this.connected) return false;
      sent.push(payload);
      return true;
    },
    stop() {
      this.connected = false;
      calls.push(["connection.stop"]);
    },
    async start(path, handlers) {
      calls.push(["connection.start", path]);
      this.starting = true;
      this.connected = true;
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
    },
    bargeInPhase: "idle",
    get utteranceActive() { return this.state.utteranceActive; },
    reset() { calls.push(["input.reset"]); this.state.utteranceActive = false; },
    resetOnset() { calls.push(["input.resetOnset"]); },
    clearBargeInCandidate() { this.bargeInPhase = "idle"; calls.push(["input.clearBargeIn"]); return true; },
    confirmBargeInCandidate() {
      if (this.bargeInPhase !== "tentative") return false;
      this.bargeInPhase = "idle";
      calls.push(["input.confirmBargeIn"]);
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
    begin(locale) { this.pipelineActive = true; calls.push(["output.begin", locale]); return 1; },
    append(text, locale) { calls.push(["output.append", text, locale]); return true; },
    finish(text, locale) { calls.push(["output.finish", text, locale]); return true; },
    stop() { this.pipelineActive = false; this.playing = false; calls.push(["output.stop"]); return true; },
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

test("browser voice session sends text through one turn transition", () => {
  const harness = createHarness();
  harness.connection.connected = true;

  assert.equal(harness.session.sendText("  汴绣是什么  "), true);
  assert.deepEqual(harness.sent.slice(-2), [
    { type: "barge_in" },
    { type: "text", text: "汴绣是什么" },
  ]);
  assert.equal(harness.machine.turn, "thinking");
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
