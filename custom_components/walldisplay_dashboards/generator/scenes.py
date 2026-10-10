"""Scenes page: the room's scenes and scripts, then area-less scenes, as tiles.

Tiles fill the page: up to 3 per row and 6 rows high, but never more than
1.25x taller than wide; up to 2 leftover rows go to the last line, and a
partial last line shares the full width (U6). Entries that don't fit end in
a "+N more" slot.
"""

from __future__ import annotations

from ..const import PAGE_SCENES
from ..layout import TILE_ASPECT_MIN, card_column_px, fill_tiles, rows_px, span_px
from ..models import EntityInfo, GeneratorInput, Grid
from . import cards
from .cards import Card
from .room import page_entities

MAX_PER_ROW = 3
MAX_ROWS = 6
LAST_LINE_EXTRA_MAX = 2


def scene_plan(data: GeneratorInput, grid: Grid) -> tuple[list[Card], list[EntityInfo]]:
    entries = page_entities(data, PAGE_SCENES)
    if not entries or grid.rows <= 0:
        return [], entries
    column_px = card_column_px(data.display.profile)
    fill = fill_tiles(
        len(entries),
        grid.card_columns,
        grid.rows,
        column_px,
        max_per_row=MAX_PER_ROW,
        max_rows=MAX_ROWS,
    )
    rows = fill.rows
    width = span_px(fill.columns, column_px)
    while rows > 1 and rows_px(rows) * TILE_ASPECT_MIN > width:
        rows -= 1
    shown = entries[: fill.count]
    leftover = grid.rows - fill.lines * rows
    last_extra = leftover if 0 < leftover <= LAST_LINE_EXTRA_MAX else 0
    last_line_start = (fill.lines - 1) * fill.per_row
    placed = []
    for index, entity in enumerate(shown):
        height = rows + (last_extra if index >= last_line_start else 0)
        card = cards.action_tile(entity, vertical=height >= 2)
        placed.append(cards.sized(card, fill.columns, height))
    placed, overflow = cards.overflow_slot(placed, entries[fill.count :], shown, data.language)
    return cards.widen_block(placed, grid.card_columns), overflow
