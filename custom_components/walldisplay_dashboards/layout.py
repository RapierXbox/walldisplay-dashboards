"""Grid budget for a display. Pure Python, no Home Assistant imports.

How the dashboard maps onto a sections view (frontend 20260930.x, measured in
tools/sandbox/SPIKE.md and docs/design-spacing.md)
-----------------------------------------------------------------------------

Every view holds exactly ONE grid section with ``column_span = C`` and the view
has ``max_columns = C``. The section then has ``12 * C`` card columns and every
card is sized with ``grid_options`` (gap 8 px). One section avoids the gap
between stacked sections and keeps every card on one predictable CSS grid.

walldisplay.js sets the view's row gap to 12 px (top/bottom padding, footer
offset) and its column gap to 12 px above 600 px wide (8 px at or below), so::

    g = 8 if W <= 600 else 12
    C = clamp(floor((W - g) / (320 + g)), 1, 3)
    R = floor((H - 96) / 64)    with the pill footer (12 top + 92 footer band - 8)
    R = floor((H - 16) / 64)    without (12 top + 12 bottom - 8)

and it stretches the row height to ``row_px()`` = ``(H - 96) / R - 8`` (no
footer ``(H - 16) / R - 8``), clamped 48-72 px, so R rows end 16 px above the
pill. The generator reasons in rows; widths use the 56 px minimum row for
aspect checks. A section is at most ``C * 500 + (C - 1) * g`` wide.

Landscape puts an info column on the left: a ``grid`` card with ``columns: 1``
sized ``info_columns x R`` (a grid card stretches its children to fill the
rows; a ``vertical-stack`` does not). The tiles follow it as ordinary cards;
CSS sparse auto-placement puts each into the next free cell, to the right of
the info column on every row. ``pack()`` reproduces that placement so the
generator can check that every planned card fits and tests can measure rows.

Cards report their own ``min_columns``/``min_rows`` (tile and shortcut: 6
columns) and the frontend clamps the requested size up to them, so the
generator sets ``min_columns`` and ``min_rows`` in ``grid_options`` too.

All tile-width decisions go through ``const.MIN_TILE_PX``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .const import (
    BOTTOM_MARGIN_PX,
    COLUMN_MIN_PX,
    FOOTER_BAND_PX,
    GRID_GAP_PX,
    GRID_ROW_PX,
    GRID_TOP_PX,
    GROWN_TILE_MAX_ROWS,
    MIN_HORIZONTAL_TILE_PX,
    MIN_TILE_PX,
    ROW_MAX_PX,
    ROW_MIN_PX,
    VIEW_GAP_PX,
)
from .models import Grid, Profile

MAX_SECTION_COLUMNS = 3
BASE_CARD_COLUMNS = 12
SECTION_MAX_PX = 500  # --column-max-width
NARROW_MAX_PX = 600  # @media (max-width: 600px) switches to the narrow gap
VIEW_GAP_NARROW_PX = 8
INFO_SHARE = 1 / 3
# Tile size caps (U5): square/portrait half a section column x 2 rows, landscape
# 3 rows. Spare rows may enlarge tiles up to const.GROWN_TILE_MAX_ROWS while
# they stay at least as wide as tall.
TILE_MAX_COLUMNS = 6
TILE_MAX_ROWS = 2
TILE_MAX_ROWS_LANDSCAPE = 3
LANDSCAPE_MAX_PER_ROW = 3


def available_rows(height: int, footer: bool = True) -> int:
    """Grid rows between the top padding and the footer band (or bottom margin)."""
    bottom = FOOTER_BAND_PX if footer else BOTTOM_MARGIN_PX
    usable = height - GRID_TOP_PX - bottom + GRID_GAP_PX
    return max(0, usable // (GRID_ROW_PX + GRID_GAP_PX))


def row_px(height: int, rows: int, footer: bool = True) -> float:
    """Row height walldisplay.js stretches to, so R rows end 16 px above the pill."""
    if rows <= 0:
        return float(GRID_ROW_PX)
    band = (
        FOOTER_BAND_PX + GRID_TOP_PX - GRID_GAP_PX if footer else 2 * BOTTOM_MARGIN_PX - GRID_GAP_PX
    )
    return min(ROW_MAX_PX, max(ROW_MIN_PX, (height - band) / rows - GRID_GAP_PX))


def view_gap(width: int) -> int:
    """Column gap (and side padding) of the sections view at this width."""
    return VIEW_GAP_NARROW_PX if width <= NARROW_MAX_PX else VIEW_GAP_PX


def section_columns(width: int) -> int:
    """Section columns the sections view creates at this width (clamped 1-3)."""
    gap = view_gap(width)
    columns = (width - 2 * gap + gap) // (COLUMN_MIN_PX + gap)
    return max(1, min(MAX_SECTION_COLUMNS, columns))


def section_width_px(width: int, columns: int) -> float:
    """Pixel width of one section spanning `columns` view columns."""
    gap = view_gap(width)
    return min(width - 2 * gap, columns * SECTION_MAX_PX + (columns - 1) * gap)


def card_column_px(profile: Profile) -> float:
    """Width of one card column inside the section."""
    columns = section_columns(profile.width)
    count = BASE_CARD_COLUMNS * columns
    return (section_width_px(profile.width, columns) - (count - 1) * GRID_GAP_PX) / count


def span_px(columns: int, column_px: float) -> float:
    """Pixel width of a card spanning `columns` card columns."""
    return columns * column_px + (columns - 1) * GRID_GAP_PX


def rows_px(rows: int) -> int:
    """Pixel height of a card spanning `rows` grid rows."""
    return rows * GRID_ROW_PX + (rows - 1) * GRID_GAP_PX


def fit_span(card_columns: int, column_px: float, min_px: float) -> int:
    """Narrowest span that divides the row evenly and is at least `min_px` wide."""
    for span in range(1, card_columns + 1):
        if card_columns % span == 0 and span_px(span, column_px) >= min_px:
            return span
    return card_columns


def status_rows(profile: Profile, rows: int) -> int:
    """Minimum rows of the clock/weather strip above the tiles."""
    match profile.orientation:
        case "landscape":
            return 0
        case "portrait":
            return 2 if rows >= 4 else (1 if rows >= 2 else 0)
        case _:
            return 1 if rows >= 2 else 0


def tile_max_rows(profile: Profile) -> int:
    return TILE_MAX_ROWS_LANDSCAPE if profile.orientation == "landscape" else TILE_MAX_ROWS


def tile_max_columns(profile: Profile) -> int | None:
    """Half a section column (6 of 12) per section column; no cap on landscape."""
    if profile.orientation == "landscape":
        return None
    return TILE_MAX_COLUMNS * section_columns(profile.width)


def _landscape_info(card_columns: int, column_px: float) -> int:
    """Info column width: about a third, leaving a tile area that splits evenly.

    Prefers a tile area divisible by 6 (2 or 3 tiles per row, U6), then by 3
    or 2, as long as tiles stay at least MIN_TILE_PX wide.
    """
    target = card_columns * INFO_SHARE
    low = max(1, math.floor(card_columns / 4))
    high = max(low, math.ceil(card_columns * 0.42))
    best: tuple[tuple[int, float, int], int] | None = None
    for info in range(low, high + 1):
        rest = card_columns - info
        splits = [
            p for p in (3, 2) if rest % p == 0 and span_px(rest // p, column_px) >= MIN_TILE_PX
        ]
        if not splits:
            continue
        key = (0 if rest % 6 == 0 else 1, abs(info - target), -info)
        if best is None or key < best[0]:
            best = (key, info)
    return best[1] if best else max(1, round(target))


def compute_grid(profile: Profile, footer: bool = True) -> Grid:
    """Compute the layout budget for a profile.

    tile_* and max_tiles describe the densest home grid (most tiles at the
    capped size); the home page picks its actual tile size with fill_tiles().
    """
    columns = section_columns(profile.width)
    card_columns = BASE_CARD_COLUMNS * columns
    column_px = card_column_px(profile)
    rows = available_rows(profile.height, footer)
    tile_area_rows = rows - status_rows(profile, rows)

    if profile.orientation == "landscape":
        info = _landscape_info(card_columns, column_px)
    else:
        info = 0
    area = card_columns - info
    limit = LANDSCAPE_MAX_PER_ROW if info else area
    per_row = max(
        (
            p
            for p in range(1, min(area, limit) + 1)
            if area % p == 0 and span_px(area // p, column_px) >= MIN_TILE_PX
        ),
        default=1,
    )
    tile_columns = area // per_row
    tile_rows = 2 if tile_area_rows >= 4 else 1
    max_tiles = per_row * (tile_area_rows // tile_rows) if tile_area_rows > 0 else 0
    return Grid(
        section_columns=columns,
        card_columns=card_columns,
        rows=rows,
        tile_rows=tile_rows,
        tile_columns=tile_columns,
        tiles_per_row=per_row,
        max_tiles=max_tiles,
        info_columns=info,
    )


@dataclass(frozen=True, slots=True)
class Placement:
    """Where CSS auto-placement puts one card (0-based)."""

    row: int
    column: int
    rows: int
    columns: int

    @property
    def bottom(self) -> int:
        return self.row + self.rows


def pack(
    spans: Iterable[tuple[int, int]], card_columns: int, max_rows: int | None = None
) -> list[Placement | None]:
    """Simulate sparse row auto-placement of (columns, rows) spans.

    With `max_rows`, a card that would end below it is left out (None) and
    does not move the placement cursor, matching a config without that card.
    """
    occupied: set[tuple[int, int]] = set()
    cursor_row, cursor_col = 0, 0
    result: list[Placement | None] = []
    for width, height in spans:
        width = max(1, min(width, card_columns))
        height = max(1, height)
        row, col = cursor_row, cursor_col
        while True:
            if col + width > card_columns:
                row, col = row + 1, 0
                continue
            cells = {(r, c) for r in range(row, row + height) for c in range(col, col + width)}
            if cells.isdisjoint(occupied):
                break
            col += 1
        if max_rows is not None and row + height > max_rows:
            result.append(None)
            continue
        occupied |= cells
        cursor_row, cursor_col = row, col + width
        result.append(Placement(row, col, height, width))
    return result


def rows_used(placements: Sequence[Placement | None]) -> int:
    """Number of grid rows the placed cards reach down to."""
    return max((p.bottom for p in placements if p is not None), default=0)


@dataclass(frozen=True, slots=True)
class TileFill:
    """How n tiles fill a rectangle of the section grid."""

    count: int  # tiles that fit (may be fewer than asked for)
    columns: int  # card columns per tile
    rows: int  # grid rows per tile
    per_row: int

    @property
    def lines(self) -> int:
        return math.ceil(self.count / self.per_row) if self.count else 0

    @property
    def height(self) -> int:
        """Rows the tile block takes."""
        return self.lines * self.rows


# Tile shapes (width / height) between these count as "square-ish".
ASPECT_MIN = 0.7
ASPECT_MAX = 2.0
PARTIAL_LINE_FACTOR = 0.8  # a half-empty last line leaves a hole (U6)
TILE_ASPECT_MIN = 0.8  # grown tiles: at most 1.25x taller than wide
TILE_ABSORB_MAX_ROWS = 5  # without a forecast, tiles may absorb spare rows up to this


def _aspect_factor(aspect: float) -> float:
    off = max(0.0, math.log2(aspect / ASPECT_MAX)) + max(0.0, math.log2(ASPECT_MIN / aspect))
    return 1 / (1 + off)


def fill_tiles(
    n: int,
    area_columns: int,
    area_rows: int,
    column_px: float,
    *,
    max_count: int | None = None,
    max_per_row: int | None = None,
    max_columns: int | None = None,
    max_rows: int | None = None,
    min_px: float = MIN_TILE_PX,
    min_horizontal_px: float = MIN_HORIZONTAL_TILE_PX,
) -> TileFill:
    """Pick tiles per row and tile size so n tiles fill the area.

    Tiles are at least `min_px` wide, 1-row tiles at least `min_horizontal_px`
    (both from const, the one place to retune for bigger type). Tiles per row
    always divide the area exactly (every full line adds up to
    the area width, U6). Tile size is capped by max_columns x max_rows (U5).
    Score = covered share of the area x a penalty for tiles much wider than
    tall (or the reverse); ties go to taller, then fewer-per-row tiles.
    """
    count = min(n, max_count) if max_count is not None else n
    if count <= 0 or area_rows <= 0 or area_columns <= 0:
        return TileFill(0, area_columns, 1, 1)
    limit = min(area_columns, max_per_row or area_columns)

    widths: dict[int, int] = {}
    for per_row in range(1, limit + 1):
        width = area_columns // per_row
        if area_columns % per_row:
            continue
        if max_columns is not None and width > max_columns:
            continue
        if per_row > 1 and span_px(width, column_px) < min_px:
            continue
        widths[per_row] = width
    if not widths:  # nothing satisfies the caps: one full-width tile per line
        widths = {1: area_columns}

    def one_row_ok(per_row: int, width: int) -> bool:
        """1-row tiles put the name beside the icon and need more width."""
        return per_row == 1 or span_px(width, column_px) >= min_horizontal_px

    tall_rows = area_rows // 2 if (max_rows is None or max_rows >= 2) else 0
    count = min(
        count,
        max(p * (area_rows if one_row_ok(p, w) else tall_rows) for p, w in widths.items()),
    )
    if count <= 0:
        return TileFill(0, area_columns, 1, 1)

    best: tuple[tuple[float, int, int], TileFill] | None = None
    for per_row, width in widths.items():
        lines = math.ceil(count / per_row)
        height = area_rows // lines
        if max_rows is not None:
            height = min(height, max_rows)
        if height == 0 or (height == 1 and not one_row_ok(per_row, width)):
            continue
        coverage = count * width * height / (area_columns * area_rows)
        aspect = span_px(width, column_px) / rows_px(height)
        partial = PARTIAL_LINE_FACTOR if count % per_row else 1.0
        score = round(coverage * _aspect_factor(aspect) * partial, 6)
        key = (score, min(height, 2), -per_row)
        if best is None or key > best[0]:
            best = (key, TileFill(count, width, height, per_row))
    assert best is not None
    return best[1]


def side_split(profile: Profile, card_columns: int) -> tuple[int, int]:
    """(main, side) card columns for a landscape page: main about two thirds."""
    main = round(card_columns * 2 / 3)
    if span_px(card_columns - main, card_column_px(profile)) < MIN_HORIZONTAL_TILE_PX:
        return card_columns, 0
    return main, card_columns - main


def grow_tiles(
    fill: TileFill, spare: int, column_px: float, cap: int = GROWN_TILE_MAX_ROWS
) -> tuple[int, int]:
    """Taller tiles from spare rows: one row per tile line at a time, up to
    `cap`, and at most 1.25x taller than wide (TILE_ASPECT_MIN).
    Returns (tile rows, spare left)."""
    rows = fill.rows
    lines = fill.lines
    if not lines:
        return rows, spare
    width = span_px(fill.columns, column_px)
    while spare >= lines and rows < cap and rows_px(rows + 1) * TILE_ASPECT_MIN <= width:
        rows += 1
        spare -= lines
    return rows, spare


def widen_last_line(
    spans: Sequence[tuple[int, int]], card_columns: int, first: int = 0
) -> list[tuple[int, int]]:
    """Let a partial last line of a tile block share the block's full width (U6).

    `spans` are (columns, rows) in placement order; the block starts at index
    `first`. The equal-size cards of the block's last packed row get
    `(card_columns - start_column) // n` columns when that divides evenly.
    """
    result = list(spans)
    placements = pack(result, card_columns)
    block = [(i, p) for i, p in enumerate(placements) if i >= first and p is not None]
    if not block:
        return result
    last_row = max(p.row for _, p in block)
    line = [(i, p) for i, p in block if p.row == last_row]
    sizes = {result[i] for i, _ in line}
    start = min(p.column for _, p in line)
    end = max(p.column + p.columns for _, p in line)
    if len(sizes) != 1 or end >= card_columns:
        return result
    width = card_columns - start
    if width % len(line):
        return result
    for i, _ in line:
        result[i] = (width // len(line), result[i][1])
    return result


@dataclass(frozen=True, slots=True)
class BlockFill:
    """A tile block that fills its area: TileFill plus the last line's extra rows."""

    count: int
    columns: int
    rows: int
    per_row: int
    last_extra: int = 0

    @property
    def lines(self) -> int:
        return math.ceil(self.count / self.per_row) if self.count else 0

    @property
    def height(self) -> int:
        return self.lines * self.rows + self.last_extra


