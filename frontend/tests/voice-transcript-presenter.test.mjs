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
