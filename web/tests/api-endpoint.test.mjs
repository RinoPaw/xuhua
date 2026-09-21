import assert from "node:assert/strict";
import test from "node:test";

import {
  apiEndpoint,
  normalizeApiBase,
  normalizeEndpoint,
} from "../src/lib/apiEndpoint.js";

test("API endpoint construction normalizes trailing and leading slashes", () => {
  assert.equal(normalizeApiBase(" https://example.com/// "), "https://example.com");
  assert.equal(apiEndpoint("https://example.com/", "/api/meta"), "https://example.com/api/meta");
  assert.equal(apiEndpoint("https://example.com///", "///api/items"), "https://example.com/api/items");
  assert.equal(apiEndpoint("", "/api/chat"), "/api/chat");
  assert.equal(apiEndpoint("/", "api/voice"), "/api/voice");
});

test("complete transport endpoints collapse duplicate path slashes without touching the scheme", () => {
  assert.equal(
    normalizeEndpoint("https://example.com//api//voice"),
    "https://example.com/api/voice",
  );
  assert.equal(
    normalizeEndpoint("wss://example.com///api/voice?mode=a//b"),
    "wss://example.com/api/voice?mode=a//b",
  );
  assert.equal(normalizeEndpoint("//api//voice"), "/api/voice");
});
