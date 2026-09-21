export function browserFetch(...args) {
  const fetchImpl = globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    return Promise.reject(new Error("browser_fetch_unavailable"));
  }
  return fetchImpl.call(globalThis, ...args);
}

export default browserFetch;
