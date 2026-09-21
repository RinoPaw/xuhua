export async function browserFetch(...args) {
  const fetchImpl = globalThis.fetch;
  const url = String(args[0] || "");
  if (typeof fetchImpl !== "function") {
    const error = new Error("browser_fetch_unavailable");
    globalThis.console?.error?.("[叙华][http] fetch unavailable", url, error);
    throw error;
  }
  try {
    return await fetchImpl.call(globalThis, ...args);
  } catch (error) {
    globalThis.console?.error?.("[叙华][http] fetch failed", url, error);
    throw error;
  }
}

export default browserFetch;
