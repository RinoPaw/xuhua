import { VoiceMediaController } from "./voiceMedia.js";
import {
  openVoiceSocket,
  parseSocketMessage,
  sendSocketJson,
} from "./voiceTransport.js";

export class VoiceConnectionController {
  constructor({
    media = new VoiceMediaController(),
    openSocket = openVoiceSocket,
    parseMessage = parseSocketMessage,
    openState = globalThis.WebSocket?.OPEN ?? 1,
    closingState = globalThis.WebSocket?.CLOSING ?? 2,
  } = {}) {
    this.media = media;
    this.openSocket = openSocket;
    this.parseMessage = parseMessage;
    this.openState = openState;
    this.closingState = closingState;
    this.socket = null;
    this.generation = 0;
    this.starting = false;
    this.onSamples = null;
    this.inputGeneration = 0;
    this.inputStarting = false;
  }

  get connected() {
    return Boolean(this.socket && this.socket.readyState === this.openState);
  }

  get inputActive() {
    return Boolean(this.media?.stream);
  }

  sendJson(payload) {
    return sendSocketJson(this.socket, payload, this.openState);
  }

  sendRaw(payload) {
    if (!this.connected) return false;
    try {
      this.socket.send(payload);
      return true;
    } catch {
      return false;
    }
  }

  releaseStartResources(stream, socket) {
    if (socket && this.socket === socket) this.socket = null;
    if (socket) {
      socket.onmessage = null;
      socket.onclose = null;
      if (socket.readyState < this.closingState) {
        try { socket.close(1000, "stale_voice_start"); } catch { /* noop */ }
      }
    }
    this.media.release(stream);
  }

  async start(path, {
    onSamples,
    onMessage,
    onOpen,
    onClose,
  } = {}) {
    if (this.starting || this.socket) return false;

    const generation = this.generation + 1;
    const inputGeneration = this.inputGeneration + 1;
    this.generation = generation;
    this.inputGeneration = inputGeneration;
    this.starting = true;
    this.inputStarting = true;
    this.onSamples = onSamples || null;
    let stream = null;
    let socket = null;
    const isCurrent = () => this.generation === generation;

    try {
      stream = await this.media.requestStream();
      if (!isCurrent() || this.inputGeneration !== inputGeneration) {
        this.releaseStartResources(stream, socket);
        return false;
      }

      socket = await this.openSocket(path);
      if (!isCurrent() || this.inputGeneration !== inputGeneration) {
        this.releaseStartResources(stream, socket);
        return false;
      }
      this.socket = socket;

      socket.onmessage = (event) => {
        if (this.socket !== socket) return;
        const message = this.parseMessage(event);
        if (message) onMessage?.(message, event);
      };
      socket.onclose = (event) => {
        if (this.socket !== socket) return;
        this.socket = null;
        this.starting = false;
        this.inputStarting = false;
        this.generation += 1;
        this.inputGeneration += 1;
        this.media.stop();
        onClose?.(event);
      };

      onOpen?.(socket);
      await this.media.attachProcessor(this.onSamples);
      if (!isCurrent() || this.inputGeneration !== inputGeneration || this.socket !== socket) {
        this.releaseStartResources(stream, socket);
        return false;
      }

      this.starting = false;
      this.inputStarting = false;
      return true;
    } catch (error) {
      if (!isCurrent()) {
        this.releaseStartResources(stream, socket);
        return false;
      }
      this.starting = false;
      if (this.inputGeneration === inputGeneration) this.inputStarting = false;
      this.releaseStartResources(stream, socket);
      throw error;
    }
  }

  pauseInput() {
    if (!this.connected) return false;
    this.inputGeneration += 1;
    this.inputStarting = false;
    this.media.stop();
    return true;
  }

  async resumeInput(onSamples = this.onSamples) {
    if (!this.connected) return false;
    if (this.inputActive) return true;
    if (this.inputStarting) return false;

    const socket = this.socket;
    const generation = this.generation;
    const inputGeneration = this.inputGeneration + 1;
    this.inputGeneration = inputGeneration;
    this.inputStarting = true;
    this.onSamples = onSamples || this.onSamples;
    let stream = null;

    try {
      stream = await this.media.requestStream();
      if (
        generation !== this.generation
        || inputGeneration !== this.inputGeneration
        || socket !== this.socket
        || !this.connected
      ) {
        this.media.release(stream);
        return false;
      }
      await this.media.attachProcessor(this.onSamples);
      if (
        generation !== this.generation
        || inputGeneration !== this.inputGeneration
        || socket !== this.socket
        || !this.connected
      ) {
        this.media.release(stream);
        return false;
      }
      return true;
    } catch (error) {
      if (stream) this.media.release(stream);
      if (
        generation !== this.generation
        || inputGeneration !== this.inputGeneration
        || socket !== this.socket
        || !this.connected
        || /voice_media_request_stale/u.test(String(error?.message || error))
      ) return false;
      throw error;
    } finally {
      if (inputGeneration === this.inputGeneration) this.inputStarting = false;
    }
  }

  stop(reason = "client_stop") {
    this.generation += 1;
    this.inputGeneration += 1;
    this.starting = false;
    this.inputStarting = false;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onmessage = null;
      socket.onclose = null;
    }
    this.media.stop();
    if (socket && socket.readyState < this.closingState) {
      try { socket.close(1000, reason); } catch { /* noop */ }
    }
  }
}
