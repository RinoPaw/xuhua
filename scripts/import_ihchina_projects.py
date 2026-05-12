"""Import ihchina project-list JSON into the normalized heritage dataset."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from heritage_explorer.dataset import HeritageItem  # noqa: E402
from heritage_explorer.extractor import StructuredMeta, infer_soft_labels  # noqa: E402


DEFAULT_INPUT = (
    ROOT
    / "ihchina.cn_getProject.html_province_rx_time_type_cate_keywords_category_id_16_limit_9999_p_1_1275518861_1(1).txt"
)
DEFAULT_DATASET = ROOT / "data" / "processed" / "heritage_items.json"

SOURCE_NAME = "ihchina"
SOURCE_URL_PREFIX = "https://www.ihchina.cn/project_details/"

TITLE_FAMILY_SUFFIXES = ("木版年画",)
PLACE_QUALIFIER_RE = re.compile(r"^[\u4e00-\u9fff]{2,12}(?:省|市|县|区|州|旗|盟|地区|自治州)$")
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
PROJECT_BATCH_RE = re.compile(r"(\d{4}).*?[（(]([^）)]+)[）)]")
CITY_RE = re.compile(r"^(.+?(?:自治州|地区|盟|市|州))(.*)$")
COUNTY_CITY_RE = re.compile(r"^([\u4e00-\u9fff]{2,12}(?:县|区|旗|市))(.*)$")

PROVINCES = (
    "北京市",
    "天津市",
    "上海市",
    "重庆市",
    "香港特别行政区",
    "澳门特别行政区",
    "内蒙古自治区",
    "广西壮族自治区",
    "西藏自治区",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "黑龙江省",
    "吉林省",
    "辽宁省",
    "河北省",
    "河南省",
    "山东省",
    "山西省",
    "陕西省",
    "甘肃省",
    "青海省",
    "四川省",
    "贵州省",
    "云南省",
    "海南省",
    "广东省",
    "湖南省",
    "湖北省",
    "安徽省",
    "江苏省",
    "浙江省",
    "福建省",
    "江西省",
    "台湾省",
)
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}

CATEGORY_IDS = {
    "传统戏剧": 1,
    "传统音乐": 2,
    "传统美术": 3,
    "传统舞蹈": 4,
    "传统医药": 5,
    "民俗": 6,
    "传统技艺": 7,
    "曲艺": 8,
    "传统体育、游艺与杂技": 9,
    "民间文学": 10,
    "未分类": 0,
}

CATEGORY_DISPLAY_FORMS = {
    "传统戏剧": ("表演", "展馆讲解"),
    "传统音乐": ("演唱演奏", "展馆讲解"),
    "传统舞蹈": ("表演", "校园展示"),
    "曲艺": ("说唱表演", "展馆讲解"),
    "民间文学": ("讲述", "研学活动"),
    "传统美术": ("作品展示", "文创设计"),
    "传统技艺": ("工艺展示", "研学体验"),
    "民俗": ("民俗活动", "社区活动"),
    "传统体育、游艺与杂技": ("展示体验", "校园展示"),
    "传统医药": ("知识展示", "研学体验"),
}


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\u00a0", " ")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
    text = TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip(" \t\r\n,，")


def normalize_title(value: str) -> str:
    return WHITESPACE_RE.sub("", value.replace("\u00a0", " ")).strip()


def split_parenthetical_title(title: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)[（(](.+)[）)]$", normalize_text(title))
    if not match:
        return "", ""
    family = normalize_text(match.group(1))
    variant = normalize_text(match.group(2))
    if PLACE_QUALIFIER_RE.match(variant):
        return "", ""
    if not family or not variant or family == variant:
        return "", ""
    return family, variant


def public_title_parts(title: str) -> tuple[str, str]:
    family, variant = split_parenthetical_title(title)
    if family and variant:
        return variant, family

    if "木板年画" in title:
        return title.replace("木板年画", "木版年画"), "木版年画"

    for suffix in TITLE_FAMILY_SUFFIXES:
        if title.endswith(suffix) and title != suffix:
            return title, suffix

    return normalize_text(title), ""


def split_region(region: str) -> tuple[str, str, str]:
    text = normalize_text(region)
    province = ""
    remainder = text
    for candidate in PROVINCES:
        if candidate in text:
            province = candidate
            remainder = text.split(candidate, 1)[1].strip()
            break

    if not province:
        return "", text, ""

    if province in MUNICIPALITIES:
        city = province
        district = remainder
        return province, city, district

    city = ""
    district = ""
    match = CITY_RE.match(remainder)
    if match:
        city = normalize_text(match.group(1))
        district = normalize_text(match.group(2))
    elif remainder:
        county_match = COUNTY_CITY_RE.match(remainder)
        if county_match:
            city = normalize_text(county_match.group(1))
            district = normalize_text(county_match.group(2))

    return province, city or province, district


def parse_batch(value: str) -> str:
    text = normalize_text(value)
    match = PROJECT_BATCH_RE.search(text)
    if not match:
        return text
    return f"{match.group(1)}（{match.group(2)}）"


def stable_id(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"h_{digest}"


def summary_from(content: str) -> str:
    content = normalize_text(content)
    if len(content) <= 220:
        return content
    for mark in ("。", "；", ";"):
        index = content.find(mark, 80)
        if 0 < index <= 260:
            return content[: index + 1]
    return content[:220].rstrip() + "..."


def convert_record(record: dict[str, Any]) -> dict[str, Any]:
    raw_title = normalize_text(record.get("title"))
    title, family = public_title_parts(raw_title)
    category = normalize_text(record.get("type")) or "未分类"
    unit = normalize_text(record.get("unit") or record.get("province"))
    province, city, district = split_region(unit or normalize_text(record.get("province")))
    intro = normalize_text(record.get("content"))
    batch = parse_batch(str(record.get("rx_time") or ""))
    project_num = normalize_text(record.get("project_num"))
    protect_unit = normalize_text(record.get("protect_unit"))
    official_title = raw_title

    metadata_lines = [
        f"标题: {title}",
        f"族属: {family}" if family else "",
        "归属: 国家级",
        f"类别: {category}",
        f"城市: {city}",
        f"地区: {district}",
        f"报道地区: {unit}",
        f"申报批次: {batch}" if batch else "",
        f"项目编号: {project_num}" if project_num else "",
        f"保护单位: {protect_unit}" if protect_unit else "",
        f"官方名称: {official_title}",
        f"介绍: {intro}" if intro else "",
    ]
    content = ", ".join(line for line in metadata_lines if line)
    summary = summary_from(intro or content)
    display_forms = CATEGORY_DISPLAY_FORMS.get(category, ())

    item = HeritageItem(
        id=f"{SOURCE_NAME}_{record.get('id')}",
        title=title,
        family=family,
        category=category,
        summary=summary,
        content=content,
        search_text=" ".join(
            part
            for part in [
                title,
                family,
                official_title,
                category,
                "国家级",
                province,
                city,
                district,
                unit,
                protect_unit,
                project_num,
                summary,
                intro,
            ]
            if part
        ),
        source={
            "provider": SOURCE_NAME,
            "source_id": str(record.get("id") or ""),
            "official_title": official_title,
            "project_num": project_num,
            "batch": batch,
            "unit": unit,
            "protect_unit": protect_unit,
            "url": f"{SOURCE_URL_PREFIX}{record.get('id')}.html",
        },
        level="国家级",
        province=province,
        city=city,
        district=district,
        display_forms=display_forms,
        history="",
        features="",
        cultural_value="",
    )
    meta = StructuredMeta(
        level=item.level,
        province=item.province,
        city=item.city,
        district=item.district,
        display_forms=item.display_forms,
        organization=protect_unit,
        history=item.history,
        features=item.features,
        cultural_value=item.cultural_value,
    )
    labels = infer_soft_labels(item, meta)

    return {
        "id": item.id,
        "title": item.title,
        "family": item.family,
        "category": item.category,
        "summary": item.summary,
        "content": item.content,
        "search_text": item.search_text,
        "source": item.source,
        "level": item.level,
        "province": item.province,
        "city": item.city,
        "district": item.district,
        "display_forms": list(item.display_forms),
        "history": item.history,
        "features": item.features,
        "cultural_value": item.cultural_value,
        "suitable_scenarios": list(labels.suitable_scenarios),
        "target_audience": list(labels.target_audience),
        "display_difficulty": labels.display_difficulty,
        "interaction_potential": labels.interaction_potential,
        "education_value": labels.education_value,
        "cultural_keywords": list(labels.cultural_keywords),
    }


def load_ihchina_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("list")
    if not isinstance(records, list):
        raise ValueError(f"{path} does not contain an ihchina list payload")
    return [record for record in records if isinstance(record, dict)]


def build_categories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("category") or "未分类") for item in items)
    categories = []
    for name, category_id in sorted(CATEGORY_IDS.items(), key=lambda pair: pair[1]):
        if counts.get(name, 0):
            categories.append({"id": category_id, "name": name, "item_count": int(counts[name])})
    for name in sorted(counts):
        if name not in CATEGORY_IDS:
            categories.append({"id": stable_category_id(name), "name": name, "item_count": int(counts[name])})
    return categories


def stable_category_id(name: str) -> int:
    return 100 + int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:4], 16)


def import_projects(raw_path: Path, dataset_path: Path) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    existing_items = [
        item
        for item in dataset.get("items", [])
        if not str(item.get("id") or "").startswith(f"{SOURCE_NAME}_")
    ]
    imported_items = [convert_record(record) for record in load_ihchina_records(raw_path)]
    items = existing_items + imported_items

    source = dict(dataset.get("source") or {})
    source["item_count"] = len(items)
    source.setdefault("imports", {})
    source["imports"][SOURCE_NAME] = {
        "file": str(raw_path),
        "item_count": len(imported_items),
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "schema_version": dataset.get("schema_version", 2),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "categories": build_categories(items),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = import_projects(args.input.resolve(), args.dataset.resolve())
    args.dataset.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    imported = sum(1 for item in payload["items"] if str(item["id"]).startswith(f"{SOURCE_NAME}_"))
    print(f"Wrote {len(payload['items'])} items to {args.dataset}")
    print(f"Imported {imported} ihchina records")


if __name__ == "__main__":
    main()
