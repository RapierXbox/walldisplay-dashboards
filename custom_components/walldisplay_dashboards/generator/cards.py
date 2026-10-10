"""Builders for Lovelace card configs. Pure Python."""

from __future__ import annotations

from typing import Any

from ..const import PAGE_MORE, SECURE_COVER_CLASSES, SECURE_DOMAINS
from ..layout import widen_last_line
from ..models import EntityInfo
from .labels import label

Card = dict[str, Any]

# Body tap toggles these (window covers only; secure covers are excluded below).
TOGGLE_DOMAINS = frozenset({"light", "switch", "fan", "cover", "input_boolean"})
ACTION_DOMAINS = {"scene": "scene.turn_on", "script": "script.turn_on"}
# Scene/script icons by name, used only when the entity has no icon (U14).
ACTION_ICON_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cook", "koch"), "mdi:pot-steam"),
    (("dinner", "essen"), "mdi:silverware-fork-knife"),
    (("breakfast", "frühstück"), "mdi:coffee"),
    (("movie", "film", "tv", "kino"), "mdi:movie-open"),
    (("relax", "entspann"), "mdi:sofa"),
    (("read", "lesen"), "mdi:book-open-variant"),
    (("night", "nacht", "sleep", "schlaf"), "mdi:weather-night"),
    (("morning", "morgen"), "mdi:weather-sunset-up"),
    (("away", "abwesend", "leave"), "mdi:home-export-outline"),
    (("arrive", "ankommen"), "mdi:home-import-outline"),
    (("all off", "alles aus"), "mdi:power"),
    (("party",), "mdi:party-popper"),
    (("clean", "putzen"), "mdi:broom"),
    (("bright", "hell"), "mdi:brightness-7"),
    (("dim", "gedimmt"), "mdi:brightness-4"),
)
WEATHER_TEXT_MIN_PX = 200  # narrower horizontal weather tiles show the temperature only
TILE_TEXT_INSET_PX = 72  # tile padding + icon + gap before the text
# WeatherEntityFeature: FORECAST_DAILY 1, FORECAST_HOURLY 2, FORECAST_TWICE_DAILY 4.
FORECAST_TYPES = ((2, "hourly"), (1, "daily"), (4, "twice_daily"))
COVER_OPEN_CLOSE = 1 | 2  # CoverEntityFeature.OPEN | CLOSE

DATE_LONG = ["weekday-long", "day-numeric", "month-long"]
DATE_SHORT = ["weekday-short", "day-numeric", "month-short"]

FEATURE_MIN_ROWS = 3  # tiles this tall get an inline control (U15)

MORE_INFO = {"action": "more-info"}


def grid_options(columns: int, rows: int) -> dict[str, int]:
    """Exact size in the section grid.

    min_* is set as well because cards report their own minimum (tile and
    shortcut: 6 columns) and the frontend clamps the requested size up to it.
    """
    return {"columns": columns, "rows": rows, "min_columns": columns, "min_rows": rows}


def sized(card: Card, columns: int, rows: int) -> Card:
    """Return the card with grid_options attached."""
    return {**card, "grid_options": grid_options(columns, rows)}


def card_rows(card: Card) -> int:
    return int(card.get("grid_options", {}).get("rows", 1))


def card_columns(card: Card, full: int = 12) -> int:
    columns = card.get("grid_options", {}).get("columns", 12)
    return full if columns == "full" else int(columns)


def widen_block(card_list: list[Card], total_columns: int, first: int = 0) -> list[Card]:
    """Apply layout.widen_last_line to the cards from index `first` on."""
    spans = [(card_columns(c, total_columns), card_rows(c)) for c in card_list]
    widened = widen_last_line(spans, total_columns, first)
    result = []
    for card, old, new in zip(card_list, spans, widened, strict=True):
        if new != old:
            options = {**card["grid_options"], "columns": new[0], "min_columns": new[0]}
            card = {**card, "grid_options": options}
        result.append(card)
    return result


