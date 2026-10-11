import assert from "node:assert/strict";
import test from "node:test";

import { VoiceOutputController, normalizeSpeechText } from "../src/lib/voiceOutput.js";

function makeSchedulerHarness() {
  const calls = [];
  let options;
  const scheduler = {
    segmentCount: 0,
    hasSegments: false,
    generation: 6,
    begin() { calls.push(["begin"]); this.generation += 1; return this.generation; },
    stop() { calls.push(["stop"]); return true; },
    enqueue(text, meta) {
      calls.push(["enqueue", text, meta]);
      this.segmentCount += 1;
      this.hasSegments = true;
      return true;
    },
    complete() { calls.push(["complete"]); return true; },
  };
  return {
    calls,
    scheduler,
    createScheduler(value) {
      options = value;
      return scheduler;
    },
    get options() { return options; },
  };
}

test("speech normalization removes markdown without dropping semantic operators", () => {
  assert.equal(
    normalizeSpeechText("### 温度\n\n**最低** -2°C，且 3 > 2。\n- 列表项\n`汴绣`"),
    "温度\n\n最低 -2°C，且 3 > 2。\n列表项\n汴绣",
  );
});

test("voice output snapshots locale and queues first phrase before completion", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    websocketPath: "/api/voice",
    getRecognitionContext: () => ({ localeHint: "zh-CN" }),
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "trace-1",
  });

  assert.equal(controller.begin("zh-CN"), 7);
  assert.equal(controller.pipelineActive, true);
  assert.equal(controller.locale, "zh-CN");
  controller.append("如果你第一次认真看一幅传统汴绣作品，可以先留意针脚方向", "zh-CN");
  assert.equal(harness.calls[1][0], "enqueue");
  assert.equal(harness.calls[1][1], "如果你第一次认真看一幅传统汴绣作品，");
  assert.deepEqual(harness.calls[1][2], {
    reason: "first_phrase",
    locale: "zh-CN",
    traceId: "trace-1",
  });
  controller.finish("", "zh-CN");
  assert.equal(harness.calls.at(-1)[0], "complete");
});

test("finish uses fallback when no segment was produced", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "trace-2",
  });
  controller.finish("短回答", "zh-CN");
  const enqueue = harness.calls.find((call) => call[0] === "enqueue");
  assert.equal(enqueue[1], "短回答");
  assert.equal(enqueue[2].reason, "text_complete");
  assert.equal(enqueue[2].locale, "zh-CN");
  assert.equal("url" in enqueue[2], false);
});

test("scheduler terminal preserves failure metadata and clears controller turn state", () => {
  const harness = makeSchedulerHarness();
  const playing = [];
  const terminal = [];
  const controller = new VoiceOutputController({
    getRecognitionContext: () => ({ localeHint: "en-US" }),
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "trace-terminal",
    onPlayingChange: (value) => playing.push(value),
    onTerminal: (value) => terminal.push(value),
  });
  controller.begin();
  controller.append("Pending text");
  harness.options.onPlayingChange(true, 7);
  assert.equal(controller.playing, true);
  assert.equal(controller.traceId, "trace-terminal");
  const terminalResult = {
    failed: true,
    reason: "tts_provider_unavailable",
    generation: 7,
  };
  harness.options.onTerminal(terminalResult);
  assert.equal(controller.pipelineActive, false);
  assert.equal(controller.playing, false);
  assert.equal(controller.traceId, "");
  assert.equal(controller.locale, "zh-CN");
  assert.deepEqual(playing, [true]);
  assert.deepEqual(terminal, [terminalResult]);
});

test("stop clears pipeline state and resets text plan", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "trace-stop",
  });
  controller.begin();
  controller.append("未完成");
  controller.stop();
  assert.equal(controller.pipelineActive, false);
  assert.equal(controller.playing, false);
  assert.equal(controller.traceId, "");
  assert.equal(harness.calls.at(-1)[0], "stop");
});


test("late TTS callbacks cannot reset or contaminate the next output generation", () => {
  const harness = makeSchedulerHarness();
  const events = [];
  const playingChanges = [];
  const terminals = [];
  let sequence = 0;
  const output = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => `tts-trace-${++sequence}`,
    onEvent: (event) => events.push(event),
    onPlayingChange: (playing) => playingChanges.push(playing),
    onTerminal: (result) => terminals.push(result),
  });
  assert.equal(output.begin(), 7);
  assert.equal(output.begin(), 8);
  output.append("新一轮回答", "zh-CN");
  assert.equal(output.traceId, "tts-trace-2");

  harness.options.onPlayingChange(true, 7);
  harness.options.onEvent({ type: "playing", generation: 7 });
  harness.options.onTerminal({ generation: 7, failed: true, reason: "old_failed" });
  assert.equal(output.pipelineActive, true);
  assert.equal(output.traceId, "tts-trace-2");
  assert.equal(output.playing, false);
  assert.deepEqual(playingChanges, []);
  assert.deepEqual(events, []);
  assert.deepEqual(terminals, []);

  harness.options.onPlayingChange(true, 8);
  harness.options.onEvent({ type: "playing", generation: 8 });
  assert.equal(output.playing, true);
  assert.deepEqual(playingChanges, [true]);
  assert.equal(events.length, 1);
  harness.options.onTerminal({ generation: 8, failed: false });
  assert.equal(output.pipelineActive, false);
  assert.equal(output.traceId, "");
  assert.equal(terminals.length, 1);
  harness.options.onTerminal({ generation: 7, failed: true });
  assert.equal(terminals.length, 1);
});

test("cancelled cache wait does not issue a new TTS ticket", async () => {
  let releaseCache;
  const output = new VoiceOutputController({
    createClipCache: () => ({
      sourceFor: () => new Promise((resolve) => { releaseCache = resolve; }),
      dispose() {},
    }),
  });
  const abort = new AbortController();
  const source = output.prepareSource({
    text: "已取消的旧回答", locale: "zh-CN", traceId: "old-trace",
    segment: 0, reason: "text_complete", signal: abort.signal,
  });
  abort.abort();
  releaseCache("");
  assert.equal(await source, "");
});

test("TTS scheduler receives a trace snapshot for each turn", () => {
  const harness = makeSchedulerHarness();
  let sequence = 0;
  const output = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => `trace-${++sequence}`,
  });
  output.begin();
  output.append("旧回答。");
  output.begin();
  output.append("新回答。");
  const enqueueCalls = harness.calls.filter(([name]) => name === "enqueue");
  assert.equal(enqueueCalls.length, 2);
  assert.equal(enqueueCalls[0][2].traceId, "trace-1");
  assert.equal(enqueueCalls[1][2].traceId, "trace-2");
});


test("voice output requests synthesis at an early Chinese comma before LLM completion", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "low-latency-first-phrase",
  });
  controller.begin("zh-CN");
  assert.equal(controller.append("这项技艺", "zh-CN"), true);
  assert.equal(harness.calls.filter(([type]) => type === "enqueue").length, 0);
  assert.equal(controller.append("历史悠久，", "zh-CN"), true);
  assert.deepEqual(
    harness.calls.filter(([type]) => type === "enqueue").map(([, text]) => text),
    ["这项技艺历史悠久，"],
  );
  controller.finish("这项技艺历史悠久，有着非常独特的传承背景。", "zh-CN");
  assert.equal(harness.calls.at(-1)[0], "complete");
});
