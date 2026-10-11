import assert from "node:assert/strict";
import test from "node:test";

import {
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

test("persona gate sleeps until local wake detector explicitly wakes it", () => {
  const log = createLog();
  const gate = new PersonaVoiceGate({ log: log.logger });

  assert.equal(gate.sleeping, true);
  assert.equal(gate.noteUserActivity(), false);
  gate.wake("叙华");
  assert.equal(gate.sleeping, false);
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
  assert.equal(gate.sleeping, false);

  assert.equal(gate.noteUserActivity(), true);
  assert.deepEqual(cleared, [17]);
  assert.equal(gate.sleeping, false);

  assert.equal(gate.responseSettled(), true);
  timerCallback();
  assert.equal(gate.sleeping, true);
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


test("a cancelled or replaced sleep timer cannot close a newly active session", () => {
  const callbacks = [];
  const sleeps = [];
  const gate = new PersonaVoiceGate({
    setTimeoutFn(callback) {
      callbacks.push(callback);
      return callbacks.length;
    },
    clearTimeoutFn() {},
    onSleep() { sleeps.push("sleep"); },
    log: { info() {} },
  });
  gate.wake("叙华");
  gate.responseSettled();
  const old = callbacks[0];

  gate.noteUserActivity();
  gate.responseSettled();
  const current = callbacks[1];
  old(); // Simulate a timer that was already queued when clearTimeout ran.
  assert.equal(gate.sleeping, false);
  assert.equal(gate.sleepTimer, 2);
  assert.deepEqual(sleeps, []);

  current();
  assert.equal(gate.sleeping, true);
  assert.deepEqual(sleeps, ["sleep"]);

  gate.wake("叙华");
  gate.responseSettled();
  const beforeDispose = callbacks[2];
  gate.dispose();
  beforeDispose();
  assert.deepEqual(sleeps, ["sleep"]);
});
