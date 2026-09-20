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
  }

  get connected() {
    return Boolean(this.socket && this.socket.readyState === this.openState);
  }

  sendJson(payload) {
    return sendSocketJson(this.socket, payload, this.openState);
  }

  sendRaw(payload) {
    if (!this.connected) return false;
    this.socket.send(payload);
    return true;
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
    this.generation = generation;
    this.starting = true;
    let stream = null;
    let socket = null;
    const isCurrent = () => this.generation === generation;

    try {
      stream = await this.media.requestStream();
      if (!isCurrent()) {
        this.releaseStartResources(stream, socket);
        return false;
      }

      socket = await this.openSocket(path);
      if (!isCurrent()) {
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
        this.generation += 1;
        this.media.stop();
        onClose?.(event);
      };

      onOpen?.(socket);
      await this.media.attachProcessor(onSamples);
      if (!isCurrent() || this.socket !== socket) {
        this.releaseStartResources(stream, socket);
        return false;
      }

      this.starting = false;
      return true;
    } catch (error) {
      if (!isCurrent()) {
        this.releaseStartResources(stream, socket);
        return false;
      }
      this.starting = false;
      this.releaseStartResources(stream, socket);
      throw error;
    }
  }

  stop(reason = "client_stop") {
    this.generation += 1;
    this.starting = false;
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
