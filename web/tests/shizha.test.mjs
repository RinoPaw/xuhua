import test from "node:test";
import assert from "node:assert/strict";
import { agentProfile } from "../src/lib/agentProfile.js";
import { apiEndpoint } from "../src/lib/apiEndpoint.js";
import { ttsEndpoint } from "../src/lib/voiceProtocol.js";
import HeritageBrowserSession from "../src/lib/heritageBrowserSession.js";
import { createServer } from "vite";
import React from "react";
import { renderToString } from "react-dom/server";

test("only the Shizha entry selects the case identity and API namespace", () => {
  for (const path of ["/shizha", "/shizha/"]) {
    const profile = agentProfile(path);
    assert.equal(profile.name, "识诈");
    assert.equal(apiEndpoint(profile.apiBase, "/api/voice"), "/shizha/api/voice");
    assert.equal(ttsEndpoint(apiEndpoint(profile.apiBase, "/api/voice")), "/shizha/api/tts");
    assert.equal(apiEndpoint(profile.apiBase, "/api/chat/session/turn/turn/cancel"), "/shizha/api/chat/session/turn/turn/cancel");
  }
  for (const path of ["/", "/persona", "/shizhax", "/shizha/other"]) {
    assert.equal(agentProfile(path).name, "叙华");
  }
  assert.equal(apiEndpoint("https://other.example/shizha", "/api/chat"), "/api/chat");
});

test("the shared browser sends all case requests and filters to the case namespace", async () => {
  const requests = [];
  const session = new HeritageBrowserSession({ apiBase: "/shizha",
    fetchFn: async url => {
      requests.push(url);
      let data;
      if (url.endsWith("/api/meta")) data = { item_count: 1, levels: [], risk_levels: ["高"] };
      else if (url.endsWith("/api/categories")) data = [];
      else if (url.endsWith("/api/items/FZ-001")) data = { id: "FZ-001", case_id: "FZ-001", title: "案例", risk_signals: "要求共享屏幕" };
      else if (url.includes("/api/items?")) data = { items: [{ id: "FZ-001", title: "案例" }], total: 1, offset: 0, limit: 30 };
      else assert.fail(`unexpected request: ${url}`);
      return { ok: true, json: async () => data };
    },
  });
  try {
    await session.start();
    session.applyFilters({ risk_level: "高", entry_channel: "电话", victim_group: "老人" });
    await new Promise(resolve => setImmediate(resolve));
    const filtered = new URL(requests.find(url => url.includes("risk_level=")), "https://test.example");
    assert.equal(filtered.searchParams.get("risk_level"), "高");
    assert.equal(filtered.searchParams.get("entry_channel"), "电话");
    assert.equal(filtered.searchParams.get("victim_group"), "老人");
    await session.openItem({ id: "FZ-001" });
    assert.equal(session.snapshot().selected.risk_signals, "要求共享屏幕");
    assert.ok(requests.every(url => url.startsWith("/shizha/api/")));
  } finally { session.destroy(); }
});

test("the shared App renders the case identity and panda asset without a heritage persona", async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
  try {
    const { App } = await server.ssrLoadModule("/src/App.jsx");
    const html = renderToString(React.createElement(App, { profile: agentProfile("/shizha") })).replace(/<!--[\s\S]*?-->/gu, "");
    assert.ok(html.includes("与识诈对话"));
    assert.ok(html.includes("/assets/portraits/panda-officer.jpg"));
    assert.ok(html.includes("熊猫警官"));
    assert.ok(html.includes("反诈案例"));
    assert.ok(html.includes("向识诈提问"));
    assert.ok(!html.includes("与叙华对话"));
    assert.ok(!html.includes("非遗类别"));
    assert.ok(!html.includes("<video"));
  } finally { await server.close(); }
});
