import assert from "node:assert/strict";
import test from "node:test";

import {
  isPersonaWakePhrase,
  PERSONA_RESPONSE_GRACE_MS,
  PersonaVoiceGate,
} from "../src/lib/personaVoiceGate.js";

function createLog() {
  const messages = [];
  return {
    messages,
    logger: {
      info(message) {
        messages.push(message);
      },
    },
  };
}

test("persona wake phrase must start with 叙华", () => {
  assert.equal(isPersonaWakePhrase("叙华"), true);
  assert.equal(isPersonaWakePhrase("  叙华，讲讲汴绣"), true);
  assert.equal(isPersonaWakePhrase("介绍一下叙华"), false);
  assert.equal(isPersonaWakePhrase("循环"), false);
});

test("persona gate sleeps initially and wakes only on the wake phrase", () => {
  const log = createLog();
  const gate = new PersonaVoiceGate({ log: log.logger });

  assert.equal(gate.allowAssistantResponse(), false);
  assert.equal(gate.acceptTranscript("今天天气不错"), "ignore");
  assert.equal(gate.allowAssistantResponse(), false);
  assert.equal(gate.acceptTranscript("叙华"), "wake");
  assert.equal(gate.allowAssistantResponse(), true);
  assert.deepEqual(log.messages, [
    "[叙华][persona] wake: 叙华",
    "[叙华][persona] awake",
  ]);
});

test("persona gate logs countdown cancellation and hands off to local sleep", () => {
  let timerCallback = null;
  let timerDelay = null;
  const cleared = [];
  const sleeps = [];
  const log = createLog();
  const gate = new PersonaVoiceGate({
    setTimeoutFn(callback, delay) {
      assert.equal(this, globalThis);
      timerCallback = callback;
      timerDelay = delay;
      return 17;
    },
    clearTimeoutFn(timer) {
      assert.equal(this, globalThis);
      cleared.push(timer);
    },
    onSleep() {
      sleeps.push("sleep");
    },
    log: log.logger,
  });

  gate.wake("叙华");
  assert.equal(gate.responseSettled(), true);
  assert.equal(timerDelay, PERSONA_RESPONSE_GRACE_MS);
  assert.equal(gate.allowAssistantResponse(), true);

  assert.equal(gate.noteUserActivity(), true);
  assert.deepEqual(cleared, [17]);
  assert.equal(gate.allowAssistantResponse(), true);

  assert.equal(gate.responseSettled(), true);
  timerCallback();
  assert.equal(gate.allowAssistantResponse(), false);
  assert.deepEqual(sleeps, ["sleep"]);
  assert.deepEqual(log.messages, [
    "[叙华][persona] wake: 叙华",
    "[叙华][persona] awake",
    "[叙华][persona] sleep countdown 7s",
    "[叙华][persona] awake",
    "[叙华][persona] sleep countdown 7s",
    "[叙华][persona] sleeping",
  ]);
});
