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


test("persona voice button follows actual local and remote microphone ownership", async () => {
  const { personaVoiceControlState } = await import("../src/lib/displayMode.js");
  assert.deepEqual(personaVoiceControlState(), {
    active: false, preparing: false, label: "开启本地唤醒监听",
  });
  assert.deepEqual(personaVoiceControlState({ wakeStarting: true }), {
    active: false, preparing: true, label: "取消本地唤醒准备",
  });
  assert.deepEqual(personaVoiceControlState({ wakeListening: true }), {
    active: true, preparing: false, label: "关闭本地唤醒监听",
  });
  assert.deepEqual(personaVoiceControlState({ connected: true, microphoneEnabled: false }), {
    active: false, preparing: false, label: "开启麦克风",
  });
  assert.deepEqual(personaVoiceControlState({ connected: true, microphoneEnabled: true }), {
    active: true, preparing: false, label: "关闭麦克风",
  });
  assert.equal(personaVoiceControlState({ available: false }).label, "语音服务暂不可用");
});
