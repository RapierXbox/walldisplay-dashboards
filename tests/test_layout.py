"""Layout budget tests (pure)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "preview"))

import sample_house

sample_house.ensure_package()

from custom_components.walldisplay_dashboards.layout import (
    MIN_TILE_PX,
    available_rows,
    card_column_px,
    compute_grid,
    fill_tiles,
    pack,
    rows_used,
    section_columns,
    span_px,
    status_rows,
    tile_max_columns,
    tile_max_rows,
)
from custom_components.walldisplay_dashboards.models import Profile
from custom_components.walldisplay_dashboards.profiles import (
    PROFILES,
    resolve_profile,
)

SIZES = [(w, h) for w in range(320, 1921, 80) for h in range(320, 1921, 80)]


def size(width: int, height: int) -> Profile:
    return Profile("custom", "Custom", width, height)


@pytest.mark.parametrize(
    ("height", "rows"), [(480, 6), (360, 4), (752, 10), (800, 11), (960, 13), (1280, 18), (90, 0)]
)
def test_available_rows(height: int, rows: int) -> None:
    assert available_rows(height) == rows


@pytest.mark.parametrize(
    ("width", "columns"),
    [(320, 1), (480, 1), (600, 1), (640, 1), (736, 2), (960, 2), (1088, 3), (1280, 3), (1920, 3)],
)
def test_section_columns_follow_frontend(width: int, columns: int) -> None:
    assert section_columns(width) == columns


def test_square_480() -> None:
    profile = PROFILES["shelly_wall_display"]
    grid = compute_grid(profile)
    assert grid.section_columns == 1
    assert grid.card_columns == 12
    assert grid.rows == 6
    assert status_rows(profile, grid.rows) == 1
    assert (grid.tile_columns, grid.tile_rows, grid.tiles_per_row) == (4, 2, 3)
    assert grid.max_tiles == 6
    assert grid.info_columns == 0


def test_x2_landscape() -> None:
    grid = compute_grid(PROFILES["shelly_x2_landscape"])
    assert (grid.section_columns, grid.card_columns, grid.rows) == (2, 24, 6)
    assert grid.info_columns == 6  # 6 + 3 x 6 (U6)
    assert (grid.tile_columns, grid.tiles_per_row, grid.tile_rows) == (6, 3, 2)
    assert grid.max_tiles == 9


def test_xl_landscape_third() -> None:
    grid = compute_grid(PROFILES["shelly_xl"])
    assert (grid.card_columns, grid.info_columns, grid.tile_columns) == (36, 12, 8)
    assert grid.rows == 10 and grid.max_tiles == 15


def test_x2_portrait() -> None:
    profile = PROFILES["shelly_x2_portrait"]
    grid = compute_grid(profile)
    assert grid.rows == 13
    assert status_rows(profile, grid.rows) == 2
    assert (grid.tile_columns, grid.tile_rows, grid.tiles_per_row) == (4, 2, 3)
    assert grid.max_tiles == 15


def test_flat_square_uses_one_row_tiles() -> None:
    grid = compute_grid(size(480, 400))  # R = 4, 3 rows after the status strip
    assert grid.rows == 4
    assert grid.tile_rows == 1
    assert grid.max_tiles == 9


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_sweep_fits(width: int, height: int) -> None:
    profile = size(width, height)
    grid = compute_grid(profile)
    rows = available_rows(height)
    assert grid.rows == rows
    assert grid.card_columns == 12 * grid.section_columns
    assert 1 <= grid.section_columns <= 3
    # Columns: info column plus a full tile row fit the section.
    assert grid.info_columns + grid.tile_columns * grid.tiles_per_row == grid.card_columns
    # Rows: status strip plus all tile rows stay within R.
    status = status_rows(profile, rows)
    tile_lines = math.ceil(grid.max_tiles / grid.tiles_per_row) if grid.max_tiles else 0
    assert status + tile_lines * grid.tile_rows <= rows
    assert grid.tile_rows in (1, 2)
    if grid.tile_rows == 2:
        assert rows - status >= 4
    if grid.tiles_per_row > 1:
        assert span_px(grid.tile_columns, card_column_px(profile)) >= MIN_TILE_PX
    if profile.orientation == "landscape":
        assert grid.card_columns / 4 - 1 <= grid.info_columns <= grid.card_columns / 2
        assert (grid.card_columns - grid.info_columns) % grid.tiles_per_row == 0
        assert grid.tiles_per_row <= 3
    else:
        assert grid.info_columns == 0
    # The packed tiles really fit (CSS auto-placement of the home section).
    spans = []
    if grid.info_columns and rows:
        spans.append((grid.info_columns, rows))
    elif status:
        spans.append((grid.card_columns, status))
    spans += [(grid.tile_columns, grid.tile_rows)] * grid.max_tiles
    assert rows_used(pack(spans, grid.card_columns)) <= rows


def test_pack_flows_around_tall_card() -> None:
    placed = pack([(4, 3), (4, 2), (4, 2), (4, 2), (4, 2)], 12)
    assert [(p.row, p.column) for p in placed] == [(0, 0), (0, 4), (0, 8), (2, 4), (2, 8)]


def test_pack_drops_overflow_without_moving_cursor() -> None:
    placed = pack([(12, 1), (6, 2), (6, 2), (12, 1), (6, 1)], 12, max_rows=3)
    assert placed[3] is None
    assert placed[4] is None or placed[4].bottom <= 3
    assert rows_used(placed) == 3


def test_resolve_profile() -> None:
    assert resolve_profile("shelly_xl", None, None) is PROFILES["shelly_xl"]
    measured = resolve_profile("shelly_xl", 1280, 720)
    assert (measured.width, measured.height, measured.measured) == (1280, 720, True)
    custom = resolve_profile("custom", 800, 480)
    assert (custom.id, custom.width, custom.height, custom.measured) == ("custom", 800, 480, False)
    assert resolve_profile("shelly_xl", 1280, None) is PROFILES["shelly_xl"]
    assert resolve_profile("nope", None, None) is PROFILES["shelly_wall_display"]


def test_profile_table() -> None:
    expected = {
        "shelly_wall_display": (480, 480, 1.0),
        "shelly_x1i": (480, 480, 1.5),
        "shelly_x2_landscape": (960, 480, 1.5),
        "shelly_x2_portrait": (480, 960, 1.5),
        "shelly_xl": (1280, 752, 1.0),
        "nspanel_pro": (480, 480, 1.0),
        "tablet_landscape": (1280, 800, 1.0),
        "tablet_portrait": (800, 1280, 1.0),
    }
    for profile_id, (width, height, dpr) in expected.items():
        profile = PROFILES[profile_id]
        assert (profile.id, profile.width, profile.height, profile.dpr_hint) == (
            profile_id,
            width,
            height,
            dpr,
        )
    assert "custom" in PROFILES


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, (1, 12, 4, 1)), (2, (2, 6, 4, 2)), (4, (4, 6, 2, 2)), (6, (6, 4, 2, 3))],
)
def test_fill_square(n: int, expected: tuple[int, int, int, int]) -> None:
    profile = PROFILES["shelly_wall_display"]
    fill = fill_tiles(n, 12, 4, card_column_px(profile))
    assert (fill.count, fill.columns, fill.rows, fill.per_row) == expected


@pytest.mark.parametrize(("width", "height"), SIZES[::7])
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 9, 12, 20])
def test_fill_fits(width: int, height: int, n: int) -> None:
    profile = size(width, height)
    grid = compute_grid(profile)
    area_columns = grid.card_columns - grid.info_columns
    area_rows = grid.rows - status_rows(profile, grid.rows)
    fill = fill_tiles(n, area_columns, area_rows, card_column_px(profile))
    if area_rows <= 0:
        assert fill.count == 0
        return
    assert 1 <= fill.count <= n
    assert fill.per_row * fill.columns <= area_columns
    # No extra tile can slip into a line, so the planned lines are the real ones.
    assert area_columns - fill.per_row * fill.columns < fill.columns
    assert math.ceil(fill.count / fill.per_row) * fill.rows <= area_rows
    placed = pack([(fill.columns, fill.rows)] * fill.count, area_columns)
    assert rows_used(placed) <= area_rows


@pytest.mark.parametrize(("height", "rows"), [(480, 7), (360, 5), (752, 11)])
def test_rows_without_footer(height: int, rows: int) -> None:
    assert available_rows(height, footer=False) == rows


@pytest.mark.parametrize(("width", "height"), SIZES[::5])
@pytest.mark.parametrize("n", [1, 2, 4, 6, 9, 12])
def test_fill_caps_and_exact_lines(width: int, height: int, n: int) -> None:
    profile = size(width, height)
    grid = compute_grid(profile)
    area = grid.card_columns - grid.info_columns
    fill = fill_tiles(
        n,
        area,
        grid.rows,
        card_column_px(profile),
        max_columns=tile_max_columns(profile),
        max_rows=tile_max_rows(profile),
    )
    if not fill.count:
        return
    assert area % fill.per_row == 0 and fill.per_row * fill.columns == area
    assert fill.rows <= tile_max_rows(profile)
    if tile_max_columns(profile) and area >= 2 * tile_max_columns(profile):
        assert fill.columns <= tile_max_columns(profile)
    assert fill.height <= grid.rows


@pytest.mark.parametrize(
    ("height", "footer", "rows", "px"),
    [(480, True, 6, 56.0), (752, True, 10, 57.6), (800, True, 11, 56.0), (480, False, 7, 58.29)],
)
def test_row_px_fills_the_height(height: int, footer: bool, rows: int, px: float) -> None:
    from custom_components.walldisplay_dashboards.layout import row_px

    assert available_rows(height, footer) == rows
    assert row_px(height, rows, footer) == pytest.approx(px, abs=0.01)
