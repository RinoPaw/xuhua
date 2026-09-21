"""Build the runtime dataset from the checked-in source JSON.

The builder deliberately has no network or application imports. Keeping the
normalisation here makes ``data/source/heritage_source.json`` the only input
to the reproducible dataset build and keeps optional LLM fields in
``scripts/enrich_dataset.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "source" / "heritage_source.json"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "heritage_items.json"

CATEGORY_IDS = {
    "传统体育、游艺与杂技": 1, "传统医药": 2, "传统戏剧": 3, "传统技艺": 4,
    "传统美术": 5, "传统舞蹈": 6, "传统音乐": 7, "曲艺": 8, "民俗": 9,
    "民间文学": 10, "未分类": 0,
}
CATEGORY_DISPLAY_FORMS = {
    "传统戏剧": ("表演", "展馆讲解"), "传统音乐": ("演唱演奏", "展馆讲解"),
    "传统舞蹈": ("表演", "校园展示"), "曲艺": ("说唱表演", "展馆讲解"),
    "民间文学": ("讲述", "研学活动"), "传统美术": ("作品展示", "文创设计"),
    "传统技艺": ("工艺展示", "研学体验"), "民俗": ("民俗活动", "社区活动"),
    "传统体育、游艺与杂技": ("展示体验", "校园展示"), "传统医药": ("知识展示", "研学体验"),
}
CATEGORY_SCENARIOS = {
    "传统戏剧": ("校园展示", "社区活动", "展馆讲解"), "传统音乐": ("校园展示", "社区活动", "展馆讲解"),
    "传统舞蹈": ("校园展示", "社区活动", "展馆讲解"), "曲艺": ("校园展示", "社区活动", "展馆讲解"),
    "民间文学": ("研学体验", "校园展示"), "传统美术": ("文创设计", "展馆讲解", "校园展示"),
    "传统技艺": ("研学体验", "文创设计", "展馆讲解"), "民俗": ("社区活动", "研学体验", "展馆讲解"),
    "传统体育、游艺与杂技": ("校园展示", "社区活动"), "传统医药": ("研学体验", "展馆讲解"),
}
PROVINCES = (
    "北京市", "天津市", "上海市", "重庆市", "香港特别行政区", "澳门特别行政区",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区", "宁夏回族自治区", "新疆维吾尔自治区",
    "黑龙江省", "吉林省", "辽宁省", "河北省", "河南省", "山东省", "山西省", "陕西省",
    "甘肃省", "青海省", "四川省", "贵州省", "云南省", "海南省", "广东省", "湖南省",
    "湖北省", "安徽省", "江苏省", "浙江省", "福建省", "江西省", "台湾省",
)
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
CITY_RE = re.compile(r"^(.+?(?:自治州|地区|盟|市|州))(.*)$")
COUNTY_RE = re.compile(r"^([\u4e00-\u9fff]{2,12}(?:县|区|旗|市))(.*)$")
PLACE_TITLE_RE = re.compile(r"^[\u4e00-\u9fff]{2,12}(?:省|市|县|区|州|旗|盟|地区|自治州)$")
CORE_FIELDS = (
    "id", "title", "family", "category", "summary", "content", "search_text", "level",
    "province", "city", "district", "display_forms", "suitable_scenarios",
)


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\u00a0", " ")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</?\s*p\s*/?\s*>", "\n", text, flags=re.I)
    return WS_RE.sub(" ", TAG_RE.sub(" ", text)).strip(" \t\r\n,，")


def clean_content(value: Any) -> str:
    """Clean an introduction while retaining source paragraph boundaries."""
    text = html.unescape(str(value or "")).replace("\u00a0", " ")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</?\s*p\s*/?\s*>", "\n", text, flags=re.I)
    text = TAG_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).replace("\u3000", "")
        line = line.strip(" \t\f\v\u3000\r\n,，")
        if line:
            lines.append(line)
    if lines and lines[0].startswith("申报地区或单位："):
        lines.pop(0)
    return "\n\n".join(lines)


def normalize_title(value: Any) -> str:
    return clean_text(value)


def split_title(raw_title: Any) -> tuple[str, str]:
    title = normalize_title(raw_title)
    # The first opening parenthesis starts the family; the variant may itself
    # contain parentheses (for example ``剪纸（泉州（李尧宝）刻纸）``).
    match = re.match(r"^(.+?)[（(](.+)[）)]$", title)
    if match:
        family, variant = clean_text(match.group(1)), clean_text(match.group(2))
        if family and variant and family != variant and not PLACE_TITLE_RE.fullmatch(variant):
            return variant, family
    if "木板年画" in title:
        return title.replace("木板年画", "木版年画"), ""
    return title, ""


def split_region(region: Any) -> tuple[str, str, str]:
    text = clean_text(region)
    if not text:
        return "", "", ""
    province = next((value for value in PROVINCES if value in text), "")
    if not province:
        return "", text, ""
    remainder = text.split(province, 1)[1].strip()
    if province in MUNICIPALITIES:
        match = COUNTY_RE.match(remainder)
        district = clean_text(match.group(1)) if match else ""
        return province, province, district
    city = district = ""
    match = CITY_RE.match(remainder)
    if match:
        city, rest = clean_text(match.group(1)), match.group(2).strip()
        district = clean_text(rest)
    elif remainder:
        match = COUNTY_RE.match(remainder)
        district = clean_text(match.group(1) if match else remainder)
    return province, city, district


def make_summary(content: str, limit: int = 220) -> str:
    content = clean_text(content)
    if len(content) <= limit:
        return content
    for mark in ("。", "；", ";"):
        index = content.find(mark, 80)
        if 0 < index < limit + 40:
            return content[: index + 1]
    return content[:limit].rstrip() + "..."


def stable_id(seed: str) -> str:
    return "h_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _value(record: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = record.get(name)
        if value is not None and clean_text(value):
            return clean_text(value)
    return ""


def _raw_value(record: Mapping[str, Any], *names: str) -> Any:
    """Return the first non-empty source value without normalising it."""
    for name in names:
        value = record.get(name)
        if value is not None and clean_text(value):
            return value
    return ""


def _record_region(record: Mapping[str, Any]) -> str:
    direct = _value(record, "unit", "location", "address", "region", "province_name")
    if direct:
        return direct
    return "".join(
        (_value(record, "province"), _value(record, "city"),
         _value(record, "district", "area", "county"))
    )


def _item_id(record: Mapping[str, Any], title: str, content: str, order: int) -> str:
    """Keep IDs compatible with the existing ai/embedding sidecars."""
    source_id = _value(record, "id", "project_id", "source_id")
    if source_id:
        return stable_id(f"ihchina_{source_id}_{title}")
    return stable_id(f"missing|{order}|{title}|{content}")


def infer_scenarios(category: str, content: str) -> tuple[str, ...]:
    values = set(CATEGORY_SCENARIOS.get(category, ("展馆讲解",)))
    text = clean_text(content)
    if re.search(r"校园|学生|教育|研学|课程|教案", text):
        values.add("校园展示")
    if re.search(r"社区|村|镇|乡|居民|群众", text):
        values.add("社区活动")
    if re.search(r"文创|产品|设计|纹样|包装|IP", text, re.I):
        values.add("文创设计")
    return tuple(sorted(values))


def convert_record(record: Mapping[str, Any], order: int = 0) -> dict[str, Any]:
    raw_title = _value(record, "title", "name", "title2")
    title, inferred_family = split_title(raw_title)
    family = _value(record, "family") or inferred_family
    category = _value(record, "category", "type", "heritage_category") or "未分类"
    region = _record_region(record)
    parsed_province, parsed_city, parsed_district = split_region(region)
    province = _value(record, "province_name") or parsed_province
    city = _value(record, "city_name") or parsed_city
    district = _value(record, "district_name") or parsed_district
    raw_content = _raw_value(record, "content", "intro", "description", "text")
    flat_content = clean_text(raw_content)
    content = clean_content(raw_content)
    summary = _value(record, "summary", "摘要") or make_summary(flat_content)
    level = _value(record, "level", "project_level", "heritage_level")
    if not level:
        # The checked-in source is the national representative-list export:
        # its ``rx_time`` batch marker is the only provenance that supports a
        # national-level classification. Do not silently label an arbitrary
        # source without a level field as 国家级.
        batch = _value(record, "rx_time", "batch")
        if "人类" in batch:
            level = "人类非物质文化遗产代表作名录"
        elif batch:
            level = "国家级"
    display_forms = record.get("display_forms")
    if not isinstance(display_forms, (list, tuple)):
        display_forms = CATEGORY_DISPLAY_FORMS.get(category, ())
    scenarios = record.get("suitable_scenarios")
    if not isinstance(scenarios, (list, tuple)):
        scenarios = infer_scenarios(category, flat_content)
    item_id = _item_id(record, title, content, order)
    unit = _record_region(record)
    protect_unit = _value(record, "protect_unit", "protection_unit")
    project_num = _value(record, "project_num", "project_number")
    search_text = " ".join(
        part
        for part in (
            title, family, raw_title, category, level, province, city, district,
            unit, protect_unit, project_num, summary, flat_content,
        )
        if part
    )
    return {
        "id": item_id, "title": title, "family": family, "category": category,
        "summary": summary, "content": content, "search_text": search_text, "level": level,
        "province": province, "city": city, "district": district,
        "display_forms": [clean_text(value) for value in display_forms if clean_text(value)],
        "suitable_scenarios": [clean_text(value) for value in scenarios if clean_text(value)],
    }


def _records(payload: Any) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], {}
    if not isinstance(payload, Mapping):
        raise ValueError("heritage_source.json must contain an object or list")
    for key in ("items", "list", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)], payload
    raise ValueError("heritage_source.json must contain an items/list/records array")


def _category_id(name: str) -> int:
    if name in CATEGORY_IDS:
        return CATEGORY_IDS[name]
    return 100 + int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:4], 16)


def build_categories(
    items: Iterable[Mapping[str, Any]], source_categories: Any = None
) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("category") or "未分类") for item in items)
    source_ids = {}
    if isinstance(source_categories, list):
        source_ids = {
            str(entry.get("name")): int(entry["id"])
            for entry in source_categories
            if (
                isinstance(entry, Mapping)
                and entry.get("name") is not None
                and str(entry.get("id", "")).isdigit()
            )
        }
    names = [name for name in CATEGORY_IDS if counts.get(name)]
    names += sorted(name for name in counts if name not in CATEGORY_IDS)
    return [
        {
            "id": source_ids.get(name, _category_id(name)),
            "name": name,
            "item_count": int(counts[name]),
        }
        for name in names
    ]


def apply_implicit_families(items: list[dict[str, Any]]) -> None:
    """Group repeated public titles under their shared heritage family."""
    counts = Counter(item["title"] for item in items)
    for item in items:
        if not item["family"] and counts[item["title"]] > 1:
            item["family"] = item["title"]


def build_dataset(input_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    records, source_payload = _records(payload)
    items = [
        convert_record(record, index)
        for index, record in enumerate(records, 1)
        if _value(record, "title", "name", "title2")
    ]
    apply_implicit_families(items)
    seen: set[str] = set()
    for index, item in enumerate(items, 1):
        if item["id"] in seen:
            item["id"] = stable_id(
                f"duplicate|{item['id']}|{index}|{item['title']}|{item['content']}"
            )
        seen.add(item["id"])
    categories = build_categories(
        items, source_payload.get("categories") if source_payload else None
    )
    source_meta = source_payload.get("meta", {}) if isinstance(source_payload, Mapping) else {}
    raw_source = source_payload.get("source") if isinstance(source_payload, Mapping) else ""
    source_name = clean_text(raw_source) if isinstance(raw_source, (str, int, float)) else ""
    generated_at = ""
    if isinstance(source_meta, Mapping):
        generated_at = clean_text(source_meta.get("generated_at"))
        source_name = source_name or clean_text(source_meta.get("source"))
    meta = dict(source_meta) if isinstance(source_meta, Mapping) else {}
    meta.update({"item_count": len(items), "category_count": len(categories)})
    return {
        "schema_version": 2, "generated_at": generated_at,
        "source": source_name or "heritage_source.json",
        "meta": meta, "categories": categories, "items": items,
    }


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build heritage_items.json from heritage_source.json"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_dataset(args.input.resolve())
    atomic_write_json(args.output.resolve(), result)
    print(f"Wrote {len(result['items'])} items to {args.output}")


if __name__ == "__main__":
    main()
