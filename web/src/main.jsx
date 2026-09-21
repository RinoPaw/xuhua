import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { PersonaDisplayPage } from "./pages/PersonaDisplayPage.jsx";
import { isPersonaDisplayPath } from "./lib/displayMode.js";
import "./styles.css";

const page = isPersonaDisplayPath(globalThis.location?.pathname)
  ? <PersonaDisplayPage />
  : <App />;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {page}
  </React.StrictMode>,
);
