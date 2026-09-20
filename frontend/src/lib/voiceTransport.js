import { decodeVoiceServerEvent } from "./voiceServerEvents.js";
import { websocketUrl } from "./voiceProtocol.js";

export function sendSocketJson(socket, payload, openState = globalThis.WebSocket?.OPEN ?? 1) {
  if (!socket || socket.readyState !== openState) return false;
  socket.send(JSON.stringify(payload));
  return true;
}

export function parseSocketMessage(event) {
  try {
    return decodeVoiceServerEvent(JSON.parse(event?.data));
  } catch {
    return null;
  }
}

export async function openVoiceSocket(
  path,
  {
    WebSocketImpl = globalThis.WebSocket,
    timeoutMs = 10000,
    setTimeoutFn = globalThis.setTimeout,
    clearTimeoutFn = globalThis.clearTimeout,
    baseUrl = globalThis.location?.href || "http://localhost/",
  } = {},
) {
  if (typeof WebSocketImpl !== "function") throw new Error("voice_socket_unavailable");
  const socket = new WebSocketImpl(websocketUrl(path, baseUrl));
  socket.binaryType = "arraybuffer";

  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeoutFn(() => reject(new Error("voice_socket_timeout")), timeoutMs);
      socket.addEventListener("open", () => {
        clearTimeoutFn(timer);
        resolve();
      }, { once: true });
      socket.addEventListener("error", () => {
        clearTimeoutFn(timer);
        reject(new Error("voice_socket_failed"));
      }, { once: true });
    });
    return socket;
  } catch (error) {
    if (socket.readyState < (WebSocketImpl.CLOSING ?? 2)) {
      try { socket.close(1000, "voice_socket_start_failed"); } catch { /* noop */ }
    }
    throw error;
  }
}
