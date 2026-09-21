import assert from "node:assert/strict";
import test from "node:test";

import { BARGE_IN_PHASE } from "../src/hooks/bargeInState.js";
import {
  createVoiceMachineState,
  reduceVoiceMachine,
  VOICE_TRANSPORT_PHASE,
} from "../src/hooks/voiceState.js";
import { routeVoiceServerEvent } from "../src/lib/voiceEventRouter.js";
import { createVoiceInputState } from "../src/lib/voiceInput.js";
import { VoiceTurnTracker } from "../src/lib/voiceProtocol.js";

function createHarness() {
  const calls = [];
  let machine = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
  };
  const state = {
    input: createVoiceInputState(),
    get machine() { return machine; },
    get status() {
      if (machine.input === "speaking") return "user_speaking";
      if (machine.input === "transcribing") return "transcribing";
      if (machine.output === "speaking") return "responding";
      if (machine.turn === "thinking" || machine.output === "pending") return "thinking";
      return "listening";
    },
    turns: new VoiceTurnTracker(),
    output: { pipelineActive: false, playing: false },
    presenter: {
      publishPartial(message) { calls.push(["publishUserPartial", message.text]); },
      publishTranscript(message, text) { calls.push(["publishUserTranscript", text]); },
      reject() { calls.push(["rejectTranscript"]); },
    },
    bargeInPhase: BARGE_IN_PHASE.IDLE,
    localeHint: "zh-CN",
  };
  const actions = {
    dispatchMany(items) {
      for (const action of items) machine = reduceVoiceMachine(machine, action);
      calls.push(["dispatchMany", items.map((item) => item.type)]);
    },
    clearBargeInCandidate() { calls.push(["clearBargeInCandidate"]); },
    confirmBargeInFromAsr() { calls.push(["confirmBargeInFromAsr"]); },
    stopSpeech(bargeIn, notifyServer) { calls.push(["stopSpeech", bargeIn, notifyServer]); },
    settleListening() { calls.push(["settleListening"]); },
    markThinking() {
      machine = reduceVoiceMachine(machine, { type: "turn.thinking" });
      calls.push(["markThinking"]);
    },
    appendSpeechDelta(text, locale) { calls.push(["appendSpeechDelta", text, locale]); },
    finishSpeechStream(text, locale) { calls.push(["finishSpeechStream", text, locale]); },
    clearError() { calls.push(["clearError"]); },
    reportError(message) { calls.push(["reportError", message]); },
  };
  return { state, actions, calls, setMachine(value) { machine = value; } };
}

test("router maps accepted server status into semantic machine actions", () => {
  const harness = createHarness();
  harness.setMachine(reduceVoiceMachine(harness.state.machine, { type: "turn.thinking" }));

  const accepted = routeVoiceServerEvent(
    { type: "status", status: "thinking", turn_id: "turn-1" },
    { state: harness.state, actions: harness.actions },
  );

  assert.equal(accepted, true);
  assert.equal(harness.state.turns.current, "turn-1");
  assert.deepEqual(harness.calls.at(-1), ["dispatchMany", ["input.idle", "turn.thinking"]]);
});

test("router commits a user transcript and starts the next assistant turn", () => {
  const harness = createHarness();

  const accepted = routeVoiceServerEvent(
    { type: "user.transcript", utterance_id: 1, text: "  汴绣是什么  " },
    { state: harness.state, actions: harness.actions },
  );

  assert.equal(accepted, true);
  assert.equal(harness.state.input.latestUtteranceId, 1);
  assert.deepEqual(harness.calls, [
    ["markThinking"],
    ["publishUserTranscript", "汴绣是什么"],
  ]);
});

test("router owns assistant turn acceptance through delta and done", () => {
  const harness = createHarness();
  harness.setMachine(reduceVoiceMachine(harness.state.machine, { type: "turn.thinking" }));
  const transcripts = [];
  const context = {
    state: harness.state,
    actions: harness.actions,
    callbacks: {
      onAssistantTranscript: (text, meta) => transcripts.push([text, meta.done, meta.locale]),
    },
  };

  assert.equal(routeVoiceServerEvent(
    { type: "assistant.delta", turn_id: "turn-1", text: "第一句", locale: "zh-CN" },
    context,
  ), true);
  assert.equal(routeVoiceServerEvent(
    { type: "assistant.done", turn_id: "turn-1", text: "完整回答", locale: "zh-CN" },
    context,
  ), true);

  assert.deepEqual(transcripts, [
    ["第一句", false, "zh-CN"],
    ["完整回答", true, "zh-CN"],
  ]);
  assert.deepEqual(harness.calls, [
    ["appendSpeechDelta", "第一句", "zh-CN"],
    ["finishSpeechStream", "完整回答", "zh-CN"],
  ]);
  assert.equal(harness.state.turns.current, "");
  assert.equal(harness.state.turns.ignoredTurns.has("turn-1"), true);
  assert.equal(routeVoiceServerEvent(
    { type: "assistant.delta", turn_id: "turn-1", text: "迟到" },
    context,
  ), false);
});

test("router rejects errors for ignored assistant turns", () => {
  const harness = createHarness();
  harness.state.turns.ignore("turn-old");
  harness.setMachine(reduceVoiceMachine(harness.state.machine, { type: "turn.thinking" }));

  const accepted = routeVoiceServerEvent(
    { type: "error", turn_id: "turn-old", message: "late" },
    { state: harness.state, actions: harness.actions },
  );

  assert.equal(accepted, false);
  assert.deepEqual(harness.calls, []);
});
