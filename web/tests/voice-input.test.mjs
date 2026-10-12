import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptVoiceUtteranceMessage,
  createVoiceInputState,
  processVoiceInputFrame,
  resetVoiceInputPhase,
  supersedeVoiceUtterance,
  VOICE_INPUT_LIMITS,
} from "../src/lib/voiceInput.js";

function constantSamples(length, value) {
  return Float32Array.from({ length }, () => value);
}

test("voice input holds short speech pauses but eventually finalizes", () => {
  const state = createVoiceInputState();
  const onset = processVoiceInputFrame(state, {
    samples: constantSamples(960, 0.1), // 60 ms at 16 kHz
    inputRate: 16000,
    now: 1000,
    transportReady: true,
    agentBusy: false,
  });

  assert.equal(VOICE_INPUT_LIMITS.silenceMs, 420);
  assert.equal(VOICE_INPUT_LIMITS.shortSilenceMs, 720);
  assert.equal(VOICE_INPUT_LIMITS.shortUtteranceMs, 1200);
  assert.equal(onset.started?.utteranceId, 1);
  assert.equal(onset.started?.shouldInterrupt, false);
  assert.equal(onset.nextStatus, "user_speaking");
  assert.equal(onset.actions[0].kind, "json");
  assert.equal(onset.actions[0].payload.type, "utterance.start");
  assert.ok(onset.actions.some((action) => action.kind === "binary"));
  assert.equal(state.utteranceActive, true);

  const stillOpen = processVoiceInputFrame(state, {
    samples: constantSamples(1600, 0),
    inputRate: 16000,
    now: 1720,
    transportReady: true,
    agentBusy: false,
  });
  assert.equal(stillOpen.actions.some((action) => action.payload?.type === "utterance.end"), false);
  assert.equal(state.utteranceActive, true);

  const ending = processVoiceInputFrame(state, {
    samples: constantSamples(1600, 0),
    inputRate: 16000,
    now: 1721,
    transportReady: true,
    agentBusy: false,
  });

  assert.equal(ending.actions.at(-1).payload.type, "utterance.end");
  assert.equal(ending.nextStatus, "transcribing");
  assert.equal(state.utteranceActive, false);
});

test("busy agent requires sustained voice before marking interruption", () => {
  const state = createVoiceInputState();
  const frame = (now) => processVoiceInputFrame(state, {
    samples: constantSamples(960, 0.1),
    inputRate: 16000,
    now,
    transportReady: true,
    playbackActive: false,
    agentBusy: true,
  });
  assert.equal(frame(1000).started, null);
  assert.equal(frame(1060).started, null);
  const onset = frame(1120);
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
  assert.equal(state.minimumUtteranceId, 1);
  assert.equal(state.resampler, null);
});

test("superseding input rejects the old utterance and preserves the next server id", () => {
  const state = createVoiceInputState();
  state.utteranceActive = true;
  state.activeUtteranceId = 3;
  state.latestUtteranceId = 2;
  state.nextUtteranceId = 3;

  assert.equal(supersedeVoiceUtterance(state), 4);
  assert.equal(state.utteranceActive, false);
  assert.equal(state.minimumUtteranceId, 4);
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 3 }), false);

  const next = processVoiceInputFrame(state, {
    samples: constantSamples(960, 0.1),
    inputRate: 16000,
    now: 2000,
    transportReady: true,
    agentBusy: false,
  });
  assert.equal(next.started?.utteranceId, 4);
  assert.equal(state.activeUtteranceId, 4);
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 4 }), true);
});



test("terminal utterance acceptance resets only on a new connection", () => {
  const state = createVoiceInputState();
  assert.equal(acceptVoiceUtteranceMessage(state, {
    utterance_id: 7,
  }, { terminal: true }), true);
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 7 }), false);
  resetVoiceInputPhase(state);
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 7 }), false);
  resetVoiceInputPhase(state, { resetIds: true });
  assert.equal(acceptVoiceUtteranceMessage(state, { utterance_id: 7 }), true);
});


test("natural speech resumed within the silence window stays in one ASR utterance", () => {
  const state = createVoiceInputState();
  const frame = (now, level) => processVoiceInputFrame(state, {
    samples: constantSamples(960, level),
    inputRate: 16000,
    now,
    transportReady: true,
    agentBusy: false,
  });
  assert.equal(frame(1000, 0.1).started?.utteranceId, 1);
  assert.equal(frame(1300, 0).actions.some((entry) => entry.payload?.type === "utterance.end"), false);
  // New speech before the 720ms short-speech deadline moves it forward.
  assert.equal(frame(1320, 0.1).actions.some((entry) => entry.payload?.type === "utterance.end"), false);
  assert.equal(frame(2020, 0).actions.some((entry) => entry.payload?.type === "utterance.end"), false);
  assert.equal(frame(2041, 0).actions.at(-1).payload.type, "utterance.end");
});


test("short connected speech separated by a 600ms pause stays in one ASR request", () => {
  const state = createVoiceInputState();
  const frame = (now, level) => processVoiceInputFrame(state, {
    samples: constantSamples(960, level),
    inputRate: 16000,
    now,
    transportReady: true,
    agentBusy: false,
  });
  assert.equal(frame(1000, 0.1).actions[0].payload.type, "utterance.start");
  assert.equal(frame(1600, 0).actions.some(({ payload }) => payload?.type === "utterance.end"), false);
  const continuation = frame(1680, 0.1);
  assert.equal(continuation.actions.some(({ payload }) => payload?.type === "utterance.start"), false);
  assert.equal(state.utteranceActive, true);
  assert.equal(frame(2401, 0).actions.at(-1).payload.type, "utterance.end");
});

test("long spoken questions keep a faster 420ms endpoint", () => {
  const state = createVoiceInputState();
  const frame = (now, level) => processVoiceInputFrame(state, {
    samples: constantSamples(960, level),
    inputRate: 16000,
    now,
    transportReady: true,
    agentBusy: false,
  });
  frame(1000, 0.1);
  frame(2400, 0.1);
  assert.equal(frame(2820, 0).actions.some(({ payload }) => payload?.type === "utterance.end"), false);
  assert.equal(frame(2821, 0).actions.at(-1).payload.type, "utterance.end");
});

test("an assistant preparing speech requires sustained onset before barge-in", () => {
  const state = createVoiceInputState();
  const frame = (now, level, busy = true) => processVoiceInputFrame(state, {
    samples: constantSamples(960, level),
    inputRate: 16000,
    now,
    transportReady: true,
    playbackActive: false,
    agentBusy: busy,
  });
  for (let now = 1000; now < 1450; now += 60) {
    assert.equal(frame(now, 0.020).started, null);
  }
  assert.equal(state.utteranceActive, false);
  assert.equal(frame(1500, 0.08).started, null);
  assert.equal(frame(1560, 0.08).started, null);
  const onset = frame(1620, 0.08);
  assert.equal(onset.started?.shouldInterrupt, true);
  assert.equal(onset.actions[0].payload.threshold, 0.022);
  assert.equal(onset.actions[0].payload.interrupt, true);
  assert.equal(frame(1680, 0.08).actions.some(({ payload }) => payload?.type === "utterance.start"), false);
});
