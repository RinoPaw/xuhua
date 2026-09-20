import assert from "node:assert/strict";
import test from "node:test";

import { VoiceOutputController, normalizeSpeechText } from "../src/lib/voiceOutput.js";

function makeSchedulerHarness() {
  const calls = [];
  let options;
  const scheduler = {
    segmentCount: 0,
    hasSegments: false,
    begin() { calls.push(["begin"]); return 7; },
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

test("voice output snapshots locale and queues first sentence before completion", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    websocketPath: "/api/voice",
    getRecognitionContext: () => ({ localeHint: "zh-CN" }),
    createScheduler: (options) => harness.createScheduler(options),
    createTraceId: () => "trace-1",
  });

  assert.equal(controller.begin("en-US"), 7);
  assert.equal(controller.pipelineActive, true);
  assert.equal(controller.locale, "en-US");
  controller.append("First sentence. Second", "zh-CN");
  assert.equal(harness.calls[1][0], "enqueue");
  assert.equal(harness.calls[1][1], "First sentence.");
  assert.match(harness.calls[1][2].url, /trace_id=trace-1/u);
  assert.match(harness.calls[1][2].url, /locale=en-US/u);
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
});

test("scheduler callbacks update controller lifecycle", () => {
  const harness = makeSchedulerHarness();
  const playing = [];
  const terminal = [];
  const controller = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
    onPlayingChange: (value) => playing.push(value),
    onTerminal: (value) => terminal.push(value),
  });
  controller.begin();
  harness.options.onPlayingChange(true);
  assert.equal(controller.playing, true);
  harness.options.onTerminal({ failed: false });
  assert.equal(controller.pipelineActive, false);
  assert.equal(controller.playing, false);
  assert.deepEqual(playing, [true]);
  assert.deepEqual(terminal, [{ failed: false }]);
});

test("stop clears pipeline state and resets text plan", () => {
  const harness = makeSchedulerHarness();
  const controller = new VoiceOutputController({
    createScheduler: (options) => harness.createScheduler(options),
  });
  controller.begin();
  controller.append("未完成");
  controller.stop();
  assert.equal(controller.pipelineActive, false);
  assert.equal(controller.playing, false);
  assert.equal(harness.calls.at(-1)[0], "stop");
});
