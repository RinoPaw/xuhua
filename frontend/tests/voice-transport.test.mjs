import assert from "node:assert/strict";
import test from "node:test";

import {
  openVoiceSocket,
  parseSocketMessage,
  sendSocketJson,
} from "../src/lib/voiceTransport.js";

class FakeSocket {
  static OPEN = 1;
  static CLOSING = 2;

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.listeners = new Map();
    queueMicrotask(() => {
      this.readyState = FakeSocket.OPEN;
      this.listeners.get("open")?.();
    });
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.readyState = FakeSocket.CLOSING;
  }
}

test("sendSocketJson only sends on an open transport", () => {
  const socket = { readyState: 1, sent: [], send(value) { this.sent.push(value); } };
  assert.equal(sendSocketJson(socket, { type: "context" }, 1), true);
  assert.deepEqual(socket.sent, ['{"type":"context"}']);
  socket.readyState = 0;
  assert.equal(sendSocketJson(socket, { type: "ignored" }, 1), false);
});

test("parseSocketMessage rejects malformed frames", () => {
  assert.deepEqual(parseSocketMessage({ data: '{"type":"ready"}' }), { type: "ready" });
  assert.equal(parseSocketMessage({ data: "{" }), null);
});

test("openVoiceSocket maps the endpoint and waits for open", async () => {
  const socket = await openVoiceSocket("/api/voice", {
    WebSocketImpl: FakeSocket,
    baseUrl: "https://example.com/app",
  });
  assert.equal(socket.url, "wss://example.com/api/voice");
  assert.equal(socket.binaryType, "arraybuffer");
  assert.equal(socket.readyState, FakeSocket.OPEN);
});
