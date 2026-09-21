import assert from "node:assert/strict";
import test from "node:test";

import { TtsScheduler } from "../src/lib/ttsScheduler.js";

class FakeAudio extends EventTarget {
  constructor(url) {
    super();
    this.src = url;
    this.preload = "";
  }

  play() { return Promise.resolve(); }
  pause() {}
  load() {}
  removeAttribute() {}
  fail() { this.dispatchEvent(new Event("error")); }
}

test("network TTS fallback preserves the resolved speech locale", () => {
  const audio = new FakeAudio("/api/tts/private-token");
  const timers = [];
  let fallbackOptions = null;
  const scheduler = new TtsScheduler({
    prepareSource: () => "/api/tts/private-token",
    createAudio: () => audio,
    scheduleRetry: (callback) => {
      timers.push(callback);
      return callback;
    },
    cancelRetry: () => {},
    fallbackSpeak: (_text, options) => {
      fallbackOptions = options;
      return () => {};
    },
  });

  scheduler.begin();
  scheduler.enqueue("粤剧历史悠久。", { locale: "yue-HK" });
  scheduler.complete();

  audio.fail();
  timers.shift()();
  audio.fail();
  timers.shift()();
  audio.fail();

  assert.equal(fallbackOptions?.locale, "yue-HK");
});
