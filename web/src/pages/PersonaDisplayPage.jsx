import DigitalHuman from "../components/DigitalHuman.jsx";
import { personaDisplayState } from "../lib/displayMode.js";
import "./PersonaDisplayPage.css";

export function PersonaDisplayPage({ search = globalThis.location?.search || "" }) {
  const mode = personaDisplayState(search);
  return (
    <main className={`persona-display persona-${mode}`} aria-label="叙华人物展示">
      <DigitalHuman mode={mode} showBrand={false} />
    </main>
  );
}

export default PersonaDisplayPage;
