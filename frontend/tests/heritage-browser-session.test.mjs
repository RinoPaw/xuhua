import assert from "node:assert/strict";
import test from "node:test";

import HeritageBrowserSession from "../src/lib/heritageBrowserSession.js";

function jsonResponse(value, { ok = true } = {}) {
  return {
    ok,
    async json() {
      return value;
    },
  };
}

function itemPage(items = [], total = items.length, offset = 0, limit = 30) {
  return jsonResponse({ items, total, offset, limit });
}

test("categories failure cannot downgrade successful meta capabilities", async () => {
  const urls = [];
  const session = new HeritageBrowserSession({
    apiBase: "https://example.test/",
    fetchFn: async (url) => {
      urls.push(url);
      if (url.endsWith("/api/meta")) {
        return jsonResponse({
          item_count: 1,
          levels: ["国家级"],
          capabilities: { realtime_voice: true },
        });
      }
      if (url.endsWith("/api/categories")) throw new Error("categories_down");
      if (url.includes("/api/items?")) return itemPage([{ id: "1", title: "汴绣" }]);
      throw new Error(`unexpected URL: ${url}`);
    },
  });

  assert.equal(await session.start(), true);
  await Promise.resolve();

  const snapshot = session.snapshot();
  assert.equal(snapshot.meta.capabilities.realtime_voice, true);
  assert.deepEqual(snapshot.categories, []);
  assert.deepEqual(snapshot.items.map((item) => item.id), ["1"]);
  assert.ok(urls.every((url) => !url.includes("example.test//api")));
  session.destroy();
});

test("slow categories do not delay initial project search", async () => {
  const session = new HeritageBrowserSession({
    fetchFn: async (url) => {
      if (url.endsWith("/api/meta")) {
        return jsonResponse({ item_count: 1, levels: [], capabilities: {} });
      }
      if (url.endsWith("/api/categories")) return new Promise(() => {});
      if (url.includes("/api/items?")) return itemPage([{ id: "1" }]);
      throw new Error(`unexpected URL: ${url}`);
    },
  });

  assert.equal(await session.start(), true);
  assert.deepEqual(session.snapshot().items.map((item) => item.id), ["1"]);
  session.destroy();
});

test("closing a detail prevents a stale response from reviving it", async () => {
  let resolveDetail;
  const detailResponse = new Promise((resolve) => {
    resolveDetail = resolve;
  });
  const session = new HeritageBrowserSession({
    fetchFn: (url) => {
      if (url.includes("/api/items/item-1")) return detailResponse;
      throw new Error(`unexpected URL: ${url}`);
    },
  });

  const request = session.openItem({ id: "item-1", title: "旧标题" });
  assert.equal(session.snapshot().selected.id, "item-1");
  session.closeItem();
  resolveDetail(jsonResponse({ id: "item-1", title: "迟到详情" }));
  await request;

  assert.equal(session.snapshot().selected, null);
  assert.equal(session.snapshot().detailLoading, false);
});

test("StrictMode-style destroy and restart invalidates the old start generation", async () => {
  let resolveFirstMeta;
  let metaCalls = 0;
  let itemCalls = 0;
  const firstMeta = new Promise((resolve) => {
    resolveFirstMeta = resolve;
  });
  const session = new HeritageBrowserSession({
    fetchFn: async (url) => {
      if (url.endsWith("/api/meta")) {
        metaCalls += 1;
        if (metaCalls === 1) return firstMeta;
        return jsonResponse({ item_count: 1, levels: [], capabilities: {} });
      }
      if (url.endsWith("/api/categories")) return jsonResponse([]);
      if (url.includes("/api/items?")) {
        itemCalls += 1;
        return itemPage([{ id: "fresh" }]);
      }
      throw new Error(`unexpected URL: ${url}`);
    },
  });

  const staleStart = session.start();
  await Promise.resolve();
  session.destroy();
  const freshStart = session.start();
  assert.equal(await freshStart, true);

  resolveFirstMeta(jsonResponse({ item_count: 999, levels: ["旧"], capabilities: {} }));
  assert.equal(await staleStart, false);

  assert.equal(itemCalls, 1);
  assert.deepEqual(session.snapshot().items.map((item) => item.id), ["fresh"]);
  assert.deepEqual(session.snapshot().meta.levels, []);
  session.destroy();
});
