import assert from "node:assert/strict";
import test from "node:test";

import {
  cancelTurnBestEffort,
  isTerminalTurnEvent,
  nextActiveTurnId,
} from "../src/lib/chatLifecycle.js";


test("terminal events clear only their active turn", () => {
  assert.equal(nextActiveTurnId(null, { type: "turn.started", turn_id: "turn-1" }), "turn-1");
  assert.equal(nextActiveTurnId("turn-1", { type: "response.text.delta", turn_id: "turn-1" }), "turn-1");
  assert.equal(nextActiveTurnId("turn-1", { type: "turn.completed", turn_id: "turn-1" }), null);
  assert.equal(nextActiveTurnId("turn-2", { type: "turn.cancelled", turn_id: "turn-1" }), "turn-2");
});


test("terminal stream detection covers every turn terminator", () => {
  assert.equal(isTerminalTurnEvent("turn.completed"), true);
  assert.equal(isTerminalTurnEvent("turn.failed"), true);
  assert.equal(isTerminalTurnEvent("turn.cancelled"), true);
  assert.equal(isTerminalTurnEvent("turn.started"), false);
  assert.equal(isTerminalTurnEvent("response.sources"), false);
  assert.equal(isTerminalTurnEvent("response.text.delta"), false);
  assert.equal(isTerminalTurnEvent(""), false);
});


test("best-effort cancel never waits for or exposes a stuck request", () => {
  let requested = "";
  const never = new Promise(() => {});
  const sent = cancelTurnBestEffort({
    fetchFn: (url, options) => {
      requested = `${options.method} ${url}`;
      return never;
    },
    url: "/cancel",
  });

  assert.equal(sent, true);
  assert.equal(requested, "POST /cancel");
});
