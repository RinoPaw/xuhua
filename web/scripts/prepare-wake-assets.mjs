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

const SHERPA_PACKAGE_VERSION = "1.3.1";
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

function tarExecutable() {
  if (process.platform !== "win32") return "tar";
  const systemRoot = process.env.SystemRoot || process.env.WINDIR;
  if (systemRoot) {
    const systemTar = path.join(systemRoot, "System32", "tar.exe");
    if (existsSync(systemTar)) return systemTar;
  }
  return "tar.exe";
}

function extractTarBz2(archive, destination) {
  const executable = tarExecutable();
  const result = spawnSync(executable, ["-xjf", archive, "-C", destination], {
    encoding: "utf8",
    stdio: "pipe",
    windowsHide: true,
  });
  if (result.error) {
    throw new Error(
      `Failed to start tar (${executable}): ${result.error.code || result.error.message}`,
    );
  }
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim();
    throw new Error(
      `Failed to extract KWS model with tar (${executable}, exit ${result.status})${detail ? `: ${detail}` : ""}`,
    );
  }
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
    extractTarBz2(archive, temp);

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
