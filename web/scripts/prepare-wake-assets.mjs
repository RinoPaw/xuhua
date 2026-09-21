#!/usr/bin/env node
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wakeRoot = path.join(root, "public", "wake");
const runtimeDir = path.join(wakeRoot, "runtime");
const modelDir = path.join(wakeRoot, "model");

const SHERPA_PACKAGE_VERSION = "1.3.1";
const SHERPA_SOURCE_COMMIT = "179a9dd8b4bca0eb8b7689b956346e8a3c1bdba4";
const RUNTIME_BASE = `https://cdn.jsdelivr.net/npm/@siteed/sherpa-onnx.rn@${SHERPA_PACKAGE_VERSION}/wasm`;
const RUNTIME_SOURCE_BASE = `https://raw.githubusercontent.com/deeeed/audiolab/${SHERPA_SOURCE_COMMIT}/packages/sherpa-onnx.rn/wasm-src`;
const MODEL_BASE = "https://www.modelscope.cn/models/pkufool/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01/resolve/master";

export const WAKE_ASSETS = [
  {
    target: path.join(runtimeDir, "sherpa-onnx-wasm-combined.js"),
    url: `${RUNTIME_BASE}/sherpa-onnx-wasm-combined.js`,
    digest: {
      algorithm: "sha256",
      value: "c7778951c5ef025d240ecf36d8d642ee2aa089353d4e46187767044547313e57",
    },
  },
  {
    target: path.join(runtimeDir, "sherpa-onnx-wasm-combined.wasm"),
    url: `${RUNTIME_BASE}/sherpa-onnx-wasm-combined.wasm`,
    digest: {
      algorithm: "sha256",
      value: "cc726f48a62ceba05541c195b7155482da7232d9300405fb5a4a7ddce6110705",
    },
  },
  {
    target: path.join(runtimeDir, "sherpa-onnx-combined.js"),
    url: `${RUNTIME_SOURCE_BASE}/sherpa-onnx-combined.js`,
    digest: {
      algorithm: "git-blob-sha1",
      value: "7d41aa0282ccd1e1b5ba751bb41e9697f06476a5",
    },
  },
  {
    target: path.join(runtimeDir, "sherpa-onnx-core.js"),
    url: `${RUNTIME_BASE}/sherpa-onnx-core.js`,
    digest: {
      algorithm: "sha256",
      value: "7913d88d173bc2140d52085cc9d62bf3c8a9b95e53842704329007fa0e37b879",
    },
  },
  {
    target: path.join(runtimeDir, "sherpa-onnx-kws.js"),
    url: `${RUNTIME_SOURCE_BASE}/sherpa-onnx-kws.js`,
    digest: {
      algorithm: "git-blob-sha1",
      value: "4ef279b7e8434af10159dcb51f274c87bd5ba6e2",
    },
  },
  {
    target: path.join(modelDir, "encoder.onnx"),
    url: `${MODEL_BASE}/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx`,
    digest: {
      algorithm: "sha256",
      value: "017af32f2c0138f931d05fbc009ee864295e910aff304f77d2f563815fc834fb",
    },
  },
  {
    target: path.join(modelDir, "decoder.onnx"),
    url: `${MODEL_BASE}/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx`,
    digest: {
      algorithm: "sha256",
      value: "fe53b8d6a07bc5373d1770649025a5a985c8fb3dab70323386a1b73aacba0546",
    },
  },
  {
    target: path.join(modelDir, "joiner.onnx"),
    url: `${MODEL_BASE}/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx`,
    digest: {
      algorithm: "sha256",
      value: "431de10b554f134ef8af320feea2db337e641290449a3d3f6cb6e5f5fd2c9c3d",
    },
  },
  {
    target: path.join(modelDir, "tokens.txt"),
    url: `${MODEL_BASE}/tokens.txt`,
    digest: {
      algorithm: "sha256",
      value: "72316508d9119696145abc6f1f8cdc46287535c34e5ce7e595f845cb1499cf2e",
    },
  },
];

export function digestBytes(bytes, digest) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  if (digest.algorithm === "sha256") {
    return createHash("sha256").update(buffer).digest("hex");
  }
  if (digest.algorithm === "git-blob-sha1") {
    return createHash("sha1")
      .update(`blob ${buffer.byteLength}\0`)
      .update(buffer)
      .digest("hex");
  }
  throw new Error(`Unsupported wake asset digest: ${digest.algorithm}`);
}

export function isAssetValid(asset) {
  if (!existsSync(asset.target)) return false;
  return digestBytes(readFileSync(asset.target), asset.digest) === asset.digest.value;
}

async function downloadVerified(asset) {
  const response = await fetch(asset.url, { redirect: "follow" });
  if (!response.ok) {
    throw new Error(`Failed to download ${asset.url}: HTTP ${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const actual = digestBytes(bytes, asset.digest);
  if (actual !== asset.digest.value) {
    throw new Error(
      `Integrity check failed for ${path.basename(asset.target)}: expected ${asset.digest.value}, got ${actual}`,
    );
  }

  mkdirSync(path.dirname(asset.target), { recursive: true });
  const temporary = `${asset.target}.tmp-${process.pid}-${Date.now()}`;
  try {
    writeFileSync(temporary, bytes);
    rmSync(asset.target, { force: true });
    renameSync(temporary, asset.target);
  } finally {
    rmSync(temporary, { force: true });
  }
}

export async function prepareWakeAssets({ checkOnly = false } = {}) {
  const missing = [];
  for (const asset of WAKE_ASSETS) {
    if (isAssetValid(asset)) continue;
    if (checkOnly) {
      missing.push(path.relative(root, asset.target));
      continue;
    }
    console.log(`Preparing wake asset: ${path.basename(asset.target)}`);
    await downloadVerified(asset);
  }

  if (missing.length) {
    throw new Error(
      `Wake assets are missing or invalid:\n- ${missing.join("\n- ")}\nRun \"npm run prepare:assets\" first.`,
    );
  }
  console.log(checkOnly ? "Wake assets verified." : "Wake assets are ready and verified.");
}

const invokedAsScript = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedAsScript) {
  prepareWakeAssets({ checkOnly: process.argv.includes("--check") }).catch((error) => {
    console.error(error?.message || error);
    process.exitCode = 1;
  });
}
