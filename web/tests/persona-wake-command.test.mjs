import assert from "node:assert/strict";
import test from "node:test";

import { PersonaBrowserVoiceSession } from "../src/lib/personaBrowserVoiceSession.js";

test("display starts the working voice transport immediately", async () => {
  const sent = [];
  const connection = {
    connected: false,
    starting: false,
    async start(_path, { onOpen }) {
      this.connected = true;
      onOpen();
      return true;
    },
    sendJson(payload) { sent.push(payload); return true; },
  };
  const session = new PersonaBrowserVoiceSession({
    connection,
    input: { reset() {}, state: { utteranceActive: false } },
    transcript: { clear() {} },
    latency: { clear() {} },
    createOutput: () => ({ prewarm() {}, pipelineActive: false }),
    getMachine: () => ({}),
    dispatchVoice() {},
    dispatchMany() {},
    getRecognitionContext: () => ({ localeHint: "zh-CN" }),
    onErrorState() {},
    onMicrophoneEnabledChange() {},
  });

  assert.equal(await session.start(), true);
  assert.equal(connection.connected, true);
  assert.equal(session.microphoneEnabled, true);
  assert.equal(sent[0].type, "context");
});

test("typed persona questions wake the gate after a successful send", () => {
  const sent = [];
  const wakes = [];
  const session = Object.create(PersonaBrowserVoiceSession.prototype);
  session.connection = { connected: true };
  session.send = (payload) => { sent.push(payload); return true; };
  session.latency = { clear() {} };
  session.transcript = { clear() {} };
  session.input = { supersedeUtterance() {} };
  session.stopSpeech = () => true;
  session.markThinking = () => {};
  session.gate = { wake(trigger) { wakes.push(trigger); } };

  assert.equal(session.sendText("皮影戏是什么？"), true);
  assert.deepEqual(sent, [{ type: "text", text: "皮影戏是什么？" }]);
  assert.deepEqual(wakes, ["文字提问"]);

  session.connection.connected = false;
  assert.equal(session.sendText("再次提问"), false);
  assert.deepEqual(wakes, ["文字提问"]);
});
