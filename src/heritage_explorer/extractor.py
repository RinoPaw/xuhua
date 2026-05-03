"""Structured metadata extraction for heritage items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .dataset import HeritageItem, KnowledgeBase


META_PATH = PROJECT_ROOT / "data/processed/heritage_meta.json"
LABELS_PATH = PROJECT_ROOT / "data/processed/heritage_labels.json"
SCHEMA_VERSION = 1

_FIELD_NAMES = (
    "序号",
    "标题",
    "归属",
    "类别",
    "城市",
    "地区",
    "报道地区",
    "介绍",
    "重大地区",
    "主要特色",
    "重要价值",
    "传承人",
    "企业",
    "展示形式",
    "联系",
    "电话",
    "省份",
    "地点",
    "面积",
    "operation",
    "经纬度",
    "历史",
    "主要时间",
    "内容",
    "保护单位",
)
_FIELD_STOP_PATTERN = "|".join(re.escape(name) for name in _FIELD_NAMES)
_PROVINCE_PATTERN = re.compile(
    r"("
    r"北京市|天津市|上海市|重庆市|"
    r"香港特别行政区|澳门特别行政区|"
    r"内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|"
    r"[\u4e00-\u9fff]{2,7}省"
    r")"
)


@dataclass(frozen=True)
class StructuredMeta:
    """Stable metadata extracted from the source content."""

    level: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    inheritors: tuple[str, ...] = ()
    coordinates: tuple[float, float] | None = None
    exhibition_types: tuple[str, ...] = ()
    organization: str = ""


@dataclass(frozen=True)
class SoftLabels:
    """LLM-assigned soft labels for downstream recommendation tasks."""

    suitable_scenarios: tuple[str, ...] = ()
    target_audience: tuple[str, ...] = ()
    interactivity: str = ""
    visual_richness: str = ""
    creative_potential: str = ""
    educational_value: str = ""
    cultural_keywords: tuple[str, ...] = ()
    exhibition_difficulty: str = ""


def structured_meta_to_dict(meta: StructuredMeta) -> dict[str, Any]:
    return {
        "level": meta.level,
        "province": meta.province,
        "city": meta.city,
        "district": meta.district,
        "inheritors": list(meta.inheritors),
        "coordinates": list(meta.coordinates) if meta.coordinates else None,
        "exhibition_types": list(meta.exhibition_types),
        "organization": meta.organization,
    }


def structured_meta_from_dict(data: dict[str, Any]) -> StructuredMeta:
    coordinates = data.get("coordinates")
    parsed_coordinates = None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) == 2:
        try:
            parsed_coordinates = (float(coordinates[0]), float(coordinates[1]))
        except (TypeError, ValueError):
            parsed_coordinates = None

    return StructuredMeta(
        level=str(data.get("level") or ""),
        province=str(data.get("province") or ""),
        city=str(data.get("city") or ""),
        district=str(data.get("district") or ""),
        inheritors=tuple(str(value) for value in data.get("inheritors") or ()),
        coordinates=parsed_coordinates,
        exhibition_types=tuple(str(value) for value in data.get("exhibition_types") or ()),
        organization=str(data.get("organization") or ""),
    )


def soft_labels_to_dict(labels: SoftLabels) -> dict[str, Any]:
    return {
        "suitable_scenarios": list(labels.suitable_scenarios),
        "target_audience": list(labels.target_audience),
        "interactivity": labels.interactivity,
        "visual_richness": labels.visual_richness,
        "creative_potential": labels.creative_potential,
        "educational_value": labels.educational_value,
        "cultural_keywords": list(labels.cultural_keywords),
        "exhibition_difficulty": labels.exhibition_difficulty,
    }


def soft_labels_from_dict(data: dict[str, Any]) -> SoftLabels:
    return SoftLabels(
        suitable_scenarios=tuple(str(value) for value in data.get("suitable_scenarios") or ()),
        target_audience=tuple(str(value) for value in data.get("target_audience") or ()),
        interactivity=str(data.get("interactivity") or ""),
        visual_richness=str(data.get("visual_richness") or ""),
        creative_potential=str(data.get("creative_potential") or ""),
        educational_value=str(data.get("educational_value") or ""),
        cultural_keywords=tuple(str(value) for value in data.get("cultural_keywords") or ()),
        exhibition_difficulty=str(data.get("exhibition_difficulty") or ""),
    )


class RuleExtractor:
    """Extract deterministic metadata fields with regex rules."""

    def extract(self, item: HeritageItem) -> StructuredMeta:
        fields = _extract_all_fields(item.content)
        province = _province_from_region(_first_value(fields, "报道地区")) or _first_value(
            fields, "省份"
        )

        return StructuredMeta(
            level=_first_value(fields, "归属"),
            province=province,
            city=_first_value(fields, "城市"),
            district=_first_value(fields, "地区"),
            inheritors=_split_people(_first_value(fields, "传承人")),
            coordinates=_extract_coordinates(fields.get("经纬度", ())),
            exhibition_types=_unique_values(fields.get("展示形式", ())),
            organization=_first_value(fields, "保护单位") or _first_value(fields, "联系"),
        )

    def extract_batch(self, items: list[HeritageItem]) -> dict[str, StructuredMeta]:
        return {item.id: self.extract(item) for item in items}


class LLMLabeler:
    """Batch labeler skeleton; actual API use is intentionally deferred."""

    def label_batch(
        self,
        items: list[HeritageItem],
        client: Any | None = None,
        batch_size: int = 20,
    ) -> dict[str, SoftLabels]:
        _ = client, batch_size
        return {item.id: SoftLabels() for item in items}

    def _build_labeling_prompt(self, items: list[HeritageItem]) -> str:
        blocks = [
            f"{index}. {item.title} / {item.category}\n{item.summary or item.content[:300]}"
            for index, item in enumerate(items, start=1)
        ]
        return "\n\n".join(blocks)

    def _parse_labeling_response(self, text: str) -> dict[str, SoftLabels]:
        _ = text
        return {}


class ExtractionCache:
    """JSON cache for rule metadata and optional soft labels."""

    def __init__(
        self,
        meta_path: Path | None = None,
        labels_path: Path | None = None,
    ) -> None:
        self.meta_path = META_PATH if meta_path is None else meta_path
        self.labels_path = LABELS_PATH if labels_path is None else labels_path

    def load(self) -> tuple[dict[str, StructuredMeta], dict[str, SoftLabels]]:
        meta_payload = self._read_payload(self.meta_path)
        labels_payload = self._read_payload(self.labels_path)

        meta = {
            item_id: structured_meta_from_dict(item)
            for item_id, item in dict(meta_payload.get("items") or {}).items()
            if isinstance(item, dict)
        }
        labels = {
            item_id: soft_labels_from_dict(item)
            for item_id, item in dict(labels_payload.get("items") or {}).items()
            if isinstance(item, dict)
        }
        return meta, labels

    def save(
        self,
        meta: dict[str, StructuredMeta],
        labels: dict[str, SoftLabels] | None = None,
        *,
        dataset_generated_at: str = "",
        dataset_schema_version: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.labels_path.parent.mkdir(parents=True, exist_ok=True)

        meta_payload = {
            "schema_version": SCHEMA_VERSION,
            "dataset_generated_at": dataset_generated_at,
            "dataset_schema_version": dataset_schema_version,
            "extracted_at": now,
            "items": {
                item_id: structured_meta_to_dict(item)
                for item_id, item in sorted(meta.items())
            },
        }
        self._write_payload(self.meta_path, meta_payload)

        if labels is not None:
            labels_payload = {
                "schema_version": SCHEMA_VERSION,
                "labeled_at": now,
                "model": "",
                "items": {
                    item_id: soft_labels_to_dict(item)
                    for item_id, item in sorted(labels.items())
                },
            }
            self._write_payload(self.labels_path, labels_payload)

    def is_stale(
        self,
        *,
        dataset_generated_at: str = "",
        dataset_schema_version: int | None = None,
    ) -> bool:
        if not self.meta_path.exists():
            return True

        payload = self._read_payload(self.meta_path)
        if payload.get("schema_version") != SCHEMA_VERSION:
            return True
        if dataset_generated_at and payload.get("dataset_generated_at") != dataset_generated_at:
            return True
        if (
            dataset_schema_version is not None
            and payload.get("dataset_schema_version") != dataset_schema_version
        ):
            return True
        return False

    @staticmethod
    def _read_payload(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_payload(path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")


def build_rule_meta(
    kb: KnowledgeBase,
    cache: ExtractionCache | None = None,
) -> dict[str, StructuredMeta]:
    meta = RuleExtractor().extract_batch(kb.items)
    target_cache = cache or ExtractionCache()
    target_cache.save(
        meta,
        dataset_generated_at=kb.generated_at,
        dataset_schema_version=kb.schema_version,
    )
    return meta


def _extract_all_fields(content: str) -> dict[str, tuple[str, ...]]:
    fields: dict[str, list[str]] = {}
    for field in _FIELD_NAMES:
        pattern = re.compile(
            rf"(?:^|[,，]\s*){re.escape(field)}\s*[:：]\s*"
            rf"(.*?)(?=(?:[,，]\s*(?:{_FIELD_STOP_PATTERN})\s*[:：])|$)",
            re.S,
        )
        values = [
            _clean_value(match.group(1))
            for match in pattern.finditer(content)
            if _clean_value(match.group(1))
        ]
        if values:
            fields[field] = values
    return {key: tuple(value) for key, value in fields.items()}


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n,，")


def _first_value(fields: dict[str, tuple[str, ...]], name: str) -> str:
    values = fields.get(name) or ()
    return values[0] if values else ""


def _province_from_region(region: str) -> str:
    match = _PROVINCE_PATTERN.search(region)
    return match.group(1) if match else ""


def _split_people(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    names = [
        item.strip(" \t\r\n,，、;；")
        for item in re.split(r"[、,，;；\s]+", value)
        if item.strip(" \t\r\n,，、;；")
    ]
    return tuple(dict.fromkeys(names))


def _unique_values(values: tuple[str, ...]) -> tuple[str, ...]:
    parts: list[str] = []
    for value in values:
        parts.extend(
            part.strip(" \t\r\n,，、;；")
            for part in re.split(r"[、;；/]+", value)
            if part.strip(" \t\r\n,，、;；")
        )
    return tuple(dict.fromkeys(parts))


def _extract_coordinates(values: tuple[str, ...]) -> tuple[float, float] | None:
    for value in values:
        match = re.search(
            r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)",
            value,
        )
        if not match:
            continue
        return (float(match.group(1)), float(match.group(2)))
    return None
