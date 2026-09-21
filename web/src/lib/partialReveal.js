import { acceptPartialRevision, reconcilePartialText, startsNewTranscript } from "./voiceTranscript.js";

export function createPartialRevealState() {
  return {
    utteranceId: 0,
    revision: 0,
    finalized: false,
    visible: "",
    target: "",
    timer: null,
    event: null,
  };
}

export function resetPartialReveal(reveal, { clearText = false } = {}) {
  if (!clearText) return reveal;
  reveal.utteranceId = 0;
  reveal.revision = 0;
  reveal.finalized = false;
  reveal.visible = "";
  reveal.target = "";
  reveal.event = null;
  return reveal;
}

export function applyPartialReveal(reveal, message) {
  const accepted = acceptPartialRevision(reveal, message);
  if (!accepted.accepted) return { accepted: false, startsNew: false };

  const startsNew = startsNewTranscript(reveal, message);
  const baseVisible = startsNew ? "" : reveal.visible;
  const target = String(message?.text || "");
  const reconciled = reconcilePartialText(baseVisible, target);

  reveal.utteranceId = accepted.state.utteranceId;
  reveal.revision = accepted.state.revision;
  reveal.finalized = false;
  reveal.visible = reconciled.visible;
  reveal.target = reconciled.target;
  reveal.event = message;
  return { accepted: true, startsNew };
}

export function applyFinalReveal(reveal, message, transcript) {
  const id = Number(message?.utterance_id);
  if (Number.isSafeInteger(id) && id > 0 && id < reveal.utteranceId) return false;
  reveal.utteranceId = Number.isSafeInteger(id) && id > 0 ? id : reveal.utteranceId;
  reveal.revision = Number(message?.revision) || reveal.revision;
  reveal.finalized = true;
  reveal.visible = String(transcript || "");
  reveal.target = reveal.visible;
  reveal.event = message;
  return true;
}
