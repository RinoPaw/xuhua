export function normalizeApiBase(value = "") {
  return String(value || "").trim().replace(/\/+$/u, "");
}

export function normalizeEndpoint(value = "") {
  const raw = String(value || "").trim();
  const absolute = raw.match(/^([a-z][a-z0-9+.-]*:\/\/)([^?#]*)(.*)$/iu);
  if (absolute) {
    return `${absolute[1]}${absolute[2].replace(/\/{2,}/gu, "/")}${absolute[3]}`;
  }
  return raw.replace(/\/{2,}/gu, "/");
}

export function apiEndpoint(_base, path) {
  const normalizedPath = `/${String(path || "").replace(/^\/+/, "")}`;
  return normalizeEndpoint(normalizedPath);
}

export default apiEndpoint;
