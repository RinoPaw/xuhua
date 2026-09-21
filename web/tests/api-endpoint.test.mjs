import assert from "node:assert/strict";
import test from "node:test";

import {
  apiEndpoint,
  normalizeApiBase,
  normalizeEndpoint,
} from "../src/lib/apiEndpoint.js";

test("API endpoint construction is always same-origin", () => {
  assert.equal(normalizeApiBase(" https://example.com/// "), "https://example.com");
  assert.equal(apiEndpoint("https://example.com/", "/api/meta"), "/api/meta");
  assert.equal(apiEndpoint("https://example.com///", "///api/items"), "/api/items");
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
