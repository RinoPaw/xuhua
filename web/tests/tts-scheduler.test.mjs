import test from "node:test";
import assert from "node:assert/strict";
import { TtsScheduler } from "../src/lib/ttsScheduler.js";

class FakeAudio extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.src = url;
    this.currentTime = 0;
    this.preload = "";
    this.playCalls = 0;
    this.pauseCalls = 0;
    this.loadCalls = 0;
  }

  play() { this.playCalls += 1; return Promise.resolve(); }
  pause() { this.pauseCalls += 1; }
  load() { this.loadCalls += 1; }
  emit(type) { this.dispatchEvent(new Event(type)); }
}

function makeScheduler() {
  const audios = [];
  const events = [];
  const terminals = [];
  const playingChanges = [];
  const scheduler = new TtsScheduler({
    prepareSource: ({ segment }) => `/tts/${segment}`,
    createAudio: (url) => {
      const audio = new FakeAudio(url);
      audios.push(audio);
      return audio;
    },
    onEvent: (event) => events.push(event),
    onPlayingChange: (playing) => playingChanges.push(playing),
    onTerminal: (event) => terminals.push(event),
  });
  return { scheduler, audios, events, terminals, playingChanges };
}

test("preloads the second segment before the first segment ends", async () => {
  const { scheduler, audios, events, terminals, playingChanges } = makeScheduler();
  scheduler.begin();

  assert.equal(scheduler.enqueue("第一句。", { reason: "first_sentence" }), true);
  assert.equal(audios.length, 1);
  assert.equal(audios[0].playCalls, 1);
  audios[0].emit("loadeddata");
  audios[0].emit("playing");

  assert.equal(scheduler.enqueue("剩余内容。", { reason: "text_complete" }), true);
  assert.equal(audios.length, 2);
  assert.equal(audios[1].loadCalls, 1);
  assert.equal(audios[1].playCalls, 0);

  scheduler.complete();
  audios[0].emit("ended");
  assert.equal(audios[1].playCalls, 1);
  audios[1].emit("loadeddata");
  audios[1].emit("playing");
  audios[1].emit("ended");
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(scheduler.isPlaying, false);
  assert.equal(scheduler.segmentCount, 0);
  assert.equal(audios[0].src, "");
  assert.equal(audios[1].src, "");
  assert.deepEqual(playingChanges, [true, false, true, false]);
  assert.equal(terminals.length, 1);
  assert.equal(terminals[0].failed, false);
  assert.deepEqual(events.filter((event) => event.type === "request.start").map((event) => event.segment), [0, 1]);
  assert.deepEqual(events.filter((event) => event.type === "first_audio_chunk").map((event) => event.segment), [0, 1]);
});

test("tentative barge-in pauses and resumes the same network audio", () => {
  const { scheduler, audios, events, playingChanges } = makeScheduler();
  scheduler.begin();
  scheduler.enqueue("播报内容。");
  audios[0].currentTime = 4.2;
  audios[0].emit("playing");

  assert.equal(scheduler.pauseTentative(), true);
  assert.equal(scheduler.isTentativePaused, true);
  assert.equal(scheduler.isPlaying, false);
  assert.equal(audios[0].pauseCalls, 1);
  assert.equal(audios[0].currentTime, 4.2);

  assert.equal(scheduler.resumeTentative(), true);
  assert.equal(audios[0].playCalls, 2);
  audios[0].emit("playing");
  assert.equal(scheduler.isTentativePaused, false);
  assert.equal(scheduler.isPlaying, true);
  assert.deepEqual(playingChanges, [true, false, true]);
  assert.equal(events.some((event) => event.type === "playback.pause_tentative"), true);
  assert.equal(events.some((event) => event.type === "playback.resume_tentative"), true);
});

test("stop releases current and prefetched audio and ignores late callbacks", () => {
  const { scheduler, audios, terminals, playingChanges } = makeScheduler();
  scheduler.begin();
  scheduler.enqueue("第一句。");
  audios[0].emit("playing");
  scheduler.enqueue("剩余内容。");

  scheduler.stop();
  assert.equal(scheduler.isPlaying, false);
  assert.equal(audios[0].pauseCalls, 1);
  assert.equal(audios[0].loadCalls, 1);
  assert.equal(audios[1].pauseCalls, 1);
  assert.equal(audios[1].loadCalls, 2);

  audios[0].emit("playing");
  audios[0].emit("ended");
  audios[1].emit("playing");
  audios[1].emit("ended");
  assert.equal(scheduler.isPlaying, false);
  assert.deepEqual(playingChanges, [true, false]);
  assert.equal(terminals.length, 0);
});

