import {
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
