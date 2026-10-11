import assert from "node:assert/strict";
import test from "node:test";

import { VoiceTranscriptPresenter } from "../src/lib/voiceTranscriptPresenter.js";

function createTimerHarness() {
  let nextId = 1;
  const callbacks = new Map();
  return {
    schedule(callback) {
      const id = nextId;
      nextId += 1;
      callbacks.set(id, callback);
      return id;
    },
    clear(id) {
      callbacks.delete(id);
    },
    tick(id) {
      callbacks.get(id)?.();
    },
    has(id) {
      return callbacks.has(id);
    },
  };
}

test("presenter owns partial reveal timer and final transcript delivery", () => {
  const timer = createTimerHarness();
  const partials = [];
  const finals = [];
  const presenter = new VoiceTranscriptPresenter({
    getCallbacks: () => ({
      onUserPartial: (text) => partials.push(text),
      onUserTranscript: (text) => finals.push(text),
    }),
    scheduleInterval: (callback) => timer.schedule(callback),
    clearScheduledInterval: (id) => timer.clear(id),
  });

  assert.equal(presenter.publishPartial({ utterance_id: 1, revision: 1, text: "汴绣" }), true);
  assert.deepEqual(partials, [""]);
  const timerId = presenter.reveal.timer;
  assert.equal(timer.has(timerId), true);

  timer.tick(timerId);
  assert.deepEqual(partials, ["", "汴"]);

  assert.equal(
    presenter.publishTranscript({ utterance_id: 1, revision: 2 }, "汴绣是什么"),
    true,
  );
  assert.equal(timer.has(timerId), false);
  assert.deepEqual(finals, ["汴绣是什么"]);
});

test("presenter rejects stale finals and clears rejected utterances", () => {
  const partials = [];
  const presenter = new VoiceTranscriptPresenter({
    getCallbacks: () => ({ onUserPartial: (text) => partials.push(text) }),
    scheduleInterval: () => 1,
    clearScheduledInterval: () => {},
  });

  presenter.publishPartial({ utterance_id: 2, revision: 1, text: "木版年画" });
  assert.equal(
    presenter.publishTranscript({ utterance_id: 1, revision: 2 }, "迟到结果"),
    false,
  );

  presenter.reject({ utterance_id: 2 });
  assert.equal(presenter.reveal.visible, "");
  assert.equal(partials.at(-1), "");
});


test("an already-queued partial interval cannot reveal text from the next utterance", () => {
  let nextTimer = 0;
  const callbacks = new Map();
  const active = new Set();
  const partials = [];
  const presenter = new VoiceTranscriptPresenter({
    getCallbacks: () => ({
      onUserPartial(text, event) { partials.push([text, event?.utterance_id]); },
    }),
    scheduleInterval(callback) {
      const id = ++nextTimer;
      callbacks.set(id, callback);
      active.add(id);
      return id;
    },
    clearScheduledInterval(id) { active.delete(id); },
  });
  presenter.publishPartial({ utterance_id: 1, revision: 1, text: "第一条旧消息" });
  const oldTimer = presenter.reveal.timer;
  callbacks.get(oldTimer)();
  assert.deepEqual(partials.at(-1), ["第", 1]);

  presenter.clear(true);
  presenter.publishPartial({ utterance_id: 2, revision: 1, text: "第二条新消息" });
  const newTimer = presenter.reveal.timer;
  assert.notEqual(newTimer, oldTimer);
  const beforeStale = [...partials];
  callbacks.get(oldTimer)(); // Already queued by the platform before clear().
  assert.deepEqual(partials, beforeStale);
  assert.equal(presenter.reveal.timer, newTimer);
  assert.equal(active.has(newTimer), true);

  callbacks.get(newTimer)();
  assert.deepEqual(partials.at(-1), ["第", 2]);

  presenter.publishTranscript({ utterance_id: 2, revision: 2 }, "第二条新消息");
  const afterFinal = [...partials];
  callbacks.get(newTimer)();
  assert.deepEqual(partials, afterFinal);
  assert.equal(presenter.reveal.visible, "第二条新消息");

  presenter.publishPartial({ utterance_id: 3, revision: 1, text: "第三条" });
  const disposeTimer = presenter.reveal.timer;
  presenter.dispose();
  callbacks.get(disposeTimer)();
  assert.equal(presenter.reveal.visible, "");
  assert.equal(presenter.reveal.timer, null);
});

test("completed partial reveal clears only its own timer", () => {
  const cleared = [];
  const callbacks = [];
  const presenter = new VoiceTranscriptPresenter({
    scheduleInterval(callback) { callbacks.push(callback); return callbacks.length; },
    clearScheduledInterval(id) { cleared.push(id); },
  });
  presenter.publishPartial({ utterance_id: 1, revision: 1, text: "A" });
  callbacks[0]();
  callbacks[0](); // Completion tick clears only the first interval.
  assert.deepEqual(cleared, [1]);
  presenter.publishPartial({ utterance_id: 2, revision: 1, text: "BC" });
  const newer = presenter.reveal.timer;
  callbacks[0]();
  assert.equal(presenter.reveal.timer, newer);
  assert.deepEqual(cleared, [1]);
  presenter.dispose();
});
