"""Home page: status area (strip or info column) and the room's tiles.

Tiles grow to fill the space up to a cap (6 columns x 2 rows on square and
portrait, 3 rows on landscape); rows left over go to the status area (larger
clock, room card, forecast), never to giant tiles. Every full tile line adds
up to the section width. Items that don't fit (or past 12, or past the
max_home_tiles option) end in a "+N more" slot that opens the More view.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from itertools import takewhile

from ..const import TILE_DOMAIN_RANK
from ..layout import (
    TILE_ABSORB_MAX_ROWS,
    card_column_px,
    fill_tiles,
    grow_tiles,
    span_px,
    tile_max_columns,
    tile_max_rows,
)
from ..models import EntityInfo, GeneratorInput, Grid, Overrides
from . import cards
from .cards import Card
from .room import (
    NaturalKey,
    area_controls,
    home_excluded_domains,
    is_display_own,
    is_entrance,
    leave_home_actions,
    natural_key,
    on_own_page,
    room_card_sensors,
)

MAX_HOME_TILES = 12
FORECAST_MIN_SPARE = 3  # info column: forecast only with this many rows left (U11)
LARGE_CLOCK_MIN_PX = 320  # narrower large clocks cut the long date
WEATHER_VERTICAL_ROWS = 8  # info column: vertical weather tile from this many rows
PORTRAIT_FORECAST_MAX_ROWS = 4
CLOCK_MAX_ROWS = 4  # HA's digital clock card: max_rows 4 (L1)
ROOM_MAX_ROWS = 3
LAST_LINE_EXTRA_MAX = 2  # landscape: up to this many leftover rows go to the last line
PORTRAIT_CLOCK_MAX_ROWS = 3


def rank_entities(entities: Iterable[EntityInfo], overrides: Overrides) -> list[EntityInfo]:
    """Pinned first (in pinned order), then by domain rank (secure last), then by name."""
    hidden = set(overrides.hidden)
    pinned = {entity_id: index for index, entity_id in enumerate(overrides.pinned)}
    unranked = len(TILE_DOMAIN_RANK)

    def key(entity: EntityInfo) -> tuple[int, int, NaturalKey, str]:
        if entity.entity_id in pinned:
            return (0, pinned[entity.entity_id], (), entity.entity_id)
        if cards.is_secure(entity):
            rank = unranked + 1
        elif entity.domain in TILE_DOMAIN_RANK:
            rank = TILE_DOMAIN_RANK.index(entity.domain)
        else:
            rank = unranked
        return (1, rank, natural_key(entity.name), entity.entity_id)

    unique: dict[str, EntityInfo] = {}
    for entity in entities:
        if entity.entity_id not in hidden:
            unique.setdefault(entity.entity_id, entity)
    return sorted(unique.values(), key=key)


def home_items(data: GeneratorInput) -> list[EntityInfo]:
    """Entities for Home tiles, in slot order.

    Entrance: people, house-wide locks/alarms (read-only), leave-home actions,
    then the room. Entities controlled on their own page and the display
    device's own entities are left out.
    """
    domains = home_excluded_domains(data)
    hidden = set(data.display.overrides.hidden)
    result: dict[str, EntityInfo] = {}
    if is_entrance(data):
        for entity in (
            *rank_entities(data.persons, data.display.overrides),
            *rank_entities(data.house_secure, data.display.overrides),
            *leave_home_actions(data),
        ):
            if entity.entity_id not in hidden:
                result.setdefault(entity.entity_id, entity)
    for entity in rank_entities(data.area_entities, data.display.overrides):
        if not on_own_page(data, entity, domains) and not is_display_own(data, entity):
            result.setdefault(entity.entity_id, entity)
    return list(result.values())


@dataclass(slots=True)
class HomePlan:
    cards: list[Card] = field(default_factory=list)
    overflow: list[EntityInfo] = field(default_factory=list)


def _clock_for(rows: int, width_px: float) -> Card:
    """Small with the short date in one row; large only where it fits (>= 320 px)."""
    if rows <= 1:
        return cards.clock("small", cards.DATE_SHORT)
    size = "large" if width_px >= LARGE_CLOCK_MIN_PX else "medium"
    return cards.clock(size, cards.DATE_LONG)


def _clock_weather(data: GeneratorInput, grid: Grid, rows: int) -> list[Card]:
    """Clock and weather side by side (or the clock alone), `rows` tall (at most 4)."""
    rows = min(rows, CLOCK_MAX_ROWS)
    weather = data.display.weather_entity
    total = grid.card_columns
    column_px = card_column_px(data.display.profile)
    if not weather:
        return [cards.sized(_clock_for(rows, span_px(total, column_px)), total, rows)]
    half = total // 2
    return [
        cards.sized(_clock_for(rows, span_px(half, column_px)), half, rows),
        cards.sized(
            cards.weather_tile(
                weather,
                data.language,
                vertical=rows >= 2,
                width_px=span_px(total - half, column_px),
            ),
            total - half,
            rows,
        ),
    ]


def _forecast(data: GeneratorInput) -> Card | None:
    """Forecast card, only when the weather entity provides forecasts."""
    weather = data.display.weather_entity
    return cards.forecast(weather, data.weather_features) if weather else None


def _room_card(data: GeneratorInput) -> Card | None:
    """HA's area card, showing the room sensors; the display's own entities stay out
    of its room controls (a screen light is not a room light)."""
    if not data.display.area_id:
        return None
    sensor_classes, exclude = room_card_sensors(data)
    exclude += [e.entity_id for e in data.area_entities if is_display_own(data, e)]
    return cards.area_card(
        data.display.area_id,
        area_controls(data),
        sensor_classes=sensor_classes,
        exclude_entities=sorted(set(exclude)),
    )


def _status_square(data: GeneratorInput, grid: Grid, rows: int) -> list[Card]:
    """Square strip: clock + weather; spare rows bring a bigger clock and the forecast."""
    forecast = _forecast(data)
    if rows <= 0:
        return []
    if forecast is None or rows <= 2:
        return _clock_weather(data, grid, min(rows, CLOCK_MAX_ROWS))
    top = 1 if rows == 3 else 2
    return _clock_weather(data, grid, top) + [cards.sized(forecast, grid.card_columns, rows - top)]


def _portrait_status_rows(data: GeneratorInput, rows: int) -> int:
    """Minimum status rows on portrait: clock/weather (2) and the room card."""
    room = _room_card(data)
    room_rows = cards.area_card_rows(room) if room else 0
    if rows >= 2 + room_rows + 1:
        return 2 + room_rows
    return min(rows, 2) if rows >= 3 else min(rows, 1)


def _status_portrait(
    data: GeneratorInput,
    grid: Grid,
    clock_rows: int,
    room: Card | None,
    forecast_rows: int,
    room_rows: int = 0,
) -> list[Card]:
    """Clock + weather, the room card, then the forecast."""
    result = _clock_weather(data, grid, clock_rows) if clock_rows else []
    if room is not None:
        rows = max(room_rows, cards.area_card_rows(room))
        result.append(cards.sized(room, grid.card_columns, rows))
    forecast = _forecast(data)
    if forecast_rows and forecast is not None:
        result.append(cards.sized(forecast, grid.card_columns, forecast_rows))
    return result


def info_column(data: GeneratorInput, grid: Grid, *, forecast: bool = True) -> Card | None:
    """Landscape info column: the clock above a nested 1-column grid.

    Grid cards share extra height equally among their children, so the
    background-less clock takes half of it and the weather/room cards the
    other half, instead of every card growing hollow.
    """
    if grid.rows <= 0 or grid.info_columns <= 0:
        return None
    weather = data.display.weather_entity
    room = _room_card(data)
    budget = grid.rows - 1  # the clock always gets one row
    parts: list[Card] = []
    if weather and budget >= 1:
        vertical = grid.rows >= WEATHER_VERTICAL_ROWS
        parts.append(
            cards.weather_tile(
                weather,
                data.language,
                vertical=vertical,
                width_px=span_px(grid.info_columns, card_column_px(data.display.profile)),
            )
        )
        budget -= 1 + (1 if vertical else 0)
    if room is not None and budget >= cards.area_card_rows(room):
        parts.append(room)
        budget -= cards.area_card_rows(room)
    forecast_card = _forecast(data) if forecast else None
    if forecast_card is not None and budget >= FORECAST_MIN_SPARE:
        parts.append(forecast_card)
        budget -= 2
    width = span_px(grid.info_columns, card_column_px(data.display.profile))
    clock = _clock_for(1 + min(2, max(0, budget)), width)
    column: list[Card] = [clock]
    if parts:
        column.append({"type": "grid", "columns": 1, "square": False, "cards": parts})
    return cards.sized(
        {"type": "grid", "columns": 1, "square": False, "cards": column},
        grid.info_columns,
        grid.rows,
    )


def _slots(data: GeneratorInput) -> list[EntityInfo | Card]:
    """Home slots; entrance: people first, then the live counts, then the rest."""
    items = home_items(data)
    counts = (
        cards.summary_cards(data.house_lights, data.openings, bool(data.house_secure))
        if is_entrance(data)
        else []
    )
    people = sum(1 for _ in takewhile(lambda e: e.domain == "person", items))
    return [*items[:people], *counts, *items[people:]]


def home_plan(data: GeneratorInput, grid: Grid) -> HomePlan:
    """All cards of the home section in placement order, plus overflow for More.

    Spare rows go to controls first (taller tiles), then to content that
    scales (forecast, clock), never into hollow cards (docs/design-spacing.md).
    """
    profile = data.display.profile
    orientation = profile.orientation
    column_px = card_column_px(profile)
    slots = _slots(data)
    plan = HomePlan()

    if orientation == "landscape":
        if not slots:  # nothing to control: the info column takes the whole width
            info = info_column(data, replace(grid, info_columns=grid.card_columns))
            plan.cards = [info] if info else []
            return plan
        area_columns, base = grid.card_columns - grid.info_columns, 0
    elif orientation == "portrait":
        area_columns, base = grid.card_columns, _portrait_status_rows(data, grid.rows)
    else:
        area_columns, base = grid.card_columns, (1 if grid.rows >= 2 or not slots else 0)

    fill = fill_tiles(
        min(len(slots), data.display.overrides.max_home_tiles or MAX_HOME_TILES),
        area_columns,
        grid.rows - base,
        column_px,
        max_columns=tile_max_columns(profile),
        max_rows=tile_max_rows(profile),
    )
    shown = slots[: fill.count]
    if fill.count < len(slots) and fill.count:
        shown = slots[: fill.count - 1]
        plan.overflow = [s for s in slots[fill.count - 1 :] if isinstance(s, EntityInfo)]
    spare = grid.rows - base - fill.height
    tile_rows = fill.rows
    last_extra = 0
    below: list[Card] = []

    if orientation == "landscape":
        full_lines = fill.count % fill.per_row == 0
        forecast_card = _forecast(data)
        if forecast_card is not None and full_lines and spare >= fill.lines + 2:
            # One step taller, keeping at least 2 rows for the forecast.
            grown, _ = grow_tiles(fill, fill.lines, column_px)
            if grown > fill.rows:
                tile_rows, spare = grown, spare - fill.lines
        if forecast_card is not None and full_lines and spare >= 2:
            below.append(cards.sized(forecast_card, area_columns, spare))
            spare = 0
        tile_rows, spare = grow_tiles(replace(fill, rows=tile_rows), spare, column_px)
        if not below and forecast_card is None:
            # No forecast to take the rows: tiles absorb them (L2).
            tile_rows, spare = grow_tiles(
                replace(fill, rows=tile_rows), spare, column_px, cap=TILE_ABSORB_MAX_ROWS
            )
        if not below and 0 < spare <= LAST_LINE_EXTRA_MAX:
            last_extra, spare = spare, 0  # the last tile line takes the rest
        info = info_column(data, grid, forecast=not below)
        if info is not None:
            plan.cards.append(info)
    elif orientation == "portrait":
        room = _room_card(data)
        room_rows = cards.area_card_rows(room) if room else 0
        room_on = room is not None and base == 2 + room_rows
        clock_rows = base - (room_rows if room_on else 0)
        if _forecast(data) is not None:
            # Spare rows: taller tiles first, then the forecast, then the clock.
            tile_rows, spare = grow_tiles(fill, spare, column_px)
            forecast_rows = 0
            if spare >= 2:
                forecast_rows = min(PORTRAIT_FORECAST_MAX_ROWS, spare)
                spare -= forecast_rows
            if spare and clock_rows:
                extra = min(spare, max(0, PORTRAIT_CLOCK_MAX_ROWS - clock_rows))
                clock_rows, spare = clock_rows + extra, spare - extra
            if forecast_rows:
                forecast_rows += spare
            else:
                clock_rows += min(spare, max(0, CLOCK_MAX_ROWS - clock_rows))
        else:
            # No forecast (L2): tiles to 4, clock/weather to 3, tiles to 5,
            # clock/weather to 4, room card to 3; the rest stays as margin.
            forecast_rows = 0
            tile_rows, spare = grow_tiles(fill, spare, column_px)

            def clock_to(limit: int) -> None:
                nonlocal clock_rows, spare
                if clock_rows:
                    extra = min(spare, max(0, limit - clock_rows))
                    clock_rows, spare = clock_rows + extra, spare - extra

            clock_to(PORTRAIT_CLOCK_MAX_ROWS)
            tile_rows, spare = grow_tiles(
                replace(fill, rows=tile_rows), spare, column_px, cap=TILE_ABSORB_MAX_ROWS
            )
            clock_to(CLOCK_MAX_ROWS)
            if room_on:
                extra = min(spare, max(0, ROOM_MAX_ROWS - room_rows))
                room_rows, spare = room_rows + extra, spare - extra
        plan.cards += _status_portrait(
            data, grid, clock_rows, room if room_on else None, forecast_rows, room_rows
        )
    else:
        tile_rows, spare = grow_tiles(fill, spare, column_px)
        plan.cards += _status_square(data, grid, base + spare)

    first_tile = len(plan.cards)
    last_start = (fill.lines - 1) * fill.per_row
    for index, slot in enumerate(shown):
        rows = tile_rows + (last_extra if index >= last_start else 0)
        if isinstance(slot, dict):
            card = {**slot, "vertical": True} if rows >= 2 else slot
        else:
            # The square 480 never gets inline features (U15).
            card = cards.entity_card(slot, rows, features=orientation != "square")
        plan.cards.append(cards.sized(card, fill.columns, rows))
    if plan.overflow:
        rows = tile_rows + last_extra
        more = cards.more_shortcut(data.language, len(plan.overflow), vertical=rows >= 2)
        plan.cards.append(cards.sized(more, fill.columns, rows))
    plan.cards = cards.widen_block(plan.cards, grid.card_columns, first_tile)
    plan.cards += below
    return plan
