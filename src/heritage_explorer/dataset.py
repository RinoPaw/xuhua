"""Dataset loading and normalized in-memory access."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import DATASET_PATH

if TYPE_CHECKING:
    from .extractor import SoftLabels, StructuredMeta


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    item_count: int


def _parse_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


@dataclass(frozen=True)
class HeritageItem:
    id: str
    title: str
    family: str
    category: str
    summary: str
    content: str
    search_text: str
    source: dict[str, Any]
    # ── structured metadata ──
    level: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    display_forms: tuple[str, ...] = ()
    history: str = ""
    features: str = ""
    cultural_value: str = ""
    # ── soft labels ──
    suitable_scenarios: tuple[str, ...] = ()
    target_audience: tuple[str, ...] = ()
    display_difficulty: str = ""
    interaction_potential: str = ""
    education_value: str = ""
    cultural_keywords: tuple[str, ...] = ()


class KnowledgeBase:
    def __init__(self, payload: dict[str, Any]):
        self.schema_version = payload.get("schema_version", 1)
        self.generated_at = payload.get("generated_at", "")
        self.source = payload.get("source", {})
        self.categories = [
            Category(
                id=int(category["id"]),
                name=str(category["name"]),
                item_count=int(category.get("item_count", 0)),
            )
            for category in payload.get("categories", [])
        ]
        self.items = [
            HeritageItem(
                id=str(item["id"]),
                title=str(item["title"]),
                family=str(item.get("family") or ""),
                category=str(item.get("category") or "未分类"),
                summary=str(item.get("summary") or ""),
                content=str(item.get("content") or ""),
                search_text=str(item.get("search_text") or ""),
                source=dict(item.get("source") or {}),
                level=str(item.get("level") or ""),
                province=str(item.get("province") or ""),
                city=str(item.get("city") or ""),
                district=str(item.get("district") or ""),
                display_forms=_parse_tuple(item.get("display_forms")),
                history=str(item.get("history") or ""),
                features=str(item.get("features") or ""),
                cultural_value=str(item.get("cultural_value") or ""),
                suitable_scenarios=_parse_tuple(item.get("suitable_scenarios")),
                target_audience=_parse_tuple(item.get("target_audience")),
                display_difficulty=str(item.get("display_difficulty") or ""),
                interaction_potential=str(item.get("interaction_potential") or ""),
                education_value=str(item.get("education_value") or ""),
                cultural_keywords=_parse_tuple(item.get("cultural_keywords")),
            )
            for item in payload.get("items", [])
        ]
        self._by_id = {item.id: item for item in self.items}

    def get(self, item_id: str) -> HeritageItem | None:
        return self._by_id.get(item_id)

    def category_names(self) -> list[str]:
        return [category.name for category in self.categories]


def load_dataset(path: Path = DATASET_PATH) -> KnowledgeBase:
    with path.open("r", encoding="utf-8") as f:
        return KnowledgeBase(json.load(f))


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    return load_dataset()


def get_structured_meta(item_id: str) -> "StructuredMeta | None":
    """Backward-compatible adapter: build StructuredMeta from HeritageItem fields."""
    from .extractor import StructuredMeta

    kb = get_knowledge_base()
    item = kb.get(item_id)
    if item is None:
        return None
    return StructuredMeta(
        level=item.level,
        province=item.province,
        city=item.city,
        district=item.district,
        display_forms=item.display_forms,
        history=item.history,
        features=item.features,
        cultural_value=item.cultural_value,
    )


def get_soft_labels(item_id: str) -> "SoftLabels | None":
    """Backward-compatible adapter: build SoftLabels from HeritageItem fields."""
    from .extractor import SoftLabels

    kb = get_knowledge_base()
    item = kb.get(item_id)
    if item is None:
        return None
    return SoftLabels(
        suitable_scenarios=item.suitable_scenarios,
        target_audience=item.target_audience,
        display_difficulty=item.display_difficulty,
        interaction_potential=item.interaction_potential,
        education_value=item.education_value,
        cultural_keywords=item.cultural_keywords,
    )


def item_to_dict(item: HeritageItem, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": item.id,
        "title": item.title,
        "family": item.family,
        "category": item.category,
        "summary": item.summary,
        "source": item.source,
        "level": item.level,
        "province": item.province,
        "city": item.city,
        "district": item.district,
        "display_forms": list(item.display_forms),
        "history": item.history,
        "features": item.features,
        "cultural_value": item.cultural_value,
    }
    if include_content:
        data["content"] = item.content
    return data
