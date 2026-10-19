import assert from "node:assert/strict";
import test from "node:test";
import { createVoiceMachineState, deriveVoiceStatus, reduceVoiceMachine } from "../src/hooks/voiceState.js";
import { BrowserVoiceSession } from "../src/lib/browserVoiceSession.js";
import { VoiceOutputController } from "../src/lib/voiceOutput.js";
import { TtsClipCache } from "../src/lib/ttsClipCache.js";
import { TtsScheduler } from "../src/lib/ttsScheduler.js";

const tick = () => new Promise(resolve => setImmediate(resolve));

test("chat mic unlocks audio and repeated name calls use one cached clip while staying connected", async () => {
  const audios = [], fetched = [], transcripts = [], sent = [];
  let machine = createVoiceMachineState();
  class Audio extends EventTarget {
    play() { this.playCalls = (this.playCalls || 0) + 1; return Promise.resolve(); }
    pause() {} load() {} removeAttribute() {}
    emit(type) { this.dispatchEvent(new Event(type)); }
  }
  const connection = {
    connected: false,
    async start(_path, handlers) { this.connected = true; handlers.onOpen(); return true; },
    stop() { this.connected = false; },
    sendJson(value) { sent.push(value); return this.connected; },
    sendRaw() { return this.connected; },
    pauseInput() { return true; },
    async resumeInput() { return true; },
  };
  const session = new BrowserVoiceSession({
    connection,
    getMachine: () => machine,
    dispatchVoice(action) { machine = reduceVoiceMachine(machine, action); },
    dispatchMany(actions) { for (const action of actions) machine = reduceVoiceMachine(machine, action); },
    getCallbacks: () => ({ onAssistantTranscript(text, meta) { transcripts.push([text, meta.done]); } }),
    createOutput: options => new VoiceOutputController({ ...options,
      createClipCache: () => new TtsClipCache({
        async fetchImpl(url) { fetched.push(url); return { ok: true, blob: async () => new Blob(["mp3"]) }; },
        createObjectURL: () => "blob:cached-xiaolu-ack",
        revokeObjectURL() {},
      }),
      createScheduler: callbacks => new TtsScheduler({ ...callbacks,
        createAudio() { const audio = new Audio(); audios.push(audio); return audio; },
      }),
    }),
    log: { info() {}, warn() {} },
  });
  try {
    session.unlockOutput();
    assert.equal(audios.length, 1, "play must be called inside the microphone button gesture");
    assert.equal(audios[0].playCalls, 1);
    await tick();
    assert.equal(await session.start(), true);
    session.input.unblock();
    for (let id = 1; id <= 2; id++) {
      assert.equal(session.routeServerEvent({ type: "user.transcript", utterance_id: id, text: "叙华" }), true);
      for (const type of ["assistant.delta", "assistant.done"]) {
        assert.equal(session.routeServerEvent({ type, turn_id: `ack-${id}`, text: "我在。",
          locale: "zh-CN", acknowledgement: true }), true);
      }
      await tick();
      const audio = audios.at(-1);
      assert.equal(audio.src, "blob:cached-xiaolu-ack");
      if (id === 1) assert.equal(audio.muted, false, "the unlocked element must play audibly");
      audio.emit("playing");
      audio.emit("ended");
      assert.equal(deriveVoiceStatus(machine), "listening");
      assert.equal(session.input.blockedUntil, 0, "the next question must not be suppressed after 我在");
      assert.equal(session.microphoneEnabled, true);
      assert.equal(connection.connected, true);
    }
    assert.equal(audios.length, 2, "first acknowledgement reuses the gesture-unlocked element");
    assert.deepEqual(fetched, ["/assets/audio/ack-wozai-x4-yezi.mp3"]);
    assert.deepEqual(transcripts.filter(([, done]) => done), [["我在。", true], ["我在。", true]]);
    assert.equal(sent.some(value => value.type === "wake"), false, "continuous chat needs no separate wake command");

    // A question can replace an acknowledgement that is still playing.
    session.routeServerEvent({ type: "user.transcript", utterance_id: 3, text: "叙华" });
    for (const type of ["assistant.delta", "assistant.done"]) {
      session.routeServerEvent({ type, turn_id: "interrupted-ack", text: "我在。",
        locale: "zh-CN", acknowledgement: true });
    }
    await tick();
    const oldAck = audios.at(-1);
    oldAck.emit("playing");
    session.routeServerEvent({ type: "user.transcript", utterance_id: 4, text: "叙华，介绍一下剪纸" });
    assert.equal(deriveVoiceStatus(machine), "thinking");
    for (const type of ["assistant.delta", "assistant.done"]) {
      session.routeServerEvent({ type, turn_id: "answer", text: "我在。", locale: "zh-CN" });
    }
    await tick();
    oldAck.emit("ended");
    assert.equal(session.output.pipelineActive, true, "a stale acknowledgement cannot clear the new answer");
    audios.at(-1).emit("playing");
    audios.at(-1).emit("ended");
    assert.ok(session.input.blockedUntil > 0, "ordinary answers retain their existing echo cooldown");
    assert.equal(session.pauseMicrophone(), true);
    assert.equal(connection.connected, true);
    assert.equal(session.microphoneEnabled, false);
    session.unlockOutput();
    assert.equal(await session.resumeMicrophone(), true);
  } finally { session.destroy(); }
});
