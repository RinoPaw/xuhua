import assert from "node:assert/strict";
import test from "node:test";

import { BARGE_IN_PHASE } from "../src/hooks/bargeInState.js";
import { VoiceInputController } from "../src/lib/voiceInputController.js";

function makeConnection() {
  const sent = [];
  return {
    connected: true,
    sent,
    sendJson(payload) { sent.push(["json", payload]); return true; },
    sendRaw(payload) { sent.push(["raw", payload]); return true; },
  };
}

test("voice input controller owns barge-in candidate lifecycle", () => {
  const input = new VoiceInputController({ now: () => 1000 });
  assert.equal(input.bargeInPhase, BARGE_IN_PHASE.IDLE);
  assert.equal(input.confirmBargeInCandidate(), false);

  assert.equal(input.beginBargeInCandidate(4, 900), true);
  assert.equal(input.bargeInPhase, BARGE_IN_PHASE.TENTATIVE);
  assert.equal(input.beginBargeInCandidate(5, 950), false);
  assert.equal(input.confirmBargeInCandidate(), true);
  assert.equal(input.bargeInPhase, BARGE_IN_PHASE.IDLE);
});

test("voice input controller owns post-output input gate", () => {
  let now = 100;
  let frameCalls = 0;
  const input = new VoiceInputController({
    now: () => now,
    processFrame() {
      frameCalls += 1;
      return { actions: [], spectrum: null, started: null, nextStatus: null };
    },
  });

  assert.equal(input.blockFor(450), 550);
  assert.equal(input.blockedUntil, 550);
  input.unblock();
  assert.equal(input.blockedUntil, 0);

  now = 200;
  input.process(new Float32Array([0]), 48000);
  assert.equal(frameCalls, 1);
});

test("voice input controller routes frame actions and semantic input transitions", () => {
  const connection = makeConnection();
  const transitions = [];
  const spectra = [];
  const input = new VoiceInputController({
    now: () => 1234,
    processFrame(state, options) {
      assert.equal(options.now, 1234);
      assert.equal(options.transportReady, true);
      assert.equal(options.playbackActive, false);
      assert.equal(options.agentBusy, true);
      state.utteranceStartedAt = 1200;
      return {
        actions: [
          { kind: "json", payload: { type: "utterance.start" } },
          { kind: "binary", payload: "pcm" },
        ],
        spectrum: [1, 2],
        started: { utteranceId: 7, shouldInterrupt: true },
        nextStatus: null,
      };
    },
  });

  input.process(new Float32Array([0.1]), 48000, {
    connection,
    output: { pipelineActive: false, playing: false },
    assistantPending: true,
    onSpectrum: (value) => spectra.push(value),
    onSpeaking: () => transitions.push("speaking"),
    onTranscribing: () => transitions.push("transcribing"),
  });

  assert.deepEqual(connection.sent, [
    ["json", { type: "utterance.start" }],
    ["raw", "pcm"],
  ]);
  assert.deepEqual(spectra, [[1, 2]]);
  assert.deepEqual(transitions, []);
  assert.equal(input.bargeInPhase, BARGE_IN_PHASE.TENTATIVE);
  assert.equal(input.bargeIn.utteranceId, 7);
  assert.equal(input.bargeIn.startedAt, 1200);
});

test("voice input controller emits speaking and transcribing phases", () => {
  const connection = makeConnection();
  const phases = [];
  const results = [
    {
      actions: [{ kind: "json", payload: { type: "utterance.start" } }],
      spectrum: null,
      started: { utteranceId: 1, shouldInterrupt: false },
      nextStatus: "user_speaking",
    },
    {
      actions: [{ kind: "json", payload: { type: "utterance.end" } }],
      spectrum: null,
      started: null,
      nextStatus: "transcribing",
    },
  ];
  const input = new VoiceInputController({ processFrame: () => results.shift() });
  const options = {
    connection,
    output: {},
    onSpeaking: () => phases.push("speaking"),
    onTranscribing: () => phases.push("transcribing"),
  };

  input.process(new Float32Array([0]), 48000, options);
  input.process(new Float32Array([0]), 48000, options);
  assert.deepEqual(phases, ["speaking", "transcribing"]);
});