def is_secure(entity: EntityInfo) -> bool:
    """Locks, alarms, valves, sirens and garage/gate/door covers: never one-tap."""
    return entity.domain in SECURE_DOMAINS or (
        entity.domain == "cover" and entity.device_class in SECURE_COVER_CLASSES
    )


def tile(entity_id: str, name: str | None = None, **extra: Any) -> Card:
    card: Card = {"type": "tile", "entity": entity_id}
    if name:
        card["name"] = name
    card.update(extra)
    return card


def secure_tile(entity: EntityInfo, *, vertical: bool = False) -> Card:
    """Status only: tap and hold open more-info, the icon does nothing, no features."""
    card = tile(
        entity.entity_id,
        entity.name,
        tap_action=dict(MORE_INFO),
        icon_tap_action={"action": "none"},
        hold_action=dict(MORE_INFO),
    )
    if vertical:
        card["vertical"] = True
    return card


def action_tile(entity: EntityInfo, *, vertical: bool = False) -> Card:
    """Scene or script tile: tap (body or icon) runs it; scenes hide their state."""
    action = {
        "action": "perform-action",
        "perform_action": ACTION_DOMAINS.get(entity.domain, f"{entity.domain}.turn_on"),
        "target": {"entity_id": entity.entity_id},
    }
    card = tile(entity.entity_id, entity.name)
    if not entity.icon:
        card["icon"] = action_icon(entity.name)
    if vertical:
        card["vertical"] = True
    if entity.domain == "scene":
        card["hide_state"] = True
    card.update(tap_action=action, icon_tap_action=dict(action), hold_action={"action": "none"})
    return card


def action_icon(name: str) -> str:
    """Icon for a scene/script without its own: first keyword match (en + de)."""
    folded = name.casefold()
    for keywords, icon in ACTION_ICON_KEYWORDS:
        if any(keyword in folded for keyword in keywords):
            return icon
    return "mdi:palette"


def _features(entity: EntityInfo) -> list[dict[str, Any]]:
    if entity.domain == "light" and getattr(entity, "dimmable", False):
        return [{"type": "light-brightness"}]
    if entity.domain == "cover" and entity.supported_features & COVER_OPEN_CLOSE:
        return [{"type": "cover-open-close"}]
    return []


def entity_card(entity: EntityInfo, rows: int, *, features: bool = True) -> Card:
    """Home/More card for one entity at the given height (features: U15)."""
    vertical = rows >= 2
    if is_secure(entity):
        return secure_tile(entity, vertical=vertical)
    if entity.domain in ACTION_DOMAINS:
        return action_tile(entity, vertical=vertical)
    card = tile(entity.entity_id, entity.name)
    if vertical:
        card["vertical"] = True
    if entity.domain in TOGGLE_DOMAINS:
        card["tap_action"] = {"action": "toggle"}
        card["hold_action"] = dict(MORE_INFO)
        if entity.domain == "cover":
            # HA leaves cover icons inert (no circle); circle = pressable.
            card["icon_tap_action"] = {"action": "toggle"}
    elif entity.domain == "climate":
        card["state_content"] = ["current_temperature", "hvac_action"]
    elif entity.domain == "person":
        card["show_entity_picture"] = True
    if features and rows >= FEATURE_MIN_ROWS and (inline := _features(entity)):
        card["features"] = inline
    return card


def more_shortcut(language: str, count: int, *, vertical: bool = False) -> Card:
    """'+N more' slot that opens the More view (relative path)."""
    card: Card = {
        "type": "shortcut",
        "label": label(language, "more_n", n=count),
        "icon": "mdi:dots-horizontal",
        "tap_action": {"action": "navigate", "navigation_path": PAGE_MORE},
    }
    if vertical:
        card["vertical"] = True
    return card