test("a new generation isolates stale audio and never creates a third segment", () => {
  const { scheduler, audios, terminals } = makeScheduler();
  scheduler.begin();
  scheduler.enqueue("旧第一句。");
  const oldAudio = audios[0];
  scheduler.stop();

  scheduler.begin();
  scheduler.enqueue("新第一句。");
  scheduler.enqueue("新剩余内容。");
  assert.equal(scheduler.enqueue("不应出现。"), false);

  oldAudio.emit("playing");
  oldAudio.emit("ended");
  assert.equal(scheduler.isPlaying, false);
  assert.equal(audios[1].playCalls, 1);
  assert.equal(audios[2].playCalls, 0);
  scheduler.complete();
  audios[1].emit("ended");
  audios[2].emit("ended");
  assert.equal(terminals.length, 1);
});

test("completion with no generated segment terminates cleanly", () => {
  const { scheduler, terminals } = makeScheduler();
  scheduler.begin();
  assert.equal(scheduler.complete(), true);
  assert.equal(terminals.length, 1);
  assert.equal(terminals[0].failed, false);
});

test("stop aborts pending source preparation and stale resolution cannot create audio", async () => {
  const audios = [];
  let resolveSource;
  let sourceSignal = null;
  const scheduler = new TtsScheduler({
    prepareSource: ({ signal }) => {
      sourceSignal = signal;
      return new Promise((resolve) => { resolveSource = resolve; });
    },
    createAudio: (url) => {
      const audio = new FakeAudio(url);
      audios.push(audio);
      return audio;
    },
  });

  scheduler.begin();
  assert.equal(scheduler.enqueue("不会复活。", { locale: "zh-CN" }), true);
  assert.equal(audios.length, 0);
  assert.equal(sourceSignal?.aborted, false);

  scheduler.stop();
  assert.equal(sourceSignal?.aborted, true);
  resolveSource("/api/tts/stale-token");
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(audios.length, 0);
  assert.equal(scheduler.segmentCount, 0);
});

test("second source may resolve first but playback order remains stable", async () => {
  const resolvers = [];
  const audios = [];
  const scheduler = new TtsScheduler({
    prepareSource: ({ segment }) => new Promise((resolve) => { resolvers[segment] = resolve; }),
    createAudio: (url) => {
      const audio = new FakeAudio(url);
      audios.push(audio);
      return audio;
    },
  });

  scheduler.begin();
  scheduler.enqueue("第一句。", { locale: "zh-CN" });
  scheduler.enqueue("第二句。", { locale: "zh-CN" });
  scheduler.complete();

  resolvers[1]("/api/tts/token-1");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(audios.length, 1);
  assert.equal(audios[0].url, "/api/tts/token-1");
  assert.equal(audios[0].playCalls, 0);
  assert.equal(audios[0].loadCalls, 1);

  resolvers[0]("/api/tts/token-0");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(audios.length, 2);
  const first = audios.find((audio) => audio.url.endsWith("token-0"));
  const second = audios.find((audio) => audio.url.endsWith("token-1"));
  assert.equal(first.playCalls, 1);
  assert.equal(second.playCalls, 0);

  first.emit("ended");
  assert.equal(second.playCalls, 1);
  second.emit("ended");
  assert.equal(scheduler.segmentCount, 0);
});

test("network TTS fails closed after two retries instead of switching engines", () => {
  const audio = new FakeAudio("/tts/0");
  const events = [];
  const terminals = [];
  const timers = [];

  const scheduler = new TtsScheduler({
    prepareSource: () => "/tts/0",
    createAudio: () => audio,
    onEvent: (event) => events.push(event),
    onTerminal: (event) => terminals.push(event),
    scheduleRetry: (callback) => {
      timers.push(callback);
      return callback;
    },
    cancelRetry: () => {},
  });

  scheduler.begin();
  scheduler.enqueue("网络不稳时不要偷偷换一个声音。");
  scheduler.complete();

  audio.emit("error");
  assert.equal(events.filter((event) => event.type === "request.retry").length, 1);
  timers.shift()();
  assert.match(audio.src, /tts_retry=1/);

  audio.emit("error");
  assert.equal(events.filter((event) => event.type === "request.retry").length, 2);
  timers.shift()();
  assert.match(audio.src, /tts_retry=2/);

  audio.emit("error");
  assert.equal(events.filter((event) => event.type === "request.failed").length, 1);
  assert.equal(events.some((event) => event.type.startsWith("fallback")), false);
  assert.equal(scheduler.isPlaying, false);
  assert.equal(terminals.length, 1);
  assert.equal(terminals[0].failed, true);
});


