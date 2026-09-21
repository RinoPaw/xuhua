export const PERSONA_DISPLAY_PATH = "/display/persona";

export function isPersonaDisplayPath(pathname = "") {
  const normalized = String(pathname || "/").trim().replace(/\/+$/u, "") || "/";
  return normalized === PERSONA_DISPLAY_PATH;
}

export function personaDisplayState(search = "") {
  const query = String(search || "").replace(/^\?/u, "");
  const params = new URLSearchParams(query);
  return params.get("state") === "speaking" ? "speaking" : "idle";
}
