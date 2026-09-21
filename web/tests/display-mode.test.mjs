import assert from "node:assert/strict";
import test from "node:test";

import {
  isPersonaDisplayPath,
  personaDisplayState,
} from "../src/lib/displayMode.js";

test("persona display route is exact and accepts a trailing slash", () => {
  assert.equal(isPersonaDisplayPath("/display/persona"), true);
  assert.equal(isPersonaDisplayPath("/display/persona/"), true);
  assert.equal(isPersonaDisplayPath("/display/persona/extra"), false);
  assert.equal(isPersonaDisplayPath("/"), false);
});

test("persona display defaults idle and accepts explicit speaking state", () => {
  assert.equal(personaDisplayState(""), "idle");
  assert.equal(personaDisplayState("?state=idle"), "idle");
  assert.equal(personaDisplayState("?state=speaking"), "speaking");
  assert.equal(personaDisplayState("?state=unknown"), "idle");
});
