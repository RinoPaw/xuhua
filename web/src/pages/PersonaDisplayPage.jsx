import { useCallback, useEffect, useMemo, useState } from "react";

import DigitalHuman from "../components/DigitalHuman.jsx";
import { useVoiceConversation } from "../hooks/useVoiceConversation.js";
import { createConversationSessionId } from "../lib/conversationSession.js";
import { personaDisplayState } from "../lib/displayMode.js";
import { getLocaleHint, getPreferredLocales } from "../lib/locale.js";
import { PersonaBrowserVoiceSession } from "../lib/personaBrowserVoiceSession.js";
import "./PersonaDisplayPage.css";

const LOCALE_HINT = getLocaleHint();
const PREFERRED_LOCALES = getPreferredLocales();

export function PersonaDisplayPage({ search = globalThis.location?.search || "" }) {
  const [sessionId] = useState(createConversationSessionId);
  const previewMode = personaDisplayState(search);
  const recognitionContext = useMemo(() => ({
    sessionId,
    localeHint: LOCALE_HINT,
    preferredLocales: PREFERRED_LOCALES,
  }), [sessionId]);
  const createSession = useCallback(
    (options) => new PersonaBrowserVoiceSession(options),
    [],
  );
  const realtime = useVoiceConversation({
    websocketPath: "/api/voice",
    recognitionContext,
    createSession,
  });

  useEffect(() => {
    void realtime.start();
  }, [realtime.start]);

  const mode = realtime.isPlaying ? "speaking" : previewMode;

  return (
    <main className="app-shell persona-display" aria-label="叙华人物展示">
      <div className="workspace persona-display-workspace">
        <aside className="left-panel persona-display-panel">
          <DigitalHuman mode={mode} />
        </aside>
      </div>
    </main>
  );
}

export default PersonaDisplayPage;
