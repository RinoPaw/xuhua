import assert from "node:assert/strict";
import test from "node:test";

import {
  isLegacyPersonaDisplayPath,
  isPersonaDisplayPath,
  PERSONA_DISPLAY_PATH,
  personaDisplayState,
} from "../src/lib/displayMode.js";

test("persona display route is exact and accepts a trailing slash", () => {
  assert.equal(PERSONA_DISPLAY_PATH, "/persona");
  assert.equal(isPersonaDisplayPath("/persona"), true);
  assert.equal(isPersonaDisplayPath("/persona/"), true);
  assert.equal(isPersonaDisplayPath("/display/persona"), true);
  assert.equal(isPersonaDisplayPath("/display/persona/"), true);
  assert.equal(isLegacyPersonaDisplayPath("/display/persona/"), true);
  assert.equal(isLegacyPersonaDisplayPath("/persona"), false);
  assert.equal(isPersonaDisplayPath("/persona/extra"), false);
  assert.equal(isPersonaDisplayPath("/display/persona/extra"), false);
  assert.equal(isPersonaDisplayPath("/"), false);
});

test("persona display defaults idle and accepts explicit speaking state", () => {
  assert.equal(personaDisplayState(""), "idle");
  assert.equal(personaDisplayState("?state=idle"), "idle");
  assert.equal(personaDisplayState("?state=speaking"), "speaking");
  assert.equal(personaDisplayState("?state=unknown"), "idle");
});
