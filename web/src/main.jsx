import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { PersonaDisplayPage } from "./pages/PersonaDisplayPage.jsx";
import { isLegacyPersonaDisplayPath, isPersonaDisplayPath, PERSONA_DISPLAY_PATH } from "./lib/displayMode.js";
import "./styles.css";
import "./viewportGuard.css";

if (isLegacyPersonaDisplayPath(globalThis.location?.pathname)) {
  globalThis.history?.replaceState(
    null,
    "",
    `${PERSONA_DISPLAY_PATH}${globalThis.location?.search || ""}${globalThis.location?.hash || ""}`,
  );
}

const page = isPersonaDisplayPath(globalThis.location?.pathname)
  ? <PersonaDisplayPage />
  : <App />;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {page}
  </React.StrictMode>,
);