def overflow_slot(
    placed: list[Card], hidden: list[EntityInfo], shown: list[EntityInfo], language: str
) -> tuple[list[Card], list[EntityInfo]]:
    """If entities are left over, turn the last placed tile into "+N more".

    `placed` are the cards of `shown` (same order, at the end of the list).
    Returns the cards and the entities that go to the More view.
    """
    if not hidden or not shown:
        return placed, hidden
    last = placed[-1]
    overflow = [shown[-1], *hidden]
    more = more_shortcut(language, len(overflow), vertical=bool(last.get("vertical")))
    more["grid_options"] = dict(last["grid_options"])
    return [*placed[:-1], more], overflow


def clock(size: str, date_format: list[str] | None = None) -> Card:
    card: Card = {"type": "clock", "clock_size": size, "no_background": True}
    if date_format:
        card["date_format"] = list(date_format)
    return card


def weather_tile(
    entity_id: str, language: str, *, vertical: bool = False, width_px: float | None = None
) -> Card:
    """Temperature first, so truncation cuts the condition and keeps the number.

    A narrow horizontal tile shows the temperature only; its icon shows the
    condition.
    """
    narrow = width_px is not None and width_px - TILE_TEXT_INSET_PX < WEATHER_TEXT_MIN_PX
    content = ["temperature"] if narrow and not vertical else ["temperature", "state"]
    card = tile(entity_id, label(language, "outside"), state_content=content)
    if vertical:
        card["vertical"] = True
    return card


def forecast_type(weather_features: int) -> str | None:
    """The forecast the weather entity provides, or None (then no forecast card)."""
    for bit, kind in FORECAST_TYPES:
        if weather_features & bit:
            return kind
    return None


def forecast(entity_id: str, weather_features: int) -> Card | None:
    kind = forecast_type(weather_features)
    if kind is None:
        return None
    return {
        "type": "weather-forecast",
        "entity": entity_id,
        "show_current": False,
        "show_forecast": True,
        "forecast_type": kind,
    }


def area_card(
    area_id: str,
    controls: list[str],
    *,
    sensor_classes: list[str] | None = None,
    exclude_entities: list[str] | None = None,
) -> Card:
    """Native room card: name, temperature/humidity, open-window badge, master switch.

    `exclude_entities` keeps entities out of its sensor values and controls.
    """
    card: Card = {
        "type": "area",
        "area": area_id,
        "display_type": "compact",
        "sensor_classes": (
            list(sensor_classes) if sensor_classes is not None else ["temperature", "humidity"]
        ),
        "alert_classes": ["window", "door", "moisture"],
    }
    if exclude_entities:
        card["exclude_entities"] = list(exclude_entities)
    if controls:
        card["features"] = [{"type": "area-controls", "controls": list(controls)}]
        card["features_position"] = "bottom"
    return card


def area_card_rows(card: Card) -> int:
    return 2 if card.get("features") else 1


def summary_cards(
    lights: tuple[str, ...], openings: tuple[str, ...], secure: bool, *, vertical: bool = False
) -> list[Card]:
    """Native home-summary cards: lights on, and security (locks, alarm, openings).

    Localised by HA and laid out like tiles (vertical in slots of 2+ rows);
    they have no tap action.
    """
    result: list[Card] = []
    if lights:
        result.append({"type": "home-summary", "summary": "light"})
    if openings or secure:
        card: Card = {"type": "home-summary", "summary": "security"}
        if openings:
            card["alert_entities"] = [{"entity": entity_id} for entity_id in openings]
        result.append(card)
    if vertical:
        result = [{**card, "vertical": True} for card in result]
    return result


def referenced_entities(node: Any) -> set[str]:
    """Every entity id a card config refers to (entity keys and action targets)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity", "entity_id") and isinstance(value, str):
                found.add(value)
            elif key == "entity_id" and isinstance(value, list):
                found.update(v for v in value if isinstance(v, str))
            else:
                found |= referenced_entities(value)
    elif isinstance(node, list):
        for item in node:
            found |= referenced_entities(item)
    return found
