import assert from "node:assert/strict";
import test from "node:test";
import { activateWakeDevice, consumeWakeActivationLink, wakeActivationCode } from "../src/lib/wakeActivation.js";

const code = "test-terminal-code-123456";
const link = `https://xuhuaai.top/persona?v=0.2.7#wake=${code}`;

test("activation accepts a pasted code, a complete link, or a fragment", () => {
  assert.equal(wakeActivationCode(code), code);
  assert.equal(wakeActivationCode(link), code);
  assert.equal(wakeActivationCode(`#wake=${code}`), code);
  assert.equal(wakeActivationCode("https://xuhuaai.top/persona"), "");
  assert.equal(wakeActivationCode("invalid"), "");
});

test("activation sends same-origin credentials and verifies that the browser retained the cookie", async () => {
  const requests = [];
  await activateWakeDevice(link, { fetchImpl: async (url, options) => {
    requests.push([url, options]);
    return { ok: true, json: async () => ({ authorized: true }) };
  } });
  assert.deepEqual(requests.map(([url]) => url), ["/api/wake/authorize", "/api/wake/status"]);
  assert.equal(JSON.parse(requests[0][1].body).code, code);
  assert.equal(requests[0][1].credentials, "same-origin");
  assert.equal(requests[1][1].credentials, "same-origin");
});

test("a blocked cookie is an activation failure even when the server accepted the code", async () => {
  await assert.rejects(activateWakeDevice(code, { fetchImpl: async () => ({
    ok: true, json: async () => ({ authorized: false }),
  }) }), /wake_cookies_unavailable/u);
});

test("an open Persona page consumes a newly supplied activation fragment and clears it only after success", async () => {
  const location = { href: link, pathname: "/persona", search: "?v=0.2.7" };
  const changes = [];
  const history = { replaceState(...args) { changes.push(args); } };
  let resolve;
  const pending = consumeWakeActivationLink({ location, history,
    activate(value) { assert.equal(value, code); return new Promise(done => { resolve = done; }); },
  });
  assert.deepEqual(changes, []);
  resolve(true);
  assert.equal(await pending, true);
  assert.deepEqual(changes[0], [null, "", "/persona?v=0.2.7"]);
});

test("failed activation keeps the URL available for retry and never clears a newer link", async () => {
  const location = { href: link, pathname: "/persona", search: "" };
  const history = { replaceState() { assert.fail("must not discard the activation link"); } };
  assert.equal(await consumeWakeActivationLink({ location, history, activate: async () => false }), false);
  assert.equal(await consumeWakeActivationLink({ location, history, activate: async () => {
    location.href = link + "-new";
    return true;
  } }), true);
});

test("invalid input does not send an authorization request", async () => {
  await assert.rejects(activateWakeDevice("invalid", { fetchImpl: () => assert.fail("no request") }), /wake_invalid_code/u);
});
