export function normalizeApiBase(value = "") {
  return String(value || "").trim().replace(/\/+$/u, "");
}

export function apiEndpoint(base, path) {
  const normalizedBase = normalizeApiBase(base);
  const normalizedPath = `/${String(path || "").replace(/^\/+/, "")}`;
  return `${normalizedBase}${normalizedPath}`;
}

export default apiEndpoint;