test("old audio ending cannot advance a new generation during synchronous replacement", () => {
  const audios = [];
  const emitted = [];
  let scheduler;
  let replacementGeneration = 0;
  scheduler = new TtsScheduler({
    prepareSource: ({ text }) => `/tts/${text}`,
    createAudio: (url) => {
      const audio = new FakeAudio(url);
      audios.push(audio);
      return audio;
    },
    onEvent: (event) => emitted.push(event),
    onPlayingChange: (playing) => {
      if (!playing && !replacementGeneration) {
        replacementGeneration = scheduler.begin();
        scheduler.enqueue("新的第一段");
      }
    },
  });
  scheduler.begin();
  scheduler.enqueue("旧第一段");
  scheduler.enqueue("旧第二段");
  const old = audios[0];
  old.emit("playing");
  old.emit("ended");

  assert.equal(replacementGeneration > 0, true);
  assert.equal(audios.length, 3);
  assert.equal(audios[1].playCalls, 0);
  assert.equal(audios[2].playCalls, 1);
  assert.equal(scheduler.segmentCount, 1);
  assert.equal(emitted.filter((event) => event.type === "segment.complete").length, 0);
});

test("cancel from request-start callback avoids a needless TTS ticket", () => {
  let scheduler;
  let prepared = 0;
  scheduler = new TtsScheduler({
    prepareSource: () => { prepared += 1; return "/tts/old"; },
    onEvent: (event) => {
      if (event.type === "request.start") scheduler.stop();
    },
  });
  scheduler.begin();
  assert.equal(scheduler.enqueue("在请求前就取消"), false);
  assert.equal(prepared, 0);
});

test("retry observation cancellation does not schedule an obsolete timer", () => {
  const retries = [];
  let scheduler;
  scheduler = new TtsScheduler({
    prepareSource: () => "/tts/error",
    createAudio: (url) => new FakeAudio(url),
    scheduleRetry: (callback) => { retries.push(callback); return callback; },
    onEvent: (event) => {
      if (event.type === "request.retry") scheduler.stop();
    },
  });
  scheduler.begin();
  scheduler.enqueue("被取消的重试");
  const audio = scheduler.entries.get(0).audio;
  audio.emit("error");
  assert.equal(retries.length, 0);
  assert.equal(scheduler.segmentCount, 0);
});

test("playing callback replacement cannot publish a stale playing event", () => {
  let scheduler;
  const emitted = [];
  const audio = new FakeAudio("/tts/old");
  scheduler = new TtsScheduler({
    prepareSource: () => "/tts/old",
    createAudio: () => audio,
    onEvent: (event) => emitted.push(event),
    onPlayingChange: (playing) => {
      if (playing) scheduler.begin();
    },
  });
  scheduler.begin();
  scheduler.enqueue("旧段");
  audio.emit("playing");
  assert.equal(scheduler.segmentCount, 0);
  assert.equal(emitted.filter((e) => e.type === "playing").length, 0);
});

test("scheduler attaches immutable trace IDs to deferred source preparations", async () => {
  const preparations = [];
  let resolveOld;
  const scheduler = new TtsScheduler({
    prepareSource: (meta) => {
      preparations.push(meta);
      return new Promise((resolve) => {
        if (meta.traceId === "old") resolveOld = resolve;
      });
    },
  });
  scheduler.begin();
  scheduler.enqueue("旧段", { traceId: "old" });
  const originalSignal = preparations[0].signal;
  scheduler.begin();
  scheduler.enqueue("新段", { traceId: "new" });
  assert.equal(originalSignal.aborted, true);
  assert.equal(preparations[0].traceId, "old");
  assert.equal(preparations[1].traceId, "new");
  resolveOld("/tts/obsolete");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(scheduler.entries.get(0).traceId, "new");
  scheduler.stop();
});
