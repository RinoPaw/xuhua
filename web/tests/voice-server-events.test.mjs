import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptServerVoiceError,
  acceptServerVoiceStatus,
  decodeVoiceServerEvent,
  resolveServerVoiceStatus,
} from "../src/lib/voiceServerEvents.js";
import { createVoiceInputState } from "../src/lib/voiceInput.js";
import { REALTIME_VOICE_STATUS } from "../src/hooks/voiceState.js";

test("server event decoder accepts only the current protocol", () => {
  assert.deepEqual(
    decodeVoiceServerEvent({
      type: "user.transcript",
      utterance_id: "3",
      text: "汴绣",
    }),
    {
      type: "user.transcript",
      utterance_id: 3,
      text: "汴绣",
    },
  );
  assert.equal(decodeVoiceServerEvent({ type: "future.event" }), null);
  assert.equal(decodeVoiceServerEvent({ type: "user.partial", utterance_id: 0 }), null);
  assert.equal(decodeVoiceServerEvent([]), null);
});

test("server status map normalizes protocol values", () => {
  assert.equal(resolveServerVoiceStatus({ status: "listening" }), REALTIME_VOICE_STATUS.LISTENING);
  assert.equal(resolveServerVoiceStatus({ status: "thinking" }), REALTIME_VOICE_STATUS.THINKING);
  assert.equal(resolveServerVoiceStatus({ status: "unknown" }), "");
});

test("older utterance status is rejected", () => {
  const inputState = createVoiceInputState();
  inputState.latestUtteranceId = 2;
  inputState.activeUtteranceId = 2;
  const result = acceptServerVoiceStatus(
    { status: "transcribing", utterance_id: 1 },
    {
      inputState,
      currentStatus: REALTIME_VOICE_STATUS.USER_SPEAKING,
    },
  );
  assert.equal(result.accepted, false);
});

test("thinking status captures the accepted assistant turn", () => {
  const inputState = createVoiceInputState();
  const result = acceptServerVoiceStatus(
    { status: "thinking", turn_id: "turn-2" },
    {
      inputState,
      currentStatus: REALTIME_VOICE_STATUS.LISTENING,
      assistantPending: true,
      activeTurn: "",
    },
  );
  assert.equal(result.accepted, true);
  assert.equal(result.status, REALTIME_VOICE_STATUS.THINKING);
  assert.equal(result.activeTurn, "turn-2");
});

test("tentative barge-in hides provider recognition statuses", () => {
  const inputState = createVoiceInputState();
  inputState.activeUtteranceId = 3;
  const result = acceptServerVoiceStatus(
    { status: "user_speaking", utterance_id: 3 },
    {
      inputState,
      currentStatus: REALTIME_VOICE_STATUS.RESPONDING,
      bargeInTentative: true,
    },
  );
  assert.equal(result.accepted, false);
});

test("server errors tied to ignored turns are rejected", () => {
  assert.equal(acceptServerVoiceError(
    { turn_id: "old-turn" },
    {
      activeTurn: "",
      assistantPending: true,
      ignoredTurns: new Set(["old-turn"]),
    },
  ), false);
  assert.equal(acceptServerVoiceError({ message: "transport" }), true);
});



test("ASR-scoped errors honor terminal and supersession boundaries", () => {
  const inputState = createVoiceInputState();
  inputState.latestUtteranceId = 5;
  assert.equal(acceptServerVoiceError({
    type: "error", utterance_id: 4, message: "late",
  }, { inputState }), false);
  assert.equal(acceptServerVoiceError({
    type: "error", utterance_id: 5, message: "current",
  }, { inputState }), true);
  assert.equal(inputState.finalizedUtteranceId, 5);
  assert.equal(acceptServerVoiceError({
    type: "error", utterance_id: 5, message: "duplicate",
  }, { inputState }), false);
  assert.equal(acceptServerVoiceError({
    type: "error", utterance_id: 6, message: "next",
  }, { inputState }), true);
});

test("ignored assistant turn errors never update utterance state", () => {
  const inputState = createVoiceInputState();
  assert.equal(acceptServerVoiceError({
    type: "error", turn_id: "old", utterance_id: 8,
  }, { inputState, assistantPending: true, ignoredTurns: new Set(["old"]) }), false);
  assert.equal(inputState.latestUtteranceId, 0);
  assert.equal(inputState.finalizedUtteranceId, 0);
});



test("interruption acknowledgements reject invalid requests and reasons", () => {
  const valid = {
    type: "interrupt.ack", request_id: "a".repeat(32),
    reason: "barge_in", cancelled: true, turn_id: "old", utterance_id: 2,
  };
  assert.deepEqual(decodeVoiceServerEvent(valid), valid);
  assert.equal(decodeVoiceServerEvent({ ...valid, request_id: "invalid" }), null);
  assert.equal(decodeVoiceServerEvent({ ...valid, reason: "unknown" }), null);
  assert.equal(decodeVoiceServerEvent({ ...valid, cancelled: "true" }), null);
});
