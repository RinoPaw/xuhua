import assert from "node:assert/strict";
import test from "node:test";

import { rms, spectrumBars } from "../src/lib/voiceAudio.js";

test("rms returns zero for silence and expected energy for constant input", () => {
  assert.equal(rms(new Float32Array([0, 0, 0, 0])), 0);
  assert.ok(Math.abs(rms(new Float32Array([0.5, 0.5])) - 0.5) < 1e-6);
});

test("spectrumBars produces bounded fixed-width levels", () => {
  const bars = spectrumBars(new Float32Array([0, 0.12, 0.12, 0]), { count: 2, scale: 0.12 });
  assert.equal(bars.length, 2);
  assert.ok(bars.every((value) => value >= 0 && value <= 1));
});
