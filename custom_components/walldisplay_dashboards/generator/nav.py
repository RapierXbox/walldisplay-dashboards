"""Footer navigation: the floating pill card (custom:wall-display-nav)."""

from __future__ import annotations

from typing import Any

from ..const import NAV
from ..models import Profile
from .labels import nav_label

NAV_CARD = "custom:wall-display-nav"
ITEM_PX = 76
PADDING_PX = 16
SCREEN_MARGIN_PX = 16


def nav_footer(
    pages: list[str],
    profile: Profile,
    language: str = "en",
    entities: dict[str, str] | None = None,
) -> dict[str, Any]:
    """View footer: one pill item per page, with the page's live entity if any.

    Paths are relative view paths. The Climate item carries the primary
    climate (the pill shows its temperature), the Media item the primary player.
    """
    items = []
    for page in pages:
        item: dict[str, Any] = {
            "path": page,
            "label": nav_label(language, page),
            "icon": NAV[page][1],
        }
        if entities and (entity_id := entities.get(page)):
            item["entity"] = entity_id
        items.append(item)
    width = min(len(items) * ITEM_PX + PADDING_PX, profile.width - SCREEN_MARGIN_PX)
    return {"card": {"type": NAV_CARD, "items": items}, "max_width": width}
