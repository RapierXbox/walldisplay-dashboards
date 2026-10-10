"""Design pass 3: many controls on the square 480 and filled portrait Scenes (pure)."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "preview"))

import sample_house

from custom_components.walldisplay_dashboards.generator import build_dashboard
from custom_components.walldisplay_dashboards.layout import compute_grid, pack, rows_used
from custom_components.walldisplay_dashboards.models import EntityInfo, GeneratorInput, Overrides
from custom_components.walldisplay_dashboards.profiles import PROFILES

SQUARE = PROFILES["shelly_wall_display"]
KITCHEN = sample_house.KITCHEN


def lamps(n: int) -> tuple[Any, ...]:
    return tuple(
        sample_house.LightInfo(f"light.kitchen_l{i:02}", f"Lamp {i}", KITCHEN, dimmable=True)
        for i in range(n)
    )


def kitchen(n: int, max_tiles: int = 0) -> GeneratorInput:
    data = replace(sample_house.sample_input(SQUARE), area_entities=lamps(n))
    overrides = Overrides(max_home_tiles=max_tiles)
    return replace(data, display=replace(data.display, overrides=overrides))


def home(data: GeneratorInput) -> list[dict[str, Any]]:
    return build_dashboard(data)["views"][0]["sections"][0]["cards"]


def controls(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Room slots: the lamps and "+N more" (not clock, weather, Indoor)."""
    return [c for c in cards if c.get("entity", "").startswith("light.") or c["type"] == "shortcut"]


def size(card: dict[str, Any]) -> tuple[int, int]:
    return card["grid_options"]["columns"], card["grid_options"]["rows"]


def fills(cards: list[dict[str, Any]], rows: int) -> bool:
    placements = pack([size(c) for c in cards], 12)
    covered = sum(p.rows * p.columns for p in placements if p is not None)
    return rows_used(placements) == rows and covered == rows * 12


@pytest.mark.parametrize("n", range(1, 7))
def test_up_to_six_controls_are_big_tiles(n: int) -> None:
    cards = home(kitchen(n))
    slots = controls(cards)
    assert len(slots) == n
    assert all(c["vertical"] is True and size(c)[1] >= 2 for c in slots)
    assert fills(cards, compute_grid(SQUARE).rows)


@pytest.mark.parametrize(("n", "visible", "strip"), [(7, 7, 2), (8, 8, 2), (9, 9, 1), (10, 10, 1)])
def test_more_than_six_become_a_two_column_list(n: int, visible: int, strip: int) -> None:
    cards = home(kitchen(n))
    slots = controls(cards)
    assert len(slots) == visible and all(c["type"] == "tile" for c in slots)
    assert all(size(c)[1] == 1 and "vertical" not in c for c in slots)
    assert {size(c)[0] for c in slots[:-1]} == {6}  # 2 per row; a lone last one spans the row
    assert size(cards[0]) == (6, strip)  # the clock: 2-row strip (with Indoor) if it fits
    assert fills(cards, compute_grid(SQUARE).rows)


def test_list_overflow_shows_nine_and_more() -> None:
    slots = controls(home(kitchen(14)))
    assert len(slots) == 10
    assert [c["type"] for c in slots].count("tile") == 9
    assert slots[-1]["label"] == "+5 more"


@pytest.mark.parametrize("limit", [4, 5, 6])
def test_tile_limit_keeps_big_tiles(limit: int) -> None:
    slots = controls(home(kitchen(9, limit)))
    assert len(slots) == limit
    assert all(c.get("vertical") is True and size(c)[1] == 2 for c in slots)
    assert slots[-1]["type"] == "shortcut"
    assert slots[-1]["label"] == f"+{9 - limit + 1} more"


def test_many_long_german_names() -> None:
    """Ben's room with 9 lights and blinds: the list, names cleaned, nothing left out."""
    data = sample_house.many_input(SQUARE)
    cards = home(data)
    names = [
        c["name"] for c in cards if c["type"] == "tile" and c["entity"] != sample_house.WEATHER
    ]
    assert len(names) == 9 and "Schreibtischlampe" in names and "Raffstore Nord" in names
    assert not [c for c in cards if c["type"] == "shortcut"]
    assert all(size(c) in ((6, 1), (12, 1)) for c in cards if c["type"] == "tile")
    # Each name fits a 228 px 1-row tile at 16 px (about 18 characters).
    assert max(len(name) for name in names) <= 18


# --- Portrait Scenes (P3-5) -------------------------------------------------------


@pytest.mark.parametrize("profile_id", ["shelly_x2_portrait", "tablet_portrait"])
@pytest.mark.parametrize("count", range(1, 9))
def test_portrait_scenes_fill_the_page(profile_id: str, count: int) -> None:
    profile = PROFILES[profile_id]
    scenes = tuple(EntityInfo(f"scene.kitchen_{i}", f"Scene {i}", KITCHEN) for i in range(count))
    data = replace(sample_house.sample_input(profile), scenes=scenes, area_entities=scenes)
    data = replace(data, house_scenes=() if count >= 3 else sample_house.HOUSE_SCENES)
    views = {v["path"]: v for v in build_dashboard(data)["views"]}
    cards = views["scenes"]["sections"][0]["cards"]
    grid = compute_grid(profile)
    placements = pack([size(c) for c in cards], grid.card_columns)
    covered = sum(p.rows * p.columns for p in placements if p is not None)
    assert covered == grid.rows * grid.card_columns, f"{count} scenes leave a gap"
    for card in cards:
        _, rows = size(card)
        assert rows <= 6 + 2  # MAX_ROWS plus the last line's extra rows
