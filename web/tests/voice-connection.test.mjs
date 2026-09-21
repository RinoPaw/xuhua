import assert from "node:assert/strict";
import test from "node:test";

import { VoiceConnectionController } from "../src/lib/voiceConnection.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function makeSocket() {
  return {
    readyState: 1,
    sent: [],
    closeCalls: [],
    onmessage: null,
    onclose: null,
    send(value) { this.sent.push(value); },
    close(code, reason) {
      this.closeCalls.push([code, reason]);
      this.readyState = 3;
    },
  };
}

function makeMedia() {
  let streamId = 0;
  return {
    stream: null,
    onSamples: null,
    stopCalls: 0,
    released: [],
    muted: false,
    async requestStream() {
      this.stream = { id: ++streamId };
      return this.stream;
    },
    async attachProcessor(callback) {
      this.onSamples = callback;
      return {};
    },
    release(stream) {
      if (!stream) return false;
      this.released.push(stream);
      if (this.stream === stream) {
        this.stop();
        return true;
      }
      return false;
    },
    stop() {
      this.stopCalls += 1;
      this.stream = null;
    },
    setMuted(value) {
      this.muted = Boolean(value);
      return this.muted;
    },
  };
}

test("connection owns socket message routing, media samples, and sends", async () => {
  const media = makeMedia();
  const socket = makeSocket();
  const messages = [];
  const samples = [];
  let opened = false;
  const connection = new VoiceConnectionController({
    media,
    openSocket: async () => socket,
    parseMessage: (event) => event.message,
    openState: 1,
    closingState: 2,
  });

  assert.equal(await connection.start("/api/voice", {
    onOpen: () => { opened = true; },
    onMessage: (message) => messages.push(message),
    onSamples: (value, rate) => samples.push([value, rate]),
  }), true);

  assert.equal(opened, true);
  assert.equal(connection.connected, true);
  socket.onmessage({ message: { type: "ready" } });
  assert.deepEqual(messages, [{ type: "ready" }]);
  media.onSamples("pcm", 48000);
  assert.deepEqual(samples, [["pcm", 48000]]);

  assert.equal(connection.sendJson({ type: "context" }), true);
  assert.equal(connection.sendRaw("binary"), true);
  assert.deepEqual(socket.sent, [JSON.stringify({ type: "context" }), "binary"]);
});

test("connection send methods report a socket-close race without throwing", () => {
  const connection = new VoiceConnectionController({
    media: makeMedia(),
    openState: 1,
    closingState: 2,
  });
  connection.socket = {
    readyState: 1,
    send() { throw new Error("closed_between_check_and_send"); },
  };

  assert.equal(connection.sendJson({ type: "context" }), false);
  assert.equal(connection.sendRaw("pcm"), false);
});

test("stale connection start cannot replace a newer session", async () => {
  const media = makeMedia();
  const opens = [deferred(), deferred()];
  let openIndex = 0;
  const connection = new VoiceConnectionController({
    media,
    openSocket: () => opens[openIndex++].promise,
    parseMessage: (event) => event,
    openState: 1,
    closingState: 2,
  });

  const firstStart = connection.start("/api/voice");
  await Promise.resolve();
  connection.stop();
  const secondStart = connection.start("/api/voice");
  await Promise.resolve();

  const secondSocket = makeSocket();
  opens[1].resolve(secondSocket);
  assert.equal(await secondStart, true);
  assert.equal(connection.socket, secondSocket);

  const firstSocket = makeSocket();
  opens[0].resolve(firstSocket);
  assert.equal(await firstStart, false);
  assert.equal(firstSocket.readyState, 3);
  assert.equal(connection.socket, secondSocket);
  assert.equal(secondSocket.readyState, 1);
});

test("microphone can pause and resume without reopening the current socket", async () => {
  const media = makeMedia();
  const socket = makeSocket();
  const samples = [];
  const connection = new VoiceConnectionController({
    media,
    openSocket: async () => socket,
    parseMessage: (event) => event,
    openState: 1,
    closingState: 2,
  });

  assert.equal(await connection.start("/api/voice", {
    onSamples: (value, rate) => samples.push([value, rate]),
  }), true);
  const firstStream = media.stream;

  assert.equal(connection.pauseInput(), true);
  assert.equal(connection.connected, true);
  assert.equal(connection.socket, socket);
  assert.equal(connection.inputActive, false);
  assert.equal(socket.closeCalls.length, 0);

  assert.equal(await connection.resumeInput(), true);
  assert.equal(connection.connected, true);
  assert.equal(connection.socket, socket);
  assert.equal(connection.inputActive, true);
  assert.notEqual(media.stream, firstStream);
  media.onSamples("pcm-2", 48000);
  assert.deepEqual(samples, [["pcm-2", 48000]]);
  assert.equal(socket.closeCalls.length, 0);
});

test("unexpected current socket close invalidates connection and stops media", async () => {
  const media = makeMedia();
  const socket = makeSocket();
  const closed = [];
  const connection = new VoiceConnectionController({
    media,
    openSocket: async () => socket,
    parseMessage: (event) => event,
    openState: 1,
    closingState: 2,
  });

  assert.equal(await connection.start("/api/voice", {
    onClose: (event) => closed.push(event.code),
  }), true);
  socket.readyState = 3;
  socket.onclose({ code: 1006 });

  assert.equal(connection.connected, false);
  assert.equal(connection.socket, null);
  assert.equal(media.stopCalls, 1);
  assert.deepEqual(closed, [1006]);
});
