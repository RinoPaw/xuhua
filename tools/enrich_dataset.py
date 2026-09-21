"""Optionally enrich the runtime dataset with three LLM-only fields.

This script writes the sidecar consumed by ``heritage_explorer.dataset``:
``data/processed/ai_fields.json``. It can be stopped and restarted safely;
completed ids are retained, writes are atomic, and failures are kept in a
JSON manifest rather than a text log.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "ai_fields.json"
FIELDS = ("features", "history", "cultural_value")
PROMPT = """你是一个非遗数据标注助手。请只根据下面原文提取 JSON。
字段 features 是核心特色，history 是历史背景，cultural_value 是文化价值。
每个字段写 2-4 句；原文没有明确内容则写空字符串，不要编造。
只返回 JSON 对象，键必须是 features、history、cultural_value。

原文：
---
{content}
---"""


class AsyncProvider(Protocol):
    async def stream_chat(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> Any: ...


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_fields(raw: str | Mapping[str, Any]) -> dict[str, str]:
    if isinstance(raw, Mapping):
        value: Any = raw
    else:
        text = str(raw).strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.I | re.S)
        if fenced:
            text = fenced.group(1).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("provider did not return a JSON object") from exc
            value = json.loads(text[start : end + 1])
    if not isinstance(value, Mapping):
        raise ValueError("provider response must be a JSON object")
    return {field: str(value.get(field) or "").strip() for field in FIELDS}


async def _provider_text(provider: Any, messages: Sequence[Mapping[str, str]]) -> str:
    if hasattr(provider, "stream_chat"):
        result = provider.stream_chat(messages, temperature=0.1, max_tokens=800)
        if inspect.isawaitable(result):
            result = await result
        chunks: list[str] = []
        async for chunk in result:
            chunks.append(str(chunk))
        return "".join(chunks)
    if hasattr(provider, "complete"):
        result = provider.complete(messages)
        if inspect.isawaitable(result):
            result = await result
        return str(result)
    if callable(provider):
        result = provider(messages)
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "__aiter__"):
            return "".join(str(chunk) async for chunk in result)
        return str(result)
    raise TypeError("provider must expose stream_chat, complete, or be callable")


def _items(dataset: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = dataset.get("items")
    if not isinstance(value, list):
        raise ValueError("dataset must contain an items array")
    return [item for item in value if isinstance(item, Mapping) and str(item.get("id") or "")]


async def enrich_dataset(
    dataset_path: Path = DEFAULT_DATASET,
    output_path: Path = DEFAULT_OUTPUT,
    provider: AsyncProvider | Any | None = None,
    *,
    checkpoint_path: Path | None = None,
    failures_path: Path | None = None,
    max_items: int = 0,
    retries: int = 3,
    retry_failures: bool = False,
) -> dict[str, dict[str, str]]:
    """Enrich items, resuming from the existing sidecar after every result."""
    dataset = _load_json(dataset_path, {})
    if not isinstance(dataset, Mapping):
        raise ValueError("dataset must be a JSON object")
    if provider is None:
        from sys import path as sys_path

        if str(ROOT / "src") not in sys_path:
            sys_path.insert(0, str(ROOT / "src"))

        from heritage_explorer import config
        from heritage_explorer.providers.llm import OpenAICompatibleLLM

        provider = OpenAICompatibleLLM(
            api_key=config.AI_API_KEY,
            base_url=config.AI_BASE_URL,
            model=config.AI_MODEL,
            timeout=config.AI_TIMEOUT,
        )
    checkpoint_path = checkpoint_path or output_path.with_suffix(
        output_path.suffix + ".checkpoint.json"
    )
    failures_path = failures_path or output_path.with_suffix(
        output_path.suffix + ".failures.json"
    )
    existing = _load_json(output_path, {})
    if not isinstance(existing, Mapping):
        existing = {}
    results: dict[str, dict[str, str]] = {
        str(key): parse_fields(value)
        for key, value in existing.items()
        if isinstance(existing, Mapping) and isinstance(value, Mapping)
    }
    checkpoint = _load_json(checkpoint_path, {})
    if not isinstance(checkpoint, Mapping):
        checkpoint = {}
    failure_map: dict[str, dict[str, Any]] = {}
    old_failures = _load_json(failures_path, [])
    if isinstance(old_failures, list):
        failure_map = {
            str(row.get("id")): dict(row)
            for row in old_failures
            if isinstance(row, Mapping) and row.get("id")
        }
    selected = _items(dataset)
    if max_items:
        selected = selected[:max_items]
    for item in selected:
        item_id = str(item["id"])
        if item_id in results and not (retry_failures and item_id in failure_map):
            continue
        content = str(item.get("content") or item.get("summary") or "")[:6000]
        messages = [{"role": "user", "content": PROMPT.format(content=content)}]
        last_error = ""
        for attempt in range(max(1, retries)):
            try:
                fields = parse_fields(await _provider_text(provider, messages))
                results[item_id] = fields
                failure_map.pop(item_id, None)
                _atomic_json(output_path, results)
                checkpoint = {**dict(checkpoint), item_id: {"status": "ok"}}
                _atomic_json(checkpoint_path, checkpoint)
                break
            except Exception as exc:  # one malformed response must not lose prior progress
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt + 1 < max(1, retries):
                    await asyncio.sleep(min(2.0 ** attempt, 8.0))
        else:
            failure_map[item_id] = {"id": item_id, "error": last_error, "attempts": max(1, retries)}
            _atomic_json(
                failures_path,
                sorted(failure_map.values(), key=lambda row: str(row["id"])),
            )
            checkpoint = {**dict(checkpoint), item_id: {"status": "failed"}}
            _atomic_json(checkpoint_path, checkpoint)
    _atomic_json(failures_path, sorted(failure_map.values(), key=lambda row: str(row["id"])))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich heritage items with optional LLM fields")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--failures", type=Path)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-failures", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        enrich_dataset(
            args.dataset.resolve(),
            args.output.resolve(),
            checkpoint_path=args.checkpoint,
            failures_path=args.failures,
            max_items=args.max_items,
            retries=args.retries,
            retry_failures=args.retry_failures,
        )
    )
    print(f"Wrote enrichment fields to {args.output}")


if __name__ == "__main__":
    main()
