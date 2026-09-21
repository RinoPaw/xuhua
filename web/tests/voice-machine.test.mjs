import assert from "node:assert/strict";
import test from "node:test";

import {
  createVoiceMachineState,
  deriveVoiceStatus,
  isVoiceAssistantPending,
  REALTIME_VOICE_STATUS,
  reduceVoiceMachine,
  voiceActionsForServerStatus,
  VOICE_INPUT_PHASE,
  VOICE_OUTPUT_PHASE,
  VOICE_TRANSPORT_PHASE,
  VOICE_TURN_PHASE,
} from "../src/hooks/voiceState.js";


test("voice machine derives display status from orthogonal phases", () => {
  let state = createVoiceMachineState();
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.IDLE);

  state = reduceVoiceMachine(state, { type: "transport.connecting" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.CONNECTING);

  state = reduceVoiceMachine(state, { type: "transport.connected" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.LISTENING);

  state = reduceVoiceMachine(state, { type: "turn.thinking" });
  state = reduceVoiceMachine(state, { type: "output.pending" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.THINKING);

  state = reduceVoiceMachine(state, { type: "output.speaking" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.RESPONDING);

  state = reduceVoiceMachine(state, { type: "input.speaking" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.USER_SPEAKING);
});


test("assistant activity is derived from turn and output phases", () => {
  let state = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
  };
  assert.equal(isVoiceAssistantPending(state), false);

  state = reduceVoiceMachine(state, { type: "turn.thinking" });
  assert.equal(isVoiceAssistantPending(state), true);

  state = reduceVoiceMachine(state, { type: "turn.idle" });
  state = reduceVoiceMachine(state, { type: "output.pending" });
  assert.equal(isVoiceAssistantPending(state), true);

  state = reduceVoiceMachine(state, { type: "output.idle" });
  assert.equal(isVoiceAssistantPending(state), false);
});


test("pending output stays responding after first speech starts", () => {
  let state = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
  };
  state = reduceVoiceMachine(state, { type: "turn.thinking" });
  state = reduceVoiceMachine(state, { type: "output.pending" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.THINKING);

  state = reduceVoiceMachine(state, { type: "turn.idle" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.RESPONDING);
});


test("server statuses translate into semantic machine actions", () => {
  let state = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
    input: VOICE_INPUT_PHASE.TRANSCRIBING,
    turn: VOICE_TURN_PHASE.THINKING,
    output: VOICE_OUTPUT_PHASE.SPEAKING,
    fault: true,
  };

  for (const action of voiceActionsForServerStatus(REALTIME_VOICE_STATUS.LISTENING)) {
    state = reduceVoiceMachine(state, action);
  }
  assert.equal(state.input, VOICE_INPUT_PHASE.IDLE);
  assert.equal(state.turn, VOICE_TURN_PHASE.IDLE);
  assert.equal(state.output, VOICE_OUTPUT_PHASE.IDLE);
  assert.equal(state.fault, false);
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.LISTENING);

  for (const action of voiceActionsForServerStatus(REALTIME_VOICE_STATUS.THINKING)) {
    state = reduceVoiceMachine(state, action);
  }
  assert.equal(state.input, VOICE_INPUT_PHASE.IDLE);
  assert.equal(state.turn, VOICE_TURN_PHASE.THINKING);
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.THINKING);
});


test("voice machine represents overlapping activity without collapsing axes", () => {
  let state = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
  };
  state = reduceVoiceMachine(state, { type: "turn.thinking" });
  state = reduceVoiceMachine(state, { type: "output.speaking" });
  state = reduceVoiceMachine(state, { type: "input.speaking" });

  assert.equal(state.input, VOICE_INPUT_PHASE.SPEAKING);
  assert.equal(state.turn, VOICE_TURN_PHASE.THINKING);
  assert.equal(state.output, VOICE_OUTPUT_PHASE.SPEAKING);
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.USER_SPEAKING);
});


test("fault overlays phases and reset restores a clean idle state", () => {
  let state = {
    ...createVoiceMachineState(),
    transport: VOICE_TRANSPORT_PHASE.CONNECTED,
    input: VOICE_INPUT_PHASE.TRANSCRIBING,
  };
  state = reduceVoiceMachine(state, { type: "fault.raise" });
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.ERROR);

  state = reduceVoiceMachine(state, { type: "reset" });
  assert.deepEqual(state, createVoiceMachineState());
  assert.equal(deriveVoiceStatus(state), REALTIME_VOICE_STATUS.IDLE);
});
