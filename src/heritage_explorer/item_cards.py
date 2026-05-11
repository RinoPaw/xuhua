"""Presentation helpers for turning dataset items into UI cards."""

from __future__ import annotations

from typing import Any

from .dataset import get_structured_meta, item_to_dict


def enriched_item_card(item: Any) -> dict[str, Any]:
    """Return item_to_dict enriched with structured metadata for UI cards."""
    card = item_to_dict(item)
    meta = get_structured_meta(item.id)
    if meta:
        card["level"] = meta.level
        card["province"] = meta.province
        card["city"] = meta.city
        card["district"] = meta.district
        card["display_forms"] = list(meta.display_forms)
    return card


# Backward-compatible private alias used while agent.py is being split.
_enriched_item_card = enriched_item_card
