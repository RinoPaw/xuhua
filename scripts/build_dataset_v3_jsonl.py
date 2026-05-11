"""Build the lean v3 heritage dataset as JSONL.

The v3 dataset is the source-of-truth shape:
id, title, family, category, level, address, content.

DeepSeek is optional and only used with --deepseek-missing to fill missing
level/address fields; failed or incomplete records are copied to review JSONL.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heritage_explorer import config  # noqa: E402
from heritage_explorer.dataset import HeritageItem, KnowledgeBase, load_dataset  # noqa: E402
from heritage_explorer.extractor import RuleExtractor, StructuredMeta  # noqa: E402


DEFAULT_INPUT = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_OUTPUT = ROOT / "data" / "dataset" / "heritage_items.v3.jsonl"
DEFAULT_REVIEW_OUTPUT = ROOT / "data" / "dataset" / "heritage_items.v3.review.jsonl"
ADDRESS_KEYS = ("province", "city", "district", "detail")
HENAN_CITIES = {
    "郑州市",
    "开封市",
    "洛阳市",
    "平顶山市",
    "安阳市",
    "鹤壁市",
    "新乡市",
    "焦作市",
    "濮阳市",
    "许昌市",
    "漯河市",
    "三门峡市",
    "南阳市",
    "商丘市",
    "信阳市",
    "周口市",
    "驻马店市",
    "济源市",
}


def build_records(
    kb: KnowledgeBase,
    *,
    use_deepseek_missing: bool = False,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    meta_by_id = _load_or_extract_meta(kb)
    records: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    items = kb.items[:limit] if limit else kb.items

    for item in items:
        meta = meta_by_id.get(item.id, StructuredMeta())
        record = _record_from_item(item, meta)
        reasons = _review_reasons(record, seen_ids)

        if reasons and use_deepseek_missing and _can_try_deepseek(reasons):
            try:
                _merge_deepseek_metadata(record, call_deepseek_metadata(item))
                reasons = _review_reasons(record, seen_ids)
            except Exception as exc:  # noqa: BLE001 - review rows capture extraction failures.
                reasons.append(f"deepseek_failed:{type(exc).__name__}")

        records.append(record)
        if reasons:
            review_rows.append({
                "id": record.get("id", ""),
                "title": record.get("title", ""),
                "reasons": reasons,
                "record": record,
            })
        seen_ids.add(str(record.get("id") or ""))

    return records, review_rows


def _load_or_extract_meta(kb: KnowledgeBase) -> dict[str, StructuredMeta]:
    extractor = RuleExtractor()
    return {item.id: extractor.extract(item) for item in kb.items}


def _record_from_item(item: HeritageItem, meta: StructuredMeta) -> dict[str, Any]:
    address = _clean_address(meta)
    return {
        "id": item.id,
        "title": item.title,
        "family": item.family,
        "category": item.category,
        "level": meta.level,
        "address": address,
        "content": item.content,
    }


def _clean_address(meta: StructuredMeta) -> dict[str, str]:
    province = meta.province.strip()
    city = meta.city.strip()
    district = meta.district.strip()

    if city in HENAN_CITIES:
        province = "河南省"

    return {
        "province": province,
        "city": city,
        "district": district,
        "detail": "",
    }


def _review_reasons(record: dict[str, Any], seen_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    for key in ("id", "title", "category", "content"):
        if not str(record.get(key) or "").strip():
            reasons.append(f"missing_{key}")
    if str(record.get("id") or "") in seen_ids:
        reasons.append("duplicate_id")

    address = record.get("address")
    if not isinstance(address, dict):
        reasons.append("invalid_address")
    else:
        for key in ADDRESS_KEYS:
            if key not in address:
                reasons.append(f"missing_address_{key}")
        if not str(address.get("province") or "").strip():
            reasons.append("review_address_province")
        if not str(address.get("city") or "").strip():
            reasons.append("review_address_city")
    if not str(record.get("level") or "").strip():
        reasons.append("review_level")

    return reasons


def _can_try_deepseek(reasons: list[str]) -> bool:
    return any(reason in {"review_level", "review_address_province", "review_address_city"} for reason in reasons)


def call_deepseek_metadata(item: HeritageItem) -> dict[str, Any]:
    if not config.AI_API_KEY:
        raise RuntimeError("AI_API_KEY is not configured")

    system_prompt = (
        "你是非物质文化遗产资料结构化助手。只输出一个 JSON 对象，不要 Markdown。"
        "字段必须是 level 和 address。level 只能从原文抽取，找不到则为空字符串。"
        "address 包含 province, city, district, detail，找不到的字段用空字符串。禁止编造。"
    )
    user_prompt = (
        f"项目名称：{item.title}\n"
        f"所属系列：{item.family}\n"
        f"类别：{item.category}\n"
        f"正文：{item.content[:4500]}"
    )
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        config.AI_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.AI_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail[:200]}") from exc

    text = str(body["choices"][0]["message"]["content"]).strip()
    return _parse_json_object(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response is not a JSON object")
    return parsed


def _merge_deepseek_metadata(record: dict[str, Any], metadata: dict[str, Any]) -> None:
    level = str(metadata.get("level") or "").strip()
    if level and not record.get("level"):
        record["level"] = level

    address = metadata.get("address")
    if not isinstance(address, dict):
        return
    record_address = record.setdefault("address", {})
    if not isinstance(record_address, dict):
        record_address = {}
        record["address"] = record_address
    for key in ADDRESS_KEYS:
        value = str(address.get(key) or "").strip()
        if value and not record_address.get(key):
            record_address[key] = value


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v3 heritage JSONL dataset")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument("--deepseek-missing", action="store_true", help="Use DeepSeek only for missing level/address")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N items")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    kb = load_dataset(args.input.resolve())
    records, review_rows = build_records(
        kb,
        use_deepseek_missing=args.deepseek_missing,
        limit=max(args.limit, 0),
    )
    row_count = write_jsonl(args.output.resolve(), records)
    review_count = write_jsonl(args.review_output.resolve(), review_rows)
    print(f"Wrote {row_count} records to {args.output}")
    print(f"Wrote {review_count} review rows to {args.review_output}")


if __name__ == "__main__":
    main()
