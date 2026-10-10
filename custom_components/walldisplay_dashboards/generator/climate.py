"""Climate page: the room's primary climate as a native thermostat card.

The thermostat shows its -/+ buttons only while the dial is at least 250 px
(U16), so features go on the card only while it stays tall enough:
- square: thermostat over all rows, no features;
- landscape: thermostat about two thirds wide; when it is too short for
  features, a "Mode" tile with the hvac modes goes into the side column, next
  to the room humidity and any other climates; the side tiles share all rows
  (vertical from 2 rows; the Mode tile from 3). With exactly one side card,
  the thermostat spans the full width and the card becomes a 1-row strip;
- portrait: thermostat on top (with features), humidity and other climates as
  small tiles below.
No second room temperature: the thermostat already shows it (U3), unless
the options name a room temperature sensor; then it is a tile like humidity.
"""

from __future__ import annotations

import math
from typing import Any

from ..const import MIN_HORIZONTAL_TILE_PX, PAGE_CLIMATE
from ..layout import (
    TileFill,
    card_column_px,
    rows_px,
    side_split,
    span_px,
)
from ..models import EntityInfo, GeneratorInput, Grid
from . import cards
from .cards import Card
from .info import ClimateInfo
from .labels import label
from .room import page_entities, room_humidity, room_temperature

__all__ = ["ClimateInfo", "below_split", "climate_plan", "side_column"]

DIAL_CARD_MIN_PX = 330  # card height that keeps a 250 px dial plus name and padding
DIAL_MIN_WIDTH_PX = 300
MIN_DIAL_ROWS = 4
MAX_ICON_PRESETS = 4
FEATURE_ROW_PX = 64
SIDE_MAX_ROWS = 3  # side tiles share all rows, each at most this tall


def feature_rows(features: list[dict[str, Any]]) -> int:
    """Rows the thermostat card adds for its features (hui-thermostat-card)."""
    return math.ceil(len(features) * 2 / 3) if features else 0


def hvac_feature(entity: EntityInfo) -> dict[str, Any] | None:
    modes = list(getattr(entity, "hvac_modes", ()))
    if len(modes) < 2:
        return None
    return {"type": "climate-hvac-modes", "style": "icons", "hvac_modes": modes}


def preset_feature(entity: EntityInfo) -> dict[str, Any] | None:
    presets = list(getattr(entity, "preset_modes", ()))
    if not presets:
        return None
    style = "icons" if len(presets) <= MAX_ICON_PRESETS else "dropdown"
    return {"type": "climate-preset-modes", "style": style, "preset_modes": presets}


def dial_fits(rows: int, width_px: float, features: list[dict[str, Any]]) -> bool:
    height = rows_px(rows) - FEATURE_ROW_PX * feature_rows(features)
    return height >= DIAL_CARD_MIN_PX and width_px >= DIAL_MIN_WIDTH_PX


def thermostat(entity: EntityInfo, name: str, rows: int, width_px: float) -> tuple[Card, bool]:
    """Thermostat card with the features that keep the dial usable.

    Returns the card and whether the hvac modes had to be left off.
    """
    hvac, preset = hvac_feature(entity), preset_feature(entity)
    features: list[dict[str, Any]] = []
    for feature in (hvac, preset):
        if feature and dial_fits(rows, width_px, [*features, feature]):
            features.append(feature)
    card: Card = {"type": "thermostat", "entity": entity.entity_id, "name": name}
    if features:
        card["features"] = features
    return card, hvac is not None and hvac not in features


def _climate_tile(entity: EntityInfo, vertical: bool) -> Card:
    card = cards.tile(
        entity.entity_id, entity.name, state_content=["current_temperature", "hvac_action"]
    )
    if vertical:
        card["vertical"] = True
    return card


def _mode_tile(entity: EntityInfo, language: str) -> Card:
    return cards.tile(
        entity.entity_id,
        label(language, "mode"),
        hide_state=True,
        features=[hvac_feature(entity)],
    )


def room_values(data: GeneratorInput) -> list[Card]:
    """Room sensor tiles: the chosen temperature (option only, U3), then humidity."""
    result: list[Card] = []
    temperature = room_temperature(data) if data.display.overrides.temperature_entity else None
    for entity_id, key in ((temperature, "temperature"), (room_humidity(data), "humidity")):
        if entity_id:
            result.append(cards.tile(entity_id, label(data.language, key)))
    return result


