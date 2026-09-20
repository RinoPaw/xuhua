export const REALTIME_VOICE_STATUS = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  LISTENING: "listening",
  USER_SPEAKING: "user_speaking",
  TRANSCRIBING: "transcribing",
  THINKING: "thinking",
  RESPONDING: "responding",
  ERROR: "error",
});

export const VOICE_TRANSPORT_PHASE = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  CONNECTED: "connected",
});

export const VOICE_INPUT_PHASE = Object.freeze({
  IDLE: "idle",
  SPEAKING: "speaking",
  TRANSCRIBING: "transcribing",
});

export const VOICE_TURN_PHASE = Object.freeze({
  IDLE: "idle",
  THINKING: "thinking",
});

export const VOICE_OUTPUT_PHASE = Object.freeze({
  IDLE: "idle",
  PENDING: "pending",
  SPEAKING: "speaking",
});

export function createVoiceMachineState() {
  return {
    transport: VOICE_TRANSPORT_PHASE.IDLE,
    input: VOICE_INPUT_PHASE.IDLE,
    turn: VOICE_TURN_PHASE.IDLE,
    output: VOICE_OUTPUT_PHASE.IDLE,
    fault: false,
  };
}

export function reduceVoiceMachine(state, action) {
  const current = state || createVoiceMachineState();
  switch (action?.type) {
    case "reset":
    case "transport.idle":
      return createVoiceMachineState();
    case "transport.connecting":
      return {
        ...createVoiceMachineState(),
        transport: VOICE_TRANSPORT_PHASE.CONNECTING,
      };
    case "transport.connected":
      return { ...current, transport: VOICE_TRANSPORT_PHASE.CONNECTED };
    case "input.idle":
      return { ...current, input: VOICE_INPUT_PHASE.IDLE };
    case "input.speaking":
      return { ...current, input: VOICE_INPUT_PHASE.SPEAKING };
    case "input.transcribing":
      return { ...current, input: VOICE_INPUT_PHASE.TRANSCRIBING };
    case "turn.idle":
      return { ...current, turn: VOICE_TURN_PHASE.IDLE };
    case "turn.thinking":
      return { ...current, turn: VOICE_TURN_PHASE.THINKING };
    case "output.idle":
      return { ...current, output: VOICE_OUTPUT_PHASE.IDLE };
    case "output.pending":
      return { ...current, output: VOICE_OUTPUT_PHASE.PENDING };
    case "output.speaking":
      return { ...current, output: VOICE_OUTPUT_PHASE.SPEAKING };
    case "fault.raise":
      return { ...current, fault: true };
    case "fault.clear":
      return { ...current, fault: false };
    default:
      return current;
  }
}

export function voiceActionsForServerStatus(status) {
  switch (status) {
    case REALTIME_VOICE_STATUS.LISTENING:
      return [
        { type: "fault.clear" },
        { type: "input.idle" },
        { type: "turn.idle" },
        { type: "output.idle" },
      ];
    case REALTIME_VOICE_STATUS.USER_SPEAKING:
      return [{ type: "input.speaking" }];
    case REALTIME_VOICE_STATUS.TRANSCRIBING:
      return [{ type: "input.transcribing" }];
    case REALTIME_VOICE_STATUS.THINKING:
      return [
        { type: "input.idle" },
        { type: "turn.thinking" },
      ];
    default:
      return [];
  }
}

export function isVoiceAssistantPending(state) {
  const current = state || createVoiceMachineState();
  return current.turn !== VOICE_TURN_PHASE.IDLE
    || current.output !== VOICE_OUTPUT_PHASE.IDLE;
}

export function deriveVoiceStatus(state) {
  const current = state || createVoiceMachineState();
  if (current.fault) return REALTIME_VOICE_STATUS.ERROR;
  if (current.transport === VOICE_TRANSPORT_PHASE.IDLE) return REALTIME_VOICE_STATUS.IDLE;
  if (current.transport === VOICE_TRANSPORT_PHASE.CONNECTING) {
    return REALTIME_VOICE_STATUS.CONNECTING;
  }
  if (current.input === VOICE_INPUT_PHASE.SPEAKING) {
    return REALTIME_VOICE_STATUS.USER_SPEAKING;
  }
  if (current.input === VOICE_INPUT_PHASE.TRANSCRIBING) {
    return REALTIME_VOICE_STATUS.TRANSCRIBING;
  }
  if (current.output === VOICE_OUTPUT_PHASE.SPEAKING) {
    return REALTIME_VOICE_STATUS.RESPONDING;
  }
  if (current.output === VOICE_OUTPUT_PHASE.PENDING) {
    return current.turn === VOICE_TURN_PHASE.THINKING
      ? REALTIME_VOICE_STATUS.THINKING
      : REALTIME_VOICE_STATUS.RESPONDING;
  }
  if (current.turn === VOICE_TURN_PHASE.THINKING) {
    return REALTIME_VOICE_STATUS.THINKING;
  }
  return REALTIME_VOICE_STATUS.LISTENING;
}

export function normalizeVoiceText(value) {
  const text = String(value ?? "").trim();
  return text || "";
}

export function normalizeVoiceId(value) {
  const id = String(value ?? "").trim();
  return id || "";
}

export function normalizeUtteranceId(value) {
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : 0;
}

export function shouldAcceptUtteranceEvent(utteranceId, latestId = 0, activeId = 0) {
  const id = normalizeUtteranceId(utteranceId);
  if (!id) return false;
  return id >= latestId && (!activeId || id >= activeId);
}

export function shouldAcceptServerTurn(
  turnId,
  currentTurnId,
  assistantPending,
  ignoredTurns = new Set(),
) {
  const id = normalizeVoiceId(turnId);
  if (!id || ignoredTurns.has(id) || !assistantPending) return false;
  return !currentTurnId || currentTurnId === id;
}

/**
 * Server status messages are advisory: the browser owns the local VAD/TTS
 * phases and must not let a delayed status from an older phase overwrite them.
 */
export function shouldAcceptServerVoiceStatus(
  nextStatus,
  currentStatus,
  {
    utteranceActive = false,
    speechPipeline = false,
    assistantPending = false,
    speechActive = false,
  } = {},
) {
  if (nextStatus === REALTIME_VOICE_STATUS.LISTENING
    && (utteranceActive || speechPipeline || assistantPending)) return false;

  if (nextStatus === REALTIME_VOICE_STATUS.THINKING && utteranceActive) return false;

  if (assistantPending && !utteranceActive && [
    REALTIME_VOICE_STATUS.USER_SPEAKING,
    REALTIME_VOICE_STATUS.TRANSCRIBING,
  ].includes(nextStatus)) return false;

  if (nextStatus === REALTIME_VOICE_STATUS.THINKING
    && (speechActive || currentStatus === REALTIME_VOICE_STATUS.RESPONDING)) return false;

  return true;
}
