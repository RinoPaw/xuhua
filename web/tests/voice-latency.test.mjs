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



test("terminal-only assistant responses still preserve the server turn ID", () => {
  let now = 1000;
  const logs = [];
  const trace = new VoiceLatencyTrace({
    now: () => now,
    log: { info: (line) => logs.push(line) },
  });
  trace.markSpeechEnd(900);
  now = 1200;
  trace.markTranscript({ connection_id: "conn-done", utterance_id: 12 });
  assert.equal(trace.noteTurn({ turn_id: "turn-done" }), true);
  now = 1250;
  trace.markPlaying("tts-done");
  assert.match(logs[0], /connection=conn-done utterance=12 turn=turn-done/);
  assert.match(logs[0], /agent_first_delta=-/);
});


test("failed voice requests produce terminal diagnostics even without first audio", () => {
  let now = 1000;
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => now,
    log: { info: (message) => lines.push(message) },
  });
  trace.markSpeechEnd(900);
  now = 1050;
  trace.markTranscript({
    connection_id: "conn-safe", utterance_id: 8, text: "敏感问题",
  });
  now = 1150;
  trace.markFirstDelta({ turn_id: "turn-safe", text: "敏感回答" });
  now = 1250;
  assert.equal(trace.finish("failed", {
    reason: "https://internal.test/api?token=SECRET_KEY",
  }), true);
  assert.equal(trace.finish("cancelled"), false);
  assert.equal(trace.markPlaying("late-audio"), null);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /voice.outcome connection=conn-safe utterance=8 turn=turn-safe/);
  assert.match(lines[0], /result=failed reason=unknown elapsed=350.0ms/);
  assert.match(lines[0], /transcribed=true first_delta=true first_audio=false playing=false/);
  assert.doesNotMatch(lines[0], /敏感问题|敏感回答|SECRET_KEY|https:/);
});

test("cancelled, disconnected and rejected utterances retain one outcome each", () => {
  let now = 500;
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => now, log: { info: (line) => lines.push(line) },
  });
  assert.equal(trace.markSpeechEnd(420), true);
  now = 600;
  assert.equal(trace.finish("cancelled"), true);
  assert.equal(trace.finish("failed"), false);
  assert.equal(trace.markSpeechEnd(640), true);
  now = 710;
  assert.equal(trace.finish("disconnected"), true);
  assert.equal(trace.markSpeechEnd(760), true);
  now = 880;
  assert.equal(trace.finish("rejected"), true);
  assert.deepEqual(lines.map((line) => /result=([a-z]+)/u.exec(line)?.[1]), [
    "cancelled", "disconnected", "rejected",
  ]);
});

test("overlapping voice requests terminate the old trace before recording the next", () => {
  let now = 1000;
  const lines = [];
  const trace = new VoiceLatencyTrace({
    now: () => now, log: { info: (line) => lines.push(line) },
  });
  trace.markSpeechEnd(950);
  now = 1020;
  trace.markTranscript({ connection_id: "before", utterance_id: 1 });
  now = 1100;
  trace.markSpeechEnd(1080);
  assert.match(lines[0], /result=superseded/);
  assert.match(lines[0], /connection=before utterance=1/);
  assert.equal(trace.context.utteranceId, null);
  now = 1190;
  trace.markTranscript({ connection_id: "after", utterance_id: 2 });
  trace.markPlaying("trace-after");
  now = 1250;
  trace.finish("completed");
  assert.equal(lines.filter((line) => line.includes("voice.outcome")).length, 2);
  assert.match(lines.at(-1), /connection=after utterance=2/);
  assert.match(lines.at(-1), /result=completed/);
});
