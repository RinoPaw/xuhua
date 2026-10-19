export function wakeActivationCode(value) {
  const text = String(value || "").trim();
  if (/^[A-Za-z0-9_-]{16,128}$/u.test(text)) return text;
  try {
    const url = new URL(text, "https://activation.invalid/");
    const code = new URLSearchParams(url.hash.slice(1)).get("wake") || "";
    return /^[A-Za-z0-9_-]{16,128}$/u.test(code) ? code : "";
  } catch { return ""; }
}

export async function activateWakeDevice(value, { fetchImpl = globalThis.fetch, signal } = {}) {
  const code = wakeActivationCode(value);
  if (!code) throw new Error("wake_invalid_code");
  const response = await fetchImpl.call(globalThis, "/api/wake/authorize", {
    method: "POST", credentials: "same-origin", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
  });
  if (!response.ok) throw new Error(response.status === 429 ? "wake_rate_limited" : "wake_invalid_code");
  const status = await fetchImpl.call(globalThis, "/api/wake/status", { credentials: "same-origin", cache: "no-store", signal });
  if (!status.ok) throw new Error("wake_activation_unavailable");
  if (!(await status.json()).authorized) throw new Error("wake_cookies_unavailable");
  return true;
}

export async function consumeWakeActivationLink({ location, history, activate }) {
  const code = wakeActivationCode(location.href);
  if (!code || !(await activate(code))) return false;
  // Never discard the link before success, or erase a newer link while awaiting a request.
  if (wakeActivationCode(location.href) === code) {
    history.replaceState(null, "", location.pathname + location.search);
  }
  return true;
}

export function activationErrorMessage(error) {
  if (error?.message === "wake_cookies_unavailable") return "浏览器未保存激活状态，请允许本站 Cookie 后重试。";
  if (error?.message === "wake_invalid_code") return "激活码不正确，请粘贴完整链接或激活码。";
  if (error?.message === "wake_rate_limited") return "尝试次数较多，请稍后重试。";
  return "暂时无法启用语音，请重试。";
}
