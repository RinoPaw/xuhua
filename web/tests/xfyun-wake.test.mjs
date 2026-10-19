import assert from "node:assert/strict";
import test from "node:test";
import { SharedVoiceMedia } from "../src/lib/sharedVoiceMedia.js";
import { XfyunWakeWordDetector } from "../src/lib/xfyunWakeWordDetector.js";
import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";
import { PersonaVoiceGate } from "../src/lib/personaVoiceGate.js";
import { VoiceOutputController } from "../src/lib/voiceOutput.js";
import { TtsScheduler } from "../src/lib/ttsScheduler.js";
import { createVoiceMachineState, reduceVoiceMachine } from "../src/hooks/voiceState.js";

const tick = async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); };
const log = { info() {}, error() {} };

function media() {
  return { requests: 0, stops: 0,
    async requestStream() { this.requests++; this.stream = {}; return this.stream; },
    async attachProcessor(callback) { this.callback = callback; return { state: "running" }; },
    stop() { this.stops++; this.stream = null; },
  };
}

test("wake and conversation leases share one capture; ending a turn preserves standby capture", async () => {
  const source = media();
  const hub = new SharedVoiceMedia(source);
  const standby = hub.createLease(), voice = hub.createLease();
  let wakeFrames = 0, voiceFrames = 0;
  await standby.requestStream();
  await standby.attachProcessor(() => wakeFrames++);
  await voice.requestStream();
  await voice.attachProcessor(() => voiceFrames++);
  source.callback(new Float32Array(320), 16000);
  voice.stop();
  source.callback(new Float32Array(320), 16000);
  assert.equal(source.requests, 1);
  assert.equal(source.stops, 0);
  assert.deepEqual([wakeFrames, voiceFrames], [2, 1]);
  standby.stop();
  assert.equal(source.stops, 1);
});

test("a cancelled permission request cannot release a new capture owned by the same lease", async () => {
  const pending = [];
  const source = media();
  source.requestStream = () => new Promise(resolve => pending.push(resolve));
  const hub = new SharedVoiceMedia(source), lease = hub.createLease();
  const first = lease.requestStream();
  lease.stop();
  const second = lease.requestStream();
  pending[0]({ old: true });
  await assert.rejects(first, /stale/u);
  pending[1]({ current: true });
  assert.deepEqual(await second, { current: true });
  assert.equal(hub.owners.has(lease), true);
  lease.stop();
});

test("cloud detector rejects stale/duplicate wake and trims keyword audio before handoff", async () => {
  const source = media(), sockets = [];
  class Socket {
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; }
    message(value) { this.onmessage?.({ data: JSON.stringify(value) }); }
  }
  const detector = new XfyunWakeWordDetector({ hub: new SharedVoiceMedia(source), WebSocketImpl: Socket });
  let wakes = 0;
  const start = detector.start(() => wakes++);
  await tick();
  const socket = sockets[0];
  socket.message({ type: "ready", stream_id: "first" });
  assert.equal(await start, true);
  source.callback(new Float32Array(1601).fill(.25), 16000);
  socket.message({ type: "wake", keyword: "叙华", stream_id: "old", end_sample: 800 });
  assert.equal(wakes, 0);
  socket.message({ type: "wake", keyword: "叙华", stream_id: "first", end_sample: 800 });
  socket.message({ type: "wake", keyword: "叙华", stream_id: "first", end_sample: 800 });
  assert.equal(wakes, 1);
  source.callback(new Float32Array(320).fill(.5), 16000);
  let replayed = 0;
  detector.finishHandoff(samples => { replayed += samples.length; });
  assert.equal(replayed, 1120);
  const resumed = detector.start(() => wakes++);
  await tick();
  assert.equal(JSON.parse(socket.sent.at(-1)).type, "resume");
  socket.message({ type: "ready", stream_id: "second" });
  assert.equal(await resumed, true);
  assert.equal(source.requests, 1);
  detector.stop();
  assert.equal(source.stops, 1);
});

test("stopping while the cloud handshake is pending settles startup and closes capture", async () => {
  const source = media();
  class Socket { constructor() { this.readyState = 0; } close() { this.readyState = 3; } }
  const detector = new XfyunWakeWordDetector({ hub: new SharedVoiceMedia(source), WebSocketImpl: Socket });
  const start = detector.start(() => assert.fail("stale wake"));
  await tick();
  detector.stop();
  assert.equal(await start, false);
  assert.equal(source.stops, 1);
});

test("two cloud wake/ack/sleep cycles play one local acknowledgement and never send the old wake command", async () => {
  const sent = [], audios = [], metrics = [];
  let machine = createVoiceMachineState(), sleep;
  const detector = { remote: true, starts: 0,
    async start(callback) { this.callback = callback; this.starts++; return true; },
    finishHandoff(consume) { consume(new Float32Array(320), 16000); },
    stop() {}, dispose() {},
  };
  const connection = { connected: false,
    async start(path, handlers) { this.connected = true; handlers.onOpen(); return true; },
    sendJson(value) { sent.push(value); return true; }, sendRaw() { return true; },
    stop() { this.connected = false; },
  };
  class Audio extends EventTarget {
    play() { return Promise.resolve(); } pause() {} load() {} removeAttribute() {}
    emit(type) { this.dispatchEvent(new Event(type)); }
  }
  const session = new PersonaBrowserVoiceSession({ wakeDetector: detector, connection, log,
    gate: new PersonaVoiceGate({ log, setTimeoutFn(callback) { sleep = callback; return 1; }, clearTimeoutFn() {} }),
    getMachine: () => machine,
    dispatchVoice(action) { machine = reduceVoiceMachine(machine, action); },
    dispatchMany(actions) { for (const action of actions) machine = reduceVoiceMachine(machine, action); },
    createOutput: options => new VoiceOutputController({ ...options,
      createClipCache: () => ({ prewarm: async () => "", sourceFor: async () => "/ack", dispose() {} }),
      createScheduler: callbacks => new TtsScheduler({ ...callbacks,
        prepareSource: async () => "/ack",
        createAudio() { const audio = new Audio(); audios.push(audio); return audio; },
      }),
    }),
  });
  session.reportTiming = body => metrics.push(body);
  try {
    await session.armWake();
    for (let cycle = 0; cycle < 2; cycle++) {
      assert.equal(await detector.callback("叙华", { detectedAt: performance.now(), wordEndAt: performance.now() }), true);
      await tick();
      assert.equal(audios.length, cycle + 1);
      audios.at(-1).emit("playing");
      session.latency.markSpeechEnd(performance.now());
      audios.at(-1).emit("ended");
      await tick();
      assert.equal(session.latency.finished, false, "the acknowledgement must not finish a question trace");
      assert.equal(session.input.blockedUntil, 0, "acknowledgement must not suppress the beginning of a question");
      assert.equal(typeof sleep, "function", "no-question timeout must be armed");
      sleep();
      await tick();
      assert.equal(connection.connected, false);
      assert.equal(session.wakeListening, true);
    }
    assert.equal(sent.some(item => item.type === "wake"), false);
    assert.equal(metrics.filter(item => item.kind === "wake" && item.played).length, 2);
    session.pauseMicrophone();
    assert.equal(session.autoWakeEnabled, false);
  } finally { session.destroy(); }
});
