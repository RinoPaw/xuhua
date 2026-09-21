import {
  normalizeUtteranceId,
  normalizeVoiceId,
  REALTIME_VOICE_STATUS,
  shouldAcceptServerTurn,
  shouldAcceptServerVoiceStatus,
} from "../hooks/voiceState.js";
import { acceptVoiceUtteranceMessage } from "./voiceInput.js";

const SERVER_STATUS_MAP = Object.freeze({
  listening: REALTIME_VOICE_STATUS.LISTENING,
  user_speaking: REALTIME_VOICE_STATUS.USER_SPEAKING,
  transcribing: REALTIME_VOICE_STATUS.TRANSCRIBING,
  thinking: REALTIME_VOICE_STATUS.THINKING,
});

const SERVER_EVENT_TYPES = new Set([
  "ready",
  "status",
  "user.partial",
  "user.transcript",
  "utterance.rejected",
  "assistant.delta",
  "sources",
  "assistant.done",
  "assistant.cancelled",
  "error",
]);

const UTTERANCE_EVENTS = new Set([
  "user.partial",
  "user.transcript",
  "utterance.rejected",
]);

export function decodeVoiceServerEvent(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const type = String(value.type || "").trim();
  if (!SERVER_EVENT_TYPES.has(type)) return null;

  const message = { ...value, type };
  if (type === "status" && !SERVER_STATUS_MAP[message.status]) return null;

  if (UTTERANCE_EVENTS.has(type)) {
    const utteranceId = normalizeUtteranceId(message.utterance_id);
    if (!utteranceId) return null;
    message.utterance_id = utteranceId;
  }

  if (message.turn_id !== undefined) {
    message.turn_id = normalizeVoiceId(message.turn_id);
  }
  if (message.session_id !== undefined) {
    message.session_id = normalizeVoiceId(message.session_id);
  }

  return message;
}

export function resolveServerVoiceStatus(message) {
  return SERVER_STATUS_MAP[message?.status] || "";
}

export function acceptServerVoiceStatus(message, {
  inputState,
  currentStatus,
  bargeInTentative = false,
  activeTurn = "",
  assistantPending = false,
  ignoredTurns = new Set(),
  speechPipeline = false,
  speechActive = false,
} = {}) {
  const nextStatus = resolveServerVoiceStatus(message);
  if (!nextStatus || !inputState) return { accepted: false, status: "", activeTurn };

  if (nextStatus !== REALTIME_VOICE_STATUS.THINKING
    && !acceptVoiceUtteranceMessage(inputState, message, {
      required: nextStatus === REALTIME_VOICE_STATUS.USER_SPEAKING
        || nextStatus === REALTIME_VOICE_STATUS.TRANSCRIBING,
    })) {
    return { accepted: false, status: nextStatus, activeTurn };
  }

  if (bargeInTentative
    && [
      REALTIME_VOICE_STATUS.USER_SPEAKING,
      REALTIME_VOICE_STATUS.TRANSCRIBING,
    ].includes(nextStatus)) {
    return { accepted: false, status: nextStatus, activeTurn };
  }

  let nextTurn = activeTurn;
  if (nextStatus === REALTIME_VOICE_STATUS.THINKING) {
    if (!shouldAcceptServerTurn(
      message?.turn_id,
      activeTurn,
      assistantPending,
      ignoredTurns,
    )) {
      return { accepted: false, status: nextStatus, activeTurn };
    }
    nextTurn = normalizeVoiceId(message?.turn_id);
  }

  if (!shouldAcceptServerVoiceStatus(nextStatus, currentStatus, {
    utteranceActive: inputState.utteranceActive,
    speechPipeline,
    assistantPending,
    speechActive,
  })) {
    return { accepted: false, status: nextStatus, activeTurn };
  }

  return { accepted: true, status: nextStatus, activeTurn: nextTurn };
}

export function acceptServerVoiceError(message, {
  activeTurn = "",
  assistantPending = false,
  ignoredTurns = new Set(),
} = {}) {
  const turnId = normalizeVoiceId(message?.turn_id);
  if (!turnId) return true;
  return shouldAcceptServerTurn(turnId, activeTurn, assistantPending, ignoredTurns);
}