def side_column(items: int, rows: int) -> tuple[int, int]:
    """(tile rows, count) for a one-tile-wide side column."""
    if not items or rows <= 0:
        return 1, 0
    height = max(1, min(2, rows // items))
    return height, min(items, rows // height)


def share_rows(minimum: list[int], rows: int, cap: int = SIDE_MAX_ROWS) -> list[int]:
    """Share `rows` among side tiles: each keeps its minimum, then one more row
    at a time round-robin, at most `cap` each."""
    heights = list(minimum)
    spare = rows - sum(heights)
    while spare > 0 and any(h < cap for h in heights):
        for index, height in enumerate(heights):
            if spare and height < cap:
                heights[index] += 1
                spare -= 1
    return heights


def below_split(
    n: int, total: int, rows: int, column_px: float, min_main: int
) -> tuple[int, TileFill]:
    """Rows for a main card on top and small tiles (1-2 rows, up to 3 a row) below."""
    if n <= 0 or rows - min_main <= 0:
        return rows, TileFill(0, total, 1, 1)
    per_row = 1
    for candidate in (3, 2):
        if (
            candidate <= n
            and total % candidate == 0
            and span_px(total // candidate, column_px) >= MIN_HORIZONTAL_TILE_PX
        ):
            per_row = candidate
            break
    lines = math.ceil(n / per_row)
    height = 2 if rows - lines * 2 >= min_main else 1
    lines = min(lines, (rows - min_main) // height)
    count = min(n, lines * per_row)
    if count == 0:
        return rows, TileFill(0, total, 1, 1)
    return rows - lines * height, TileFill(count, total // per_row, height, per_row)


def climate_plan(data: GeneratorInput, grid: Grid) -> tuple[list[Card], list[EntityInfo]]:
    """Cards of the climate section and the climates that did not fit (for More)."""
    entities = page_entities(data, PAGE_CLIMATE)
    if not entities or grid.rows <= 0:
        return [], []
    primary, others = entities[0], entities[1:]
    # A thermostat from another room (options) keeps its own name.
    in_room = primary.area_id == data.display.area_id
    name = data.area_name if not others and in_room else primary.name
    profile = data.display.profile
    column_px = card_column_px(profile)
    total, rows = grid.card_columns, grid.rows
    values = room_values(data)

    if profile.orientation == "landscape":
        main, side = side_split(profile, total)
        card, modes_dropped = thermostat(primary, name, rows, span_px(main, column_px))
        side_cards: list[tuple[Card, int]] = []
        if modes_dropped:
            side_cards.append((_mode_tile(primary, data.language), 2))
        side_cards += [(value, 1) for value in values]
        if not side or not (side_cards or others):
            card, _ = thermostat(primary, name, rows, span_px(total, column_px))
            return [cards.sized(card, total, rows)], others  # no room for a "+N more"
        used = sum(r for _, r in side_cards)
        while used > rows and side_cards:
            used -= side_cards.pop()[1]
        _, count = side_column(len(others), rows - used)
        items = side_cards + [(_climate_tile(e, False), 1) for e in others[:count]]
        if len(items) == 1 and count == len(others) and rows >= 2:
            # One side card (C1): full-width thermostat over a 1-row strip.
            strip = items[0][0]
            card, dropped = thermostat(primary, name, rows - 1, span_px(total, column_px))
            if modes_dropped and not dropped:  # the thermostat carries the modes now
                card, _ = thermostat(primary, name, rows, span_px(total, column_px))
                return [cards.sized(card, total, rows)], []
            if strip.get("features"):
                strip = {**strip, "features_position": "inline"}
            return [cards.sized(card, total, rows - 1), cards.sized(strip, total, 1)], []
        cap = max(SIDE_MAX_ROWS, math.ceil(rows / len(items))) if items else SIDE_MAX_ROWS
        heights = share_rows([r for _, r in items], rows, cap)
        result = [cards.sized(card, main, rows)]
        for (tile, _), height in zip(items, heights, strict=True):
            if height >= 2 and not (tile.get("features") and height < 3):
                tile = {**tile, "vertical": True}
            result.append(cards.sized(tile, side, height))
        return cards.overflow_slot(result, others[count:], others[:count], data.language)

    width_px = span_px(total, column_px)
    if profile.orientation == "portrait":
        n_extra = len(others) + len(values)
    else:
        n_extra = len(others)  # square: the thermostat alone, extra climates below
    main_rows, fill = below_split(n_extra, total, rows, column_px, MIN_DIAL_ROWS)
    if profile.orientation == "square":
        card = {"type": "thermostat", "entity": primary.entity_id, "name": name}
    else:
        card, _ = thermostat(primary, name, main_rows, width_px)
    result = [cards.sized(card, total, main_rows)]
    extras: list[Card] = []
    vertical = fill.rows >= 2
    if profile.orientation == "portrait":
        extras += [{**value, "vertical": True} if vertical else value for value in values]
    shown_others = others[: max(0, fill.count - len(extras))]
    extras += [_climate_tile(e, vertical) for e in shown_others]
    result += [cards.sized(c, fill.columns, fill.rows) for c in extras[: fill.count]]
    return cards.overflow_slot(result, others[len(shown_others) :], shown_others, data.language)
