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



test("duplicate final transcript does not interrupt the new answer", () => {
  const h = createHarness();
  const transcript = { type: "user.transcript", utterance_id: 4, text: "第一问" };

  assert.equal(routeVoiceServerEvent(transcript, {
    state: h.state, actions: h.actions,
  }), true);
  assert.equal(h.state.input.finalizedUtteranceId, 4);
  h.setMachine(reduceVoiceMachine(h.state.machine, { type: "output.speaking" }));
  h.state.output.playing = true;
  h.calls.length = 0;

  assert.equal(routeVoiceServerEvent(transcript, {
    state: h.state, actions: h.actions,
  }), false);
  assert.equal(routeVoiceServerEvent({
    type: "user.partial", utterance_id: 4, text: "旧文本",
  }, { state: h.state, actions: h.actions }), false);
  assert.deepEqual(h.calls, []);
});

test("old ASR errors cannot stop a newer assistant turn or TTS", () => {
  const h = createHarness();
  const context = { state: h.state, actions: h.actions };
  assert.equal(routeVoiceServerEvent({
    type: "user.transcript", utterance_id: 1, text: "旧问题",
  }, context), true);
  assert.equal(routeVoiceServerEvent({
    type: "user.transcript", utterance_id: 2, text: "新问题",
  }, context), true);
  h.state.turns.setActive("turn-new");
  h.state.output.pipelineActive = true;
  h.setMachine(reduceVoiceMachine(h.state.machine, { type: "output.speaking" }));
  h.calls.length = 0;

  assert.equal(routeVoiceServerEvent({
    type: "error", utterance_id: 1, code: "asr_unavailable", message: "旧识别失败",
  }, context), false);
  assert.equal(h.state.turns.current, "turn-new");
  assert.deepEqual(h.calls, []);
});

test("ASR error is terminal for its utterance but not the next one", () => {
  const h = createHarness();
  const context = { state: h.state, actions: h.actions };
  const asrFailure = {
    type: "error", utterance_id: 3, code: "asr_unavailable", message: "无法识别",
  };
  assert.equal(routeVoiceServerEvent(asrFailure, context), true);
  assert.equal(h.state.input.finalizedUtteranceId, 3);
  assert.equal(routeVoiceServerEvent(asrFailure, context), false);
  assert.equal(routeVoiceServerEvent({
    type: "user.transcript", utterance_id: 4, text: "新的提问",
  }, context), true);
  assert.deepEqual(
    h.calls.filter((call) => call[0] === "reportError"),
    [["reportError", "无法识别"]],
  );
});

test("repeated rejection cannot reset next utterance's transcription", () => {
  const h = createHarness();
  const context = { state: h.state, actions: h.actions };
  assert.equal(routeVoiceServerEvent({
    type: "utterance.rejected", utterance_id: 2,
  }, context), true);
  h.calls.length = 0;
  assert.equal(routeVoiceServerEvent({
    type: "utterance.rejected", utterance_id: 2,
  }, context), false);
  assert.equal(routeVoiceServerEvent({
    type: "user.transcript", utterance_id: 3, text: "当前问题",
  }, context), true);
  assert.deepEqual(h.calls, [
    ["markThinking"], ["publishUserTranscript", "当前问题"],
  ]);
});



test("router delegates cancellation confirmation without touching voice state", () => {
  const h = createHarness();
  const machineBefore = h.state.machine;
  const ack = {
    type: "interrupt.ack", request_id: "a".repeat(32),
    reason: "barge_in", cancelled: true,
  };
  h.actions.confirmInterruptAck = (message) => {
    h.calls.push(["confirmInterruptAck", message.request_id]);
    return true;
  };
  assert.equal(routeVoiceServerEvent(ack, {
    state: h.state, actions: h.actions,
  }), true);
  assert.deepEqual(h.calls, [["confirmInterruptAck", ack.request_id]]);
  assert.deepEqual(h.state.machine, machineBefore);
});


test("capacity rejection settles only the input and preserves an active answer", () => {
  const h = createHarness();
  h.state.output.pipelineActive = true;
  h.state.output.playing = true;
  h.state.input.utteranceActive = true;
  const context = { state: h.state, actions: h.actions };
  assert.equal(routeVoiceServerEvent({
    type: "utterance.rejected", utterance_id: 4,
    reason: "voice_asr_capacity",
  }, context), true);
  assert.equal(h.state.input.finalizedUtteranceId, 4);
  assert.equal(h.state.input.activeUtteranceId, 0);
  assert.equal(h.state.output.playing, true);
  assert.deepEqual(h.calls, [["rejectTranscript"], ["settleListening"]]);
});