def fill_block(
    n: int,
    area_columns: int,
    area_rows: int,
    column_px: float,
    *,
    max_columns: int | None = None,
    max_rows: int | None = None,
    grow_cap: int = TILE_ABSORB_MAX_ROWS,
    last_extra_max: int = 2,
    min_px: float = MIN_TILE_PX,
    min_horizontal_px: float = MIN_HORIZONTAL_TILE_PX,
) -> BlockFill:
    """Tiles that fill the whole area (More view): for every tiles-per-row
    choice, start at the capped size, grow (up to `grow_cap`, at most 1.25x
    taller than wide), give up to `last_extra_max` leftover rows to the last
    line, and keep the choice that leaves the fewest empty cells (then shows
    the most tiles, then has the best tile shape)."""
    if n <= 0 or area_rows <= 0 or area_columns <= 0:
        return BlockFill(0, area_columns, 1, 1)
    divisors = [p for p in range(1, area_columns + 1) if area_columns % p == 0]
    capped = [p for p in divisors if max_columns is None or area_columns // p <= max_columns]
    best: tuple[tuple[int, int, float], BlockFill] | None = None
    for per_row in capped or divisors:
        width = area_columns // per_row
        width_px = span_px(width, column_px)
        if per_row > 1 and width_px < min_px:
            continue
        one_row_ok = per_row == 1 or width_px >= min_horizontal_px
        min_rows = 1 if one_row_ok else 2
        capacity = per_row * (area_rows // min_rows)
        count = min(n, capacity)
        if count == 0:
            continue
        lines = math.ceil(count / per_row)
        rows = max(min_rows, min(area_rows // lines, max_rows or area_rows))
        while (
            (rows + 1) * lines <= area_rows
            and rows < grow_cap
            and rows_px(rows + 1) * TILE_ASPECT_MIN <= width_px
        ):
            rows += 1
        leftover = area_rows - rows * lines
        extra = leftover if leftover <= last_extra_max else 0
        partial = count % per_row
        hole = 0 if not partial or area_columns % partial == 0 else 1
        empty = (leftover - extra) * area_columns + hole * width * rows
        aspect = width_px / rows_px(rows)
        key = (-empty, count, round(_aspect_factor(aspect), 6))
        if best is None or key > best[0]:
            best = (key, BlockFill(count, width, rows, per_row, extra))
    return best[1] if best else BlockFill(0, area_columns, 1, 1)
