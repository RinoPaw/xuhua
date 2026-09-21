import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const voiceStateStyles = await readFile(new URL("../src/viewportGuard.css", import.meta.url), "utf8");

test("app voice state classes cannot collide with component voice-error styles", () => {
  assert.match(appSource, /app-shell voice-state-\$\{voiceStatus\}/);
  assert.doesNotMatch(appSource, /app-shell voice-\$\{voiceStatus\}/);
});

test("speaking persona styling follows the namespaced voice state", () => {
  assert.match(voiceStateStyles, /\.app-shell\.voice-state-responding \.human-stage/);
  assert.match(voiceStateStyles, /\.app-shell\.voice-state-user_speaking \.human-stage/);
  assert.doesNotMatch(voiceStateStyles, /position:\s*fixed/);
  assert.doesNotMatch(voiceStateStyles, /max-width:\s*none/);
});
