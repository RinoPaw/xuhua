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

test("scheduler terminal clears controller turn state", () => {
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
  harness.options.onPlayingChange(true);
  assert.equal(controller.playing, true);
  assert.equal(controller.traceId, "trace-terminal");
  harness.options.onTerminal({ failed: false });
  assert.equal(controller.pipelineActive, false);
  assert.equal(controller.playing, false);
  assert.equal(controller.traceId, "");
  assert.equal(controller.locale, "zh-CN");
  assert.deepEqual(playing, [true]);
  assert.deepEqual(terminal, [{ failed: false }]);
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
