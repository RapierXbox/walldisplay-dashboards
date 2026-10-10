"""Scenes page: the room's scenes and scripts, then area-less scenes, as tiles.

Tiles fill the page: up to 3 per row and 6 rows high, but never more than
1.25x taller than wide; up to 2 leftover rows go to the last line, and a
partial last line shares the full width (U6). When the shape the Home rules
pick leaves more rows empty (tall portrait pages, P3-5), the tiles per row
that leave the fewest empty rows win. Entries that don't fit end in a
"+N more" slot.
"""

from __future__ import annotations

import math

from ..const import MIN_TILE_PX, PAGE_SCENES
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
    per_row, rows, last_extra, empty = _shape(fill.count, fill.per_row, grid, column_px)
    for other in range(1, MAX_PER_ROW + 1):
        if empty and other != fill.per_row and grid.card_columns % other == 0:
            width = span_px(grid.card_columns // other, column_px)
            if other == 1 or width >= MIN_TILE_PX:
                shape = _shape(fill.count, other, grid, column_px)
                if shape[3] < empty:
                    per_row, rows, last_extra, empty = shape
    columns = grid.card_columns // per_row
    shown = entries[: fill.count]
    last_line_start = (math.ceil(fill.count / per_row) - 1) * per_row
    placed = []
    for index, entity in enumerate(shown):
        height = rows + (last_extra if index >= last_line_start else 0)
        card = cards.action_tile(entity, vertical=height >= 2)
        placed.append(cards.sized(card, columns, height))
    placed, overflow = cards.overflow_slot(placed, entries[fill.count :], shown, data.language)
    return cards.widen_block(placed, grid.card_columns), overflow


def _shape(count: int, per_row: int, grid: Grid, column_px: float) -> tuple[int, int, int, int]:
    """(per_row, tile rows, last line's extra rows, empty rows) for `count` tiles.

    As tall as the page allows, up to MAX_ROWS and 1.25x taller than wide;
    lines that don't fit count as a fully empty page.
    """
    lines = math.ceil(count / per_row)
    width = span_px(grid.card_columns // per_row, column_px)
    rows = max(1, min(MAX_ROWS, grid.rows // lines))
    while rows > 1 and rows_px(rows) * TILE_ASPECT_MIN > width:
        rows -= 1
    leftover = grid.rows - lines * rows
    if leftover < 0:  # the lines don't fit: never better than the Home rules' shape
        return per_row, rows, 0, grid.rows
    extra = leftover if leftover <= LAST_LINE_EXTRA_MAX else 0
    return per_row, rows, extra, leftover - extra
