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



test("cross-service latency line correlates connection, ASR, assistant, and TTS", () => {
  let current = 1000;
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => current,
    log: { info: (line) => lines.push(line) },
  });
  trace.markSpeechEnd(950);
  current = 1100;
  trace.markTranscript({ connection_id: "conn-1", utterance_id: 42 });
  current = 1300;
  trace.markFirstDelta({ connection_id: "conn-1", turn_id: "turn-2" });
  current = 1340;
  trace.markTtsRequest();
  current = 1400;
  trace.markFirstAudio();
  current = 1450;
  trace.markPlaying("tts-3");
  assert.match(lines[0], /connection=conn-1 utterance=42 turn=turn-2 tts_trace=tts-3/);
  trace.markSpeechEnd(1500);
  assert.equal(trace.context.turnId, "");
  assert.equal(trace.context.utteranceId, null);
});

test("latency correlation does not log transcript content", () => {
  const lines = [];
  let current = 200;
  const trace = new VoiceLatencyTrace({
    now: () => current,
    log: { info: (line) => lines.push(line) },
  });
  trace.markSpeechEnd(100);
  current = 250;
  trace.markTranscript({
    connection_id: "conn-safe",
    utterance_id: 3,
    text: "敏感转写内容",
  });
  current = 280;
  trace.markFirstDelta({ turn_id: "turn-safe", text: "敏感回答内容" });
  current = 320;
  trace.markPlaying("clip");
  assert.equal(lines.length, 1);
  assert.doesNotMatch(lines[0], /敏感转写内容|敏感回答内容/);
});
