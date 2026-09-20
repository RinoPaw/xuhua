import assert from "node:assert/strict";
import test from "node:test";

import { TtsScheduler, ttsLocaleFromUrl } from "../src/lib/ttsScheduler.js";

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
  assert.equal(ttsLocaleFromUrl("/api/tts?text=%E7%B2%A4%E5%89%A7&locale=yue-HK"), "yue-HK");

  const audio = new FakeAudio("/api/tts?locale=yue-HK");
  const timers = [];
  let fallbackOptions = null;
  const scheduler = new TtsScheduler({
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
  scheduler.enqueue("粤剧历史悠久。", { url: "/api/tts?locale=yue-HK" });
  scheduler.complete();

  audio.fail();
  timers.shift()();
  audio.fail();
  timers.shift()();
  audio.fail();

  assert.equal(fallbackOptions?.locale, "yue-HK");
});
