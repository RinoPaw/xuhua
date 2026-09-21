import assert from "node:assert/strict";
import test from "node:test";

import config from "../vite.config.mjs";

test("vite dev proxy forwards realtime voice websocket upgrades", () => {
  assert.equal(config.server?.proxy?.["/api"]?.ws, true);
});
