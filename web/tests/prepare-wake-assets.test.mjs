import assert from "node:assert/strict";
import test from "node:test";

import { digestBytes, WAKE_ASSETS } from "../scripts/prepare-wake-assets.mjs";

test("wake asset digests use pinned content hashes", () => {
  assert.equal(
    digestBytes(Buffer.from("abc"), { algorithm: "sha256" }),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  assert.equal(
    digestBytes(Buffer.from("hello\n"), { algorithm: "git-blob-sha1" }),
    "ce013625030ba8dba906f756967f9e9ca394464a",
  );
});

test("every wake asset has an immutable source and fixed digest", () => {
  assert.equal(WAKE_ASSETS.length, 9);
  for (const asset of WAKE_ASSETS) {
    assert.match(asset.url, /^https:\/\//u);
    assert.equal(asset.url.includes("latest"), false);
    if (asset.digest.algorithm === "sha256") {
      assert.match(asset.digest.value, /^[0-9a-f]{64}$/u);
    } else {
      assert.equal(asset.digest.algorithm, "git-blob-sha1");
      assert.match(asset.digest.value, /^[0-9a-f]{40}$/u);
      assert.match(asset.url, /179a9dd8b4bca0eb8b7689b956346e8a3c1bdba4/u);
    }
  }
});
