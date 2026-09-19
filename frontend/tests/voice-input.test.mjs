import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptVoiceUtteranceMessage,
  createVoiceInputState,
  processVoiceInputFrame,
  resetVoiceInputPhase,
} from "../src/lib/voiceInput.js";

function constantSamples(length, value) {
  return Float32Array.from({ length }, () => value);
}

test("voice input emits onset, retained PCM and transcribing transition", () => {
  const state = createVoiceInputState();
  const onset = processVoiceInputFrame(state, {
    samples: constantSamples(960, 0.1), // 60 ms at 16 kHz
    inputRate: 16000,
    now: 1000,
    transportReady: true,
    agentBusy: false,
  });

  assert.equal(onset.started?.utteranceId, 1);
  assert.equal(onset.started?.shouldInterrupt, false);
  assert.equal(onset.nextStatus, "user_speaking");
  assert.equal(onset.actions[0].kind, "json");
  assert.equal(onset.actions[0].payload.type, "utterance.start");
  assert.ok(onset.actions.some((action) => action.kind === "binary"));
  assert.equal(state.utteranceActive, true);

  const ending = processVoiceInputFrame(state, {
    samples: constantSamples(1600, 0),
    inputRate: 16000,
    now: 1800,
    transportReady: true,
    agentBusy: false,
  });

  assert.equal(ending.actions.at(-1).payload.type, "utterance.end");
  assert.equal(ending.nextStatus, "transcribing");
  assert.equal(state.utteranceActive, false);
});

test("busy agent marks onset as interruption without forcing user status", () => {
  const state = createVoiceInputState();
  const onset = processVoiceInputFrame(state, {
    samples: constantSamples(960, 0.1),
    inputRate: 16000,
    now: 1000,
    transportReady: true,
    playbackActive: false,
    agentBusy: true,
  });

  assert.equal(onset.started?.shouldInterrupt, true);
  assert.equal(onset.actions[0].payload.interrupt, true);
  assert.equal(onset.nextStatus, null);
});

test("blocked input resets transient capture state before transport checks", () => {
  const state = createVoiceInputState();
  state.utteranceActive = true;
  state.utteranceStartedAt = 12;
  state.gate = { aboveMs: 80, onset: true };

  const result = processVoiceInputFrame(state, {
    samples: constantSamples(128, 0.1),
    inputRate: 48000,
    now: 100,
    blockedUntil: 200,
    transportReady: false,
  });

  assert.deepEqual(result.actions, []);
  assert.equal(state.gate.aboveMs, 0);
  assert.equal(state.utteranceActive, true);
});

test("utterance acceptance and full reset keep server ordering explicit", () => {
  const state = createVoiceInputState();
  state.activeUtteranceId = 2;
  state.latestUtteranceId = 2;
  state.nextUtteranceId = 2;

  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 1 }), false);
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 2 }), true);
  assert.equal(acceptVoiceUtteranceMessage(state, {}, { required: false }), true);

  resetVoiceInputPhase(state, { resetIds: true, discardResampler: true });
  assert.equal(state.utteranceActive, false);
  assert.equal(state.latestUtteranceId, 0);
  assert.equal(state.activeUtteranceId, 0);
  assert.equal(state.nextUtteranceId, 0);
  assert.equal(state.resampler, null);
});
