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
