#!/usr/bin/env node
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wakeRoot = path.join(root, "public", "wake");
const runtimeDir = path.join(wakeRoot, "runtime");
const modelDir = path.join(wakeRoot, "model");

const SHERPA_PACKAGE_VERSION = "1.3.2-beta.0";
const RUNTIME_BASE = `https://cdn.jsdelivr.net/npm/@siteed/sherpa-onnx.rn@${SHERPA_PACKAGE_VERSION}/wasm`;
const MODEL_ARCHIVE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2";
const MODEL_FOLDER = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01";

const runtimeFiles = [
  "sherpa-onnx-wasm-combined.js",
  "sherpa-onnx-wasm-combined.wasm",
  "sherpa-onnx-combined.js",
  "sherpa-onnx-core.js",
  "sherpa-onnx-kws.js",
];

const modelFiles = {
  "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx": "encoder.onnx",
  "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx": "decoder.onnx",
  "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx": "joiner.onnx",
  "tokens.txt": "tokens.txt",
};

async function download(url, destination) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`Failed to download ${url}: HTTP ${response.status}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  writeFileSync(destination, bytes);
}

async function prepareRuntime() {
  mkdirSync(runtimeDir, { recursive: true });
  for (const name of runtimeFiles) {
    const destination = path.join(runtimeDir, name);
    if (existsSync(destination)) continue;
    console.log(`Downloading wake runtime: ${name}`);
    await download(`${RUNTIME_BASE}/${name}`, destination);
  }
}

async function prepareModel() {
  mkdirSync(modelDir, { recursive: true });
  const targets = Object.values(modelFiles).map((name) => path.join(modelDir, name));
  if (targets.every(existsSync)) return;

  const temp = mkdtempSync(path.join(os.tmpdir(), "xuhua-kws-"));
  try {
    const archive = path.join(temp, "model.tar.bz2");
    console.log("Downloading sherpa-onnx Chinese KWS model...");
    await download(MODEL_ARCHIVE_URL, archive);

    const result = spawnSync("tar", ["-xjf", archive, "-C", temp], {
      encoding: "utf8",
      stdio: "pipe",
    });
    if (result.status !== 0) {
      throw new Error(`Failed to extract KWS model with tar: ${result.stderr || result.stdout}`);
    }

    const sourceDir = path.join(temp, MODEL_FOLDER);
    for (const [sourceName, targetName] of Object.entries(modelFiles)) {
      const source = path.join(sourceDir, sourceName);
      if (!existsSync(source)) throw new Error(`Missing KWS model file after extraction: ${sourceName}`);
      copyFileSync(source, path.join(modelDir, targetName));
    }
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
}

await prepareRuntime();
await prepareModel();
console.log("Local wake-word assets are ready.");
