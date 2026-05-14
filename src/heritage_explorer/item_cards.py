"""Presentation helpers for turning dataset items into UI cards."""

from __future__ import annotations

from typing import Any

from .dataset import item_to_dict


def enriched_item_card(item: Any) -> dict[str, Any]:
    """Return item_to_dict enriched with structured metadata for UI cards."""
    card = item_to_dict(item)
    card["level"] = item.level
    card["province"] = item.province
    card["city"] = item.city
    card["district"] = item.district
    card["display_forms"] = list(item.display_forms)
    return card


def title_with_family(item: Any) -> str:
    title = item.title
    family = item.family
    if family and family not in title:
        return f"{title}（{family}）"
    return title


def source_payload(item: Any) -> dict[str, str]:
    return {
        "id": item.id,
        "title": item.title,
        "family": item.family,
        "category": item.category,
    }


# Backward-compatible aliases used while agent modules are being split.
_enriched_item_card = enriched_item_card
_title_with_family = title_with_family
_source_payload = source_payload
