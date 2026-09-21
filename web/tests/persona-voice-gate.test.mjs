import assert from "node:assert/strict";
import test from "node:test";

import {
  isPersonaWakePhrase,
  PERSONA_RESPONSE_GRACE_MS,
  PersonaVoiceGate,
} from "../src/lib/personaVoiceGate.js";

test("persona wake phrase must start with 叙华", () => {
  assert.equal(isPersonaWakePhrase("叙华"), true);
  assert.equal(isPersonaWakePhrase("  叙华，讲讲汴绣"), true);
  assert.equal(isPersonaWakePhrase("介绍一下叙华"), false);
  assert.equal(isPersonaWakePhrase("循环"), false);
});

test("persona gate sleeps initially and wakes only on the wake phrase", () => {
  const gate = new PersonaVoiceGate();

  assert.equal(gate.allowAssistantResponse(), false);
  assert.equal(gate.acceptTranscript("今天天气不错"), "ignore");
  assert.equal(gate.allowAssistantResponse(), false);
  assert.equal(gate.acceptTranscript("叙华"), "wake");
  assert.equal(gate.allowAssistantResponse(), true);
});

test("persona gate starts the seven second countdown only after response settles", () => {
  let timerCallback = null;
  let timerDelay = null;
  const cleared = [];
  const gate = new PersonaVoiceGate({
    setTimeoutFn(callback, delay) {
      timerCallback = callback;
      timerDelay = delay;
      return 17;
    },
    clearTimeoutFn(timer) {
      cleared.push(timer);
    },
  });

  gate.wake();
  assert.equal(gate.responseSettled(), true);
  assert.equal(timerDelay, PERSONA_RESPONSE_GRACE_MS);
  assert.equal(gate.allowAssistantResponse(), true);

  assert.equal(gate.noteUserActivity(), true);
  assert.deepEqual(cleared, [17]);
  assert.equal(gate.allowAssistantResponse(), true);

  assert.equal(gate.responseSettled(), true);
  timerCallback();
  assert.equal(gate.allowAssistantResponse(), false);
});
