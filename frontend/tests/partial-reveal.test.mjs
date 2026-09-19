import assert from "node:assert/strict";
import test from "node:test";

import {
  applyFinalReveal,
  applyPartialReveal,
  createPartialRevealState,
  resetPartialReveal,
} from "../src/lib/partialReveal.js";

test("partial reveal advances revisions and reconciles text", () => {
  const reveal = createPartialRevealState();
  assert.equal(applyPartialReveal(reveal, { utterance_id: 1, revision: 1, text: "汴" }).accepted, true);
  assert.equal(reveal.target, "汴");
  assert.equal(applyPartialReveal(reveal, { utterance_id: 1, revision: 2, text: "汴绣" }).accepted, true);
  assert.equal(reveal.target, "汴绣");
});

test("final reveal rejects an older utterance", () => {
  const reveal = createPartialRevealState();
  applyPartialReveal(reveal, { utterance_id: 2, revision: 1, text: "木雕" });
  assert.equal(applyFinalReveal(reveal, { utterance_id: 1, revision: 2 }, "旧文本"), false);
  assert.equal(applyFinalReveal(reveal, { utterance_id: 2, revision: 2 }, "木雕技艺"), true);
  assert.equal(reveal.visible, "木雕技艺");
  assert.equal(reveal.finalized, true);
});

test("reset can preserve or clear transcript state", () => {
  const reveal = createPartialRevealState();
  reveal.visible = "汴绣";
  resetPartialReveal(reveal, { clearText: false });
  assert.equal(reveal.visible, "汴绣");
  resetPartialReveal(reveal, { clearText: true });
  assert.equal(reveal.visible, "");
  assert.equal(reveal.utteranceId, 0);
});
