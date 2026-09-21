import assert from "node:assert/strict";
import test from "node:test";

import { VoiceLatencyTrace } from "../src/lib/voiceLatency.js";

test("voice latency trace accounts from last speech to actual playback", () => {
  let current = 1420;
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => current,
    log: { info: (line) => lines.push(line) },
  });

  assert.equal(trace.markSpeechEnd(1000), true);
  current = 1600;
  trace.markTranscript();
  current = 2050;
  trace.markFirstDelta();
  current = 2130;
  trace.markTtsRequest();
  current = 2400;
  trace.markFirstAudio();
  current = 2435;
  const metrics = trace.markPlaying("trace-1");

  assert.deepEqual(metrics, {
    totalMs: 1435,
    eouMs: 420,
    asrFinalMs: 180,
    agentFirstDeltaMs: 450,
    firstPhraseMs: 80,
    ttsFirstAudioMs: 270,
    audioStartMs: 35,
  });
  assert.match(lines[0], /total=1435\.0ms/);
  assert.match(lines[0], /eou=420\.0ms/);
  assert.equal(trace.markPlaying("trace-1"), null);
});

test("text-only playback does not invent a voice latency trace", () => {
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => 1000,
    log: { info: (line) => lines.push(line) },
  });

  trace.markFirstDelta();
  trace.markTtsRequest();
  assert.equal(trace.markPlaying("text-turn"), null);
  assert.deepEqual(lines, []);
});
