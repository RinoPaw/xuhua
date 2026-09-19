import assert from "node:assert/strict";
import test from "node:test";

import { VoiceMediaController } from "../src/lib/voiceMedia.js";

function makeStream() {
  const track = {
    enabled: true,
    stop() {},
  };
  return {
    track,
    getAudioTracks() { return [track]; },
    getTracks() { return [track]; },
  };
}

test("mute state is inherited by a newly acquired stream after reconnect", async () => {
  const streams = [makeStream(), makeStream()];
  const mediaDevices = {
    async getUserMedia() {
      return streams.shift();
    },
  };
  const controller = new VoiceMediaController({ mediaDevices });

  const first = await controller.requestStream();
  controller.setMuted(true);
  assert.equal(first.track.enabled, false);
  controller.stop();

  const second = await controller.requestStream();
  assert.equal(second.track.enabled, false);
});
