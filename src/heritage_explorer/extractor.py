"""Structured metadata extraction for heritage items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .dataset import HeritageItem, KnowledgeBase


META_PATH = PROJECT_ROOT / "data/processed/heritage_meta.json"
LABELS_PATH = PROJECT_ROOT / "data/processed/heritage_labels.json"
SCHEMA_VERSION = 2

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
    r"[一-鿿]{2,7}省"
    r")"
)


@dataclass(frozen=True)
class FieldEvidence:
    """Provenance metadata for a single extracted field."""

    source_text: str = ""
    method: str = ""  # "rule" / "rule_infer" / "llm" / "manual"
    confidence: float = 0.0


def _evidence_dict(
    source_text: str = "",
    method: str = "rule",
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "source_text": source_text,
        "method": method,
        "confidence": confidence,
    }


def _maybe_evidence(fields: dict[str, tuple[str, ...]], name: str, confidence: float = 0.8) -> dict[str, Any]:
    values = fields.get(name) or ()
    source_text = values[0] if values else ""
    return _evidence_dict(source_text=source_text, method="rule", confidence=confidence if source_text else 0.0)


# ---------------------------------------------------------------------------
# Stable structured metadata (rule-based extraction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredMeta:
    """Stable metadata extracted from the source content."""

    level: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    inheritors: tuple[str, ...] = ()
    coordinates: tuple[float, float] | None = None
    display_forms: tuple[str, ...] = ()
    organization: str = ""
    history: str = ""
    features: str = ""
    cultural_value: str = ""
    _evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Soft labels (AI-assisted, MVP rule-inferred)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoftLabels:
    """AI-assisted soft labels for downstream recommendation tasks."""

    suitable_scenarios: tuple[str, ...] = ()
    target_audience: tuple[str, ...] = ()
    display_difficulty: str = ""
    interaction_potential: str = ""
    creative_product_potential: str = ""
    education_value: str = ""
    cultural_keywords: tuple[str, ...] = ()
    _evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def structured_meta_to_dict(meta: StructuredMeta) -> dict[str, Any]:
    return {
        "level": meta.level,
        "province": meta.province,
        "city": meta.city,
        "district": meta.district,
        "inheritors": list(meta.inheritors),
        "coordinates": list(meta.coordinates) if meta.coordinates else None,
        "display_forms": list(meta.display_forms),
        "organization": meta.organization,
        "history": meta.history,
        "features": meta.features,
        "cultural_value": meta.cultural_value,
        "_evidence": meta._evidence,
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
        inheritors=tuple(str(v) for v in data.get("inheritors") or ()),
        coordinates=parsed_coordinates,
        display_forms=tuple(str(v) for v in data.get("display_forms") or ()),
        organization=str(data.get("organization") or ""),
        history=str(data.get("history") or ""),
        features=str(data.get("features") or ""),
        cultural_value=str(data.get("cultural_value") or ""),
        _evidence=_unpack_evidence(data.get("_evidence")),
    )


def soft_labels_to_dict(labels: SoftLabels) -> dict[str, Any]:
    return {
        "suitable_scenarios": list(labels.suitable_scenarios),
        "target_audience": list(labels.target_audience),
        "display_difficulty": labels.display_difficulty,
        "interaction_potential": labels.interaction_potential,
        "creative_product_potential": labels.creative_product_potential,
        "education_value": labels.education_value,
        "cultural_keywords": list(labels.cultural_keywords),
        "_evidence": labels._evidence,
    }


def soft_labels_from_dict(data: dict[str, Any]) -> SoftLabels:
    return SoftLabels(
        suitable_scenarios=tuple(str(v) for v in data.get("suitable_scenarios") or ()),
        target_audience=tuple(str(v) for v in data.get("target_audience") or ()),
        display_difficulty=str(data.get("display_difficulty") or ""),
        interaction_potential=str(data.get("interaction_potential") or ""),
        creative_product_potential=str(data.get("creative_product_potential") or ""),
        education_value=str(data.get("education_value") or ""),
        cultural_keywords=tuple(str(v) for v in data.get("cultural_keywords") or ()),
        _evidence=_unpack_evidence(data.get("_evidence")),
    )


def _unpack_evidence(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    evidence: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            evidence[str(key)] = {
                "source_text": str(value.get("source_text") or ""),
                "method": str(value.get("method") or ""),
                "confidence": float(value.get("confidence") or 0.0),
            }
    return evidence


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------


class RuleExtractor:
    """Extract deterministic metadata fields with regex rules."""

    def extract(self, item: HeritageItem) -> StructuredMeta:
        fields = _extract_all_fields(item.content)
        province = _province_from_region(_first_value(fields, "报道地区")) or _first_value(
            fields, "省份"
        )

        evidence: dict[str, dict[str, Any]] = {}

        level_val, level_ev = _extract_level(fields)
        evidence["level"] = level_ev

        prov_ev = _evidence_dict(
            source_text=province,
            method="rule",
            confidence=0.95 if province else 0.0,
        )
        evidence["province"] = prov_ev

        city_val = _first_value(fields, "城市")
        evidence["city"] = _evidence_dict(
            source_text=city_val,
            method="rule",
            confidence=0.95 if city_val else 0.0,
        )

        district_val = _first_value(fields, "地区")
        # district evidence stored as part of city group – skip standalone to keep lean

        features_val = _first_value(fields, "主要特色")
        evidence["features"] = _evidence_dict(
            source_text=features_val,
            method="rule",
            confidence=0.8 if features_val else 0.0,
        )

        cv_val = _first_value(fields, "重要价值")
        evidence["cultural_value"] = _evidence_dict(
            source_text=cv_val,
            method="rule",
            confidence=0.8 if cv_val else 0.0,
        )

        return StructuredMeta(
            level=level_val,
            province=province,
            city=city_val,
            district=district_val,
            inheritors=_split_people(_first_value(fields, "传承人")),
            coordinates=_extract_coordinates(fields.get("经纬度", ())),
            display_forms=_unique_values(fields.get("展示形式", ())),
            organization=_first_value(fields, "保护单位") or _first_value(fields, "联系"),
            history=_first_value(fields, "历史") or _first_value(fields, "主要时间"),
            features=features_val,
            cultural_value=cv_val,
            _evidence=evidence,
        )

    def extract_batch(self, items: list[HeritageItem]) -> dict[str, StructuredMeta]:
        return {item.id: self.extract(item) for item in items}


def _extract_level(fields: dict[str, tuple[str, ...]]) -> tuple[str, dict[str, Any]]:
    value = _first_value(fields, "归属")
    mapped = _normalize_level(value)
    confidence = 1.0 if mapped else 0.0
    return mapped, _evidence_dict(source_text=value, method="rule", confidence=confidence)


def _normalize_level(raw: str) -> str:
    if not raw:
        return ""
    if "人类" in raw:
        return "人类"
    if "国家" in raw:
        return "国家级"
    if "省" in raw and "级" in raw:
        return "省级"
    if raw in ("国家级", "省级", "人类"):
        return raw
    return raw


# ---------------------------------------------------------------------------
# MVP SoftLabels rule inference
# ---------------------------------------------------------------------------


_CATEGORY_SCENARIO_MAP: dict[str, tuple[str, ...]] = {
    "传统技艺": ("研学体验", "文创设计", "社区活动"),
    "传统戏剧": ("校园展示", "展馆讲解", "社区活动"),
    "传统舞蹈": ("校园展示", "社区活动", "研学体验"),
    "民俗": ("社区活动", "校园展示", "研学体验"),
    "传统美术": ("文创设计", "展馆讲解", "校园展示"),
    "传统医药": ("研学体验", "展馆讲解"),
    "传统体育、游艺与杂技": ("校园展示", "社区活动", "研学体验"),
    "曲艺": ("展馆讲解", "校园展示"),
    "民间文学": ("研学活动", "校园展示"),
    "传统音乐": ("校园展示", "展馆讲解", "社区活动"),
}
_DEFAULT_SCENARIOS: tuple[str, ...] = ("校园展示", "社区活动", "研学体验")

_CATEGORY_CREATIVE_MAP: dict[str, str] = {
    "传统技艺": "高",
    "传统美术": "高",
    "传统戏剧": "中",
    "传统舞蹈": "中",
    "曲艺": "中",
    "民俗": "中",
    "民间文学": "中",
    "传统音乐": "中",
    "传统体育、游艺与杂技": "中",
    "传统医药": "低",
}


def _infer_display_difficulty(display_forms: tuple[str, ...]) -> str:
    text = " ".join(display_forms)
    if not text:
        return ""
    if any(t in text for t in ("制作", "技艺", "流程")):
        return "高"
    if any(t in text for t in ("表演", "演出", "演唱")):
        return "中"
    return "低"


def _infer_interaction_potential(display_forms: tuple[str, ...]) -> str:
    text = " ".join(display_forms)
    if not text:
        return ""
    if any(t in text for t in ("互动", "体验", "推手", "参与", "实操")):
        return "高"
    if any(t in text for t in ("表演", "演出", "演唱", "演示")):
        return "中"
    return "低"


def _infer_education_value(level: str) -> str:
    if level in ("人类", "国家级"):
        return "高"
    if level == "省级":
        return "中"
    return ""


def _infer_audience_from_scenarios(scenarios: tuple[str, ...]) -> tuple[str, ...]:
    audience: list[str] = []
    for scenario in scenarios:
        if "校园" in scenario:
            audience.append("中小学生")
        if "研学" in scenario:
            audience.append("大学生")
        if "社区" in scenario:
            audience.append("社区居民")
        if "文创" in scenario:
            audience.append("设计师")
        if "展馆" in scenario:
            audience.append("游客")
    return tuple(dict.fromkeys(audience))


def _extract_cultural_keywords(item: HeritageItem, features: str) -> tuple[str, ...]:
    keywords: list[str] = []
    text = f"{item.category} {features} {item.summary[:200]}"
    # extract 2-4 char Chinese nouns as candidate keywords
    candidates = re.findall(r"[一-鿿]{2,6}", text)
    seen: set[str] = set()
    for candidate in candidates:
        if len(candidate) >= 3 and candidate not in seen:
            seen.add(candidate)
            keywords.append(candidate)
        if len(keywords) >= 10:
            break
    return tuple(keywords)


def infer_soft_labels(item: HeritageItem, meta: StructuredMeta) -> SoftLabels:
    category = item.category
    scenarios = _CATEGORY_SCENARIO_MAP.get(category, _DEFAULT_SCENARIOS)
    audience = _infer_audience_from_scenarios(scenarios)
    difficulty = _infer_display_difficulty(meta.display_forms)
    interaction = _infer_interaction_potential(meta.display_forms)
    education = _infer_education_value(meta.level)
    creative = _CATEGORY_CREATIVE_MAP.get(category, "")
    keywords = _extract_cultural_keywords(item, meta.features)

    evidence: dict[str, dict[str, Any]] = {}
    evidence["suitable_scenarios"] = _evidence_dict(
        source_text=f"category={category}",
        method="rule_infer",
        confidence=0.6 if scenarios else 0.0,
    )
    evidence["target_audience"] = _evidence_dict(
        source_text=f"scenarios={scenarios}",
        method="rule_infer",
        confidence=0.5 if audience else 0.0,
    )

    return SoftLabels(
        suitable_scenarios=scenarios,
        target_audience=audience,
        display_difficulty=difficulty,
        interaction_potential=interaction,
        creative_product_potential=creative,
        education_value=education,
        cultural_keywords=keywords,
        _evidence=evidence,
    )


# ---------------------------------------------------------------------------
# LLM labeler (skeleton — future phase)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Extraction cache
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Build entry points
# ---------------------------------------------------------------------------


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


def build_rule_soft_labels(
    kb: KnowledgeBase,
    meta: dict[str, StructuredMeta],
    cache: ExtractionCache | None = None,
) -> dict[str, SoftLabels]:
    labels = {
        item.id: infer_soft_labels(item, meta.get(item.id, StructuredMeta()))
        for item in kb.items
    }
    target_cache = cache or ExtractionCache()
    target_cache.save(
        meta,
        labels=labels,
        dataset_generated_at=kb.generated_at,
        dataset_schema_version=kb.schema_version,
    )
    return labels


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
