import {
  isVoiceAssistantPending,
  normalizeVoiceId,
  normalizeVoiceText,
  voiceActionsForServerStatus,
} from "../hooks/voiceState.js";
import { BARGE_IN_PHASE, shouldConfirmBargeInText } from "../hooks/bargeInState.js";
import { assistantEventLocale } from "./voiceProtocol.js";
import { acceptVoiceUtteranceMessage } from "./voiceInput.js";
import {
  acceptServerVoiceError,
  acceptServerVoiceStatus,
} from "./voiceServerEvents.js";

/** Route one canonical realtime voice event through browser session collaborators. */
export function routeVoiceServerEvent(message, {
  state,
  actions,
  callbacks = {},
} = {}) {
  if (!message?.type || !state?.input || !state?.machine || !state?.turns) return false;

  const output = state.output;
  const presenter = state.presenter;
  const bargeInTentative = state.bargeInPhase === BARGE_IN_PHASE.TENTATIVE;
  const assistantPending = isVoiceAssistantPending(state.machine);

  if (message.type === "ready") return true;

  if (message.type === "status") {
    const decision = acceptServerVoiceStatus(message, {
      inputState: state.input,
      currentStatus: state.status,
      bargeInTentative,
      activeTurn: state.turns.current,
      assistantPending,
      ignoredTurns: state.turns.ignoredTurns,
      speechPipeline: Boolean(output?.pipelineActive),
      speechActive: Boolean(output?.playing),
    });
    if (!decision.accepted) return false;
    if (decision.activeTurn) state.turns.setActive(decision.activeTurn);
    actions.dispatchMany(voiceActionsForServerStatus(decision.status));
    return true;
  }

  if (message.type === "user.transcript") {
    if (!acceptVoiceUtteranceMessage(state.input, message)) return false;
    state.input.activeUtteranceId = 0;
    const transcript = normalizeVoiceText(message.text);
    if (!transcript) {
      presenter?.reject(message);
      if (bargeInTentative) actions.clearBargeInCandidate();
      else actions.settleListening();
      return true;
    }

    if (bargeInTentative) {
      actions.confirmBargeInFromAsr();
    } else if (output?.pipelineActive || output?.playing) {
      actions.stopSpeech(true, false);
    } else {
      state.turns.ignoreActive();
    }
    actions.markThinking();
    presenter?.publishTranscript(message, transcript);
    return true;
  }

  if (message.type === "user.partial") {
    if (!acceptVoiceUtteranceMessage(state.input, message)) return false;
    if (bargeInTentative) {
      if (!shouldConfirmBargeInText(message.text)) return false;
      actions.confirmBargeInFromAsr();
    }
    presenter?.publishPartial(message);
    return true;
  }

  if (message.type === "assistant.delta") {
    if (!state.turns.accept(message)) return false;
    const locale = assistantEventLocale(message, state.localeHint);
    callbacks.onAssistantTranscript?.(message.text || "", { done: false, locale });
    actions.appendSpeechDelta(message.text || "", locale);
    return true;
  }

  if (message.type === "assistant.done") {
    if (!state.turns.accept(message)) return false;
    const locale = assistantEventLocale(message, state.localeHint);
    callbacks.onAssistantTranscript?.(message.text || "", { done: true, locale });
    actions.finishSpeechStream(message.text || "", locale);
    const turnId = normalizeVoiceId(message.turn_id);
    if (turnId) state.turns.ignore(turnId);
    return true;
  }

  if (message.type === "assistant.cancelled") {
    if (!state.turns.accept(message)) return false;
    actions.stopSpeech(false, false);
    actions.clearError();
    actions.settleListening();
    return true;
  }

  if (message.type === "utterance.rejected") {
    if (!acceptVoiceUtteranceMessage(state.input, message)) return false;
    presenter?.reject(message);
    if (bargeInTentative) actions.clearBargeInCandidate();
    else actions.settleListening();
    state.input.activeUtteranceId = 0;
    return true;
  }

  if (message.type === "sources") {
    if (!state.turns.accept(message)) return false;
    callbacks.onSources?.(message.items || []);
    return true;
  }

  if (message.type === "error") {
    if (!acceptServerVoiceError(message, {
      activeTurn: state.turns.current,
      assistantPending,
      ignoredTurns: state.turns.ignoredTurns,
    })) return false;
    actions.stopSpeech(false, false);
    actions.reportError(message.message || "voice_error");
    return true;
  }

  return false;
}
