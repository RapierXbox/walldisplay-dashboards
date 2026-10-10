"""Dashboard generator tests (pure, sample house)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "preview"))

import dump_goldens
import sample_house

from custom_components.walldisplay_dashboards.const import (
    NAV,
    SECURE_COVER_CLASSES,
    SECURE_DOMAINS,
)
from custom_components.walldisplay_dashboards.generator import (
    PAGE_PLANS,
    build_dashboard,
    dashboard_budget,
    fit_to_rows,
)
from custom_components.walldisplay_dashboards.generator.cards import (
    referenced_entities,
)
from custom_components.walldisplay_dashboards.generator.info import (
    ClimateInfo,
    LightInfo,
)
from custom_components.walldisplay_dashboards.generator.labels import LABELS
from custom_components.walldisplay_dashboards.layout import (
    compute_grid,
    pack,
    rows_used,
)
from custom_components.walldisplay_dashboards.models import (
    EntityInfo,
    GeneratorInput,
    Overrides,
    Profile,
)
from custom_components.walldisplay_dashboards.profiles import PROFILES

GOLDENS = Path(__file__).parent / "fixtures" / "expected"
SIZES = [(w, h) for w in range(320, 1921, 160) for h in range(320, 1921, 160)]
KITCHEN = sample_house.KITCHEN
SQUARE = PROFILES["shelly_wall_display"]
LANDSCAPE = PROFILES["shelly_x2_landscape"]
PORTRAIT = PROFILES["shelly_x2_portrait"]
DISPLAY_FIELDS = {"pages", "overrides", "indoor_temperature", "indoor_humidity", "weather_entity"}
READ_ONLY_TYPES = {"area", "weather-forecast", "markdown", "clock"}


def sized(width: int, height: int) -> Profile:
    return Profile("custom", "Custom", width, height)


def sample(profile: Profile | None = None, **changes: Any) -> GeneratorInput:
    data = sample_house.sample_input(profile or SQUARE)
    display = {k: changes.pop(k) for k in list(changes) if k in DISPLAY_FIELDS}
    if display:
        data = replace(data, display=replace(data.display, **display))
    return replace(data, **changes)


def views_of(data: GeneratorInput) -> dict[str, dict[str, Any]]:
    return {view["path"]: view for view in build_dashboard(data)["views"]}


def section_cards(view: dict[str, Any]) -> list[dict[str, Any]]:
    return view["sections"][0]["cards"]


def all_entities(data: GeneratorInput) -> dict[str, EntityInfo]:
    index: dict[str, EntityInfo] = {}
    for group in (
        data.area_entities,
        data.climates,
        data.media_players,
        data.scenes,
        data.area_sensors,
        data.house_scenes,
        data.persons,
        data.house_secure,
        data.leave_home,
    ):
        for entity in group:
            index.setdefault(entity.entity_id, entity)
    return index


def known_entities(data: GeneratorInput) -> set[str]:
    display = data.display
    extra = (
        display.weather_entity,
        display.indoor_temperature,
        display.indoor_humidity,
        data.area_temperature,
        data.area_humidity,
    )
    return set(all_entities(data)) | set(data.openings) | {x for x in extra if x}


def is_secure(entity: EntityInfo) -> bool:
    return entity.domain in SECURE_DOMAINS or (
        entity.domain == "cover" and entity.device_class in SECURE_COVER_CLASSES
    )


def walk(node: Any):
    """Every card dict inside a card config (nested grid cards included)."""
    if isinstance(node, dict):
        if "type" in node:
            yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def actions(card: dict[str, Any]) -> list[dict[str, Any]]:
    return [card[k] for k in ("tap_action", "icon_tap_action", "hold_action") if k in card]


def is_control(card: dict[str, Any]) -> bool:
    if card["type"] in ("thermostat", "media-control"):
        return True
    if card["type"] != "tile":
        return False
    acting = any(a.get("action") in ("toggle", "perform-action") for a in actions(card))
    return acting or bool(card.get("features"))


def check_rows(view: dict[str, Any], columns: int, rows: int) -> None:
    """Rows fit the budget, and every row is a full-width prefix that never grows."""
    spans = []
    for card in section_cards(view):
        options = card["grid_options"]
        width, height = options["columns"], options["rows"]
        assert options["min_columns"] == width and options["min_rows"] == height
        assert 1 <= width <= columns
        spans.append((width, height))
    placements = pack(spans, columns)
    assert rows_used(placements) <= rows
    previous = columns
    for row in range(rows_used(placements)):
        cells = sorted(
            c
            for p in placements
            if p is not None and p.row <= row < p.bottom
            for c in range(p.column, p.column + p.columns)
        )
        assert cells == list(range(len(cells))), f"{view['path']}: hole in row {row}"
        assert len(cells) <= previous, f"{view['path']}: row {row} wider than the one above"
        previous = len(cells)


def check_dashboard(dashboard: dict[str, Any], data: GeneratorInput) -> None:
    """Invariants every generated dashboard must hold."""
    profile = data.display.profile
    language = LABELS.get(data.language.split("-")[0], LABELS["en"])
    assert set(dashboard) == {"title", "views"}
    views = dashboard["views"]
    paths = [view["path"] for view in views]
    nav = [p for p in paths if p != "more"]
    assert paths[0] == "home"
    assert nav == [p for p in ("home", "climate", "media", "scenes") if p in nav]
    if "more" in paths:
        assert paths[-1] == "more"
    known = known_entities(data)
    index = all_entities(data)
    controls: dict[str, set[str]] = {}

    for view in views:
        assert view["type"] == "sections"
        assert view["top_margin"] is False
        assert view["title"] == language.get(view["path"], NAV[view["path"]][0])
        has_footer = "footer" in view
        assert has_footer == (len(nav) >= 2 or view["path"] == "more")
        grid = compute_grid(profile, footer=has_footer)
        assert view["max_columns"] == grid.section_columns
        assert len(view["sections"]) == 1
        assert view["sections"][0]["column_span"] == grid.section_columns
        check_rows(view, grid.card_columns, grid.rows)

        if has_footer:
            footer = view["footer"]
            pill = footer["card"]
            assert pill["type"] == "custom:wall-display-nav"
            assert [item["path"] for item in pill["items"]] == nav
            assert footer["max_width"] == min(len(nav) * 76 + 16, profile.width - 16)
            for item in pill["items"]:
                assert item["label"] == language[item["path"]][:8]
                assert len(item["label"]) <= 8
                assert "/" not in item["path"]
                assert item["icon"] == NAV[item["path"]][1]
                if "entity" in item:
                    assert item["path"] in ("climate", "media")
                    assert (
                        item["entity"].split(".")[0]
                        == {
                            "climate": "climate",
                            "media": "media_player",
                        }[item["path"]]
                    )

        assert referenced_entities(view) <= known
        for card in walk(section_cards(view)):
            entity = index.get(card.get("entity", ""))
            if entity is not None and is_secure(entity):
                assert card["type"] == "tile"
                assert card["tap_action"] == {"action": "more-info"}
                assert card["icon_tap_action"] == {"action": "none"}
                assert card["hold_action"] == {"action": "more-info"}
                assert "features" not in card
            for action in actions(card):
                if action.get("action") in ("toggle", "perform-action"):
                    target = card.get("entity")
                    if action.get("action") == "perform-action":
                        target = action["target"]["entity_id"]
                    assert target in index and not is_secure(index[target])
            if action_target := card.get("tap_action", {}).get("navigation_path"):
                assert "/" not in action_target
            if card["type"] == "tile" and card.get("name") and "vertical" in card:
                assert card["vertical"] is True
            if is_control(card):
                controls.setdefault(card["entity"], set()).add(view["path"])
            if card["type"] == "vertical-stack":
                pytest.fail("vertical-stack does not fill its rows")
    for entity_id, where in controls.items():
        assert len(where) == 1, f"{entity_id} is controlled on {where}"


@pytest.mark.parametrize("profile_id", sorted(PROFILES))
def test_profiles(profile_id: str) -> None:
    data = sample_house.sample_input(PROFILES[profile_id])
    check_dashboard(build_dashboard(data), data)


@pytest.mark.parametrize("variant", sorted(sample_house.VARIANTS))
@pytest.mark.parametrize("profile_id", sorted(PROFILES))
def test_variants(variant: str, profile_id: str) -> None:
    make_input, kwargs = sample_house.VARIANTS[variant]
    data = make_input(PROFILES[profile_id], **kwargs)
    check_dashboard(build_dashboard(data), data)


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_sweep(width: int, height: int) -> None:
    for make_input in (sample_house.sample_input, sample_house.entrance_input):
        data = make_input(sized(width, height))
        check_dashboard(build_dashboard(data), data)


def crowded(profile: Profile) -> GeneratorInput:
    """A kitchen with far more entities than fit anywhere."""
    base = sample_house.sample_input(profile)
    lights = tuple(
        LightInfo(f"light.kitchen_{i:02}", f"Light {i:02}", KITCHEN, dimmable=True)
        for i in range(30)
    )
    locks = (EntityInfo("lock.kitchen_door", "Back door", KITCHEN),)
    climates = tuple(
        ClimateInfo(f"climate.kitchen_{i}", f"Zone {i}", KITCHEN, hvac_modes=("off", "heat"))
        for i in range(8)
    )
    players = tuple(
        EntityInfo(f"media_player.kitchen_{i}", f"Player {i}", KITCHEN) for i in range(8)
    )
    scenes = tuple(EntityInfo(f"scene.kitchen_{i:02}", f"Scene {i:02}", KITCHEN) for i in range(40))
    sensors = (
        EntityInfo("sensor.kitchen_temp", "Temperature", KITCHEN, "temperature"),
        EntityInfo("sensor.kitchen_hum", "Humidity", KITCHEN, "humidity"),
    )
    return replace(
        base,
        area_entities=base.area_entities + lights + locks,
        climates=base.climates + climates,
        media_players=base.media_players + players,
        scenes=base.scenes + scenes,
        area_sensors=sensors,
    )


@pytest.mark.parametrize(("width", "height"), SIZES[::3])
def test_sweep_crowded(width: int, height: int) -> None:
    data = crowded(sized(width, height))
    dashboard = build_dashboard(data)
    check_dashboard(dashboard, data)
    home = section_cards(dashboard["views"][0])
    assert sum(1 for c in home if c.get("entity", "").startswith("light.")) <= 12


@pytest.mark.parametrize(("width", "height"), SIZES[::2])
def test_plans_fit_without_cutting(width: int, height: int) -> None:
    """Page builders plan within the budget; the overflow cut is only a safety net."""
    for data in (
        sample_house.sample_input(sized(width, height)),
        crowded(sized(width, height)),
        sample_house.entrance_input(sized(width, height)),
    ):
        grid = compute_grid(data.display.profile)
        for page, plan in PAGE_PLANS.items():
            planned = plan(data, grid)[0]
            assert fit_to_rows(planned, grid, page) == planned


def test_square_home() -> None:
    clock, weather, *tiles = section_cards(views_of(sample())["home"])
    assert clock["type"] == "clock" and clock["no_background"]
    # 228 px wide: medium (a large clock would cut the long date).
    assert clock["clock_size"] == "medium" and clock["date_format"]
    assert weather["name"] == "Outside"
    assert weather["state_content"] == ["temperature", "state"]
    assert [c["grid_options"]["columns"] for c in (clock, weather)] == [6, 6]
    assert clock["grid_options"]["rows"] + 4 == compute_grid(SQUARE).rows
    # Climate, media and scenes have pages, so Home keeps lights, cover and switch.
    assert [t["entity"] for t in tiles] == [
        "light.kitchen_ceiling",
        "light.kitchen_counter",
        "cover.kitchen_blinds",
        "switch.kitchen_coffee",
    ]
    for tile in tiles:
        assert tile["vertical"] is True
        assert (tile["grid_options"]["columns"], tile["grid_options"]["rows"]) == (6, 2)
        assert tile["tap_action"] == {"action": "toggle"}
        assert tile["hold_action"] == {"action": "more-info"}
        assert "features" not in tile  # square never gets inline features
        assert "color" not in tile


def test_big_tiles_get_inline_features() -> None:
    home = section_cards(views_of(sample(PROFILES["shelly_xl"]))["home"])
    tiles = {c["entity"]: c for c in home if c["type"] == "tile"}
    assert tiles["light.kitchen_ceiling"]["features"] == [{"type": "light-brightness"}]
    assert tiles["cover.kitchen_blinds"]["features"] == [{"type": "cover-open-close"}]
    assert "features" not in tiles["switch.kitchen_coffee"]
    assert all(3 <= c["grid_options"]["rows"] <= 5 for c in tiles.values())


def test_landscape_info_column_is_a_grid_card() -> None:
    info = section_cards(views_of(sample(LANDSCAPE))["home"])[0]
    assert info["type"] == "grid" and info["columns"] == 1 and info["square"] is False
    clock, nested = info["cards"]
    assert clock["type"] == "clock"
    assert nested["type"] == "grid" and nested["columns"] == 1
    assert [c["type"] for c in nested["cards"]][:2] == ["tile", "area"]
    area = nested["cards"][1]
    assert area["area"] == KITCHEN and area["display_type"] == "compact"
    assert area["features"] == [{"type": "area-controls", "controls": ["light", "cover-blind"]}]
    assert "switch" not in area["features"][0]["controls"]


def test_portrait_room_card_and_spare_rows() -> None:
    home = section_cards(views_of(sample(PORTRAIT))["home"])
    assert [c["type"] for c in home[:3]] == ["clock", "tile", "area"]
    assert home[0]["clock_size"] == "medium"  # 228 px: no large clock
    assert home[0]["grid_options"]["rows"] == home[1]["grid_options"]["rows"] <= 4
    tiles = [c for c in home if c["type"] == "tile" and c["entity"].startswith("light.")]
    assert all(t["grid_options"]["rows"] >= 4 for t in tiles)  # spare rows went to tiles
    # Tablet portrait has room left for the forecast.
    tablet = section_cards(views_of(sample(PROFILES["tablet_portrait"]))["home"])
    assert "weather-forecast" in [c["type"] for c in tablet]


def test_portrait_without_forecast_follows_l2() -> None:
    home = section_cards(views_of(sample(PORTRAIT, weather_features=0))["home"])
    clock, weather, room, *tiles = home
    assert clock["grid_options"]["rows"] == weather["grid_options"]["rows"] <= 4
    assert room["type"] == "area" and room["grid_options"]["rows"] <= 3
    assert all(2 <= t["grid_options"]["rows"] <= 5 for t in tiles)


def test_landscape_heat_single_side_card_is_a_strip() -> None:
    cards = section_cards(views_of(sample(PROFILES["shelly_xl"]))["climate"])
    thermostat, strip = cards
    grid = compute_grid(PROFILES["shelly_xl"])
    assert thermostat["grid_options"]["columns"] == strip["grid_options"]["columns"] == 36
    assert thermostat["grid_options"]["rows"] == grid.rows - 1
    assert strip["grid_options"]["rows"] == 1 and "vertical" not in strip


def test_entrance_summaries_vertical_in_tall_slots() -> None:
    home = section_cards(views_of(sample_house.entrance_input(PROFILES["shelly_xl"]))["home"])
    summaries = [c for c in home if c["type"] == "home-summary"]
    assert summaries and all(c.get("vertical") is True for c in summaries)
    assert all(c["grid_options"]["rows"] >= 2 for c in summaries)


def test_busy_room_more_view_fills() -> None:
    for profile_id in ("shelly_wall_display", "shelly_x2_landscape"):
        profile = PROFILES[profile_id]
        views = views_of(sample_house.busy_input(profile))
        empty, _ = empty_cells(views["more"], profile)
        assert empty == 0
        assert all(c["grid_options"]["rows"] >= 2 for c in section_cards(views["more"]))


def test_scenes_page_threshold_and_house_scenes() -> None:
    views = views_of(sample())
    scenes = [c["entity"] for c in section_cards(views["scenes"])]
    assert scenes == [
        "scene.kitchen_breakfast",
        "scene.kitchen_cooking",
        "scene.all_off",
        "scene.away",
        "scene.good_night",
    ]
    # Without the area-less scenes only 2 remain: no page, they stay on Home.
    views = views_of(sample(house_scenes=()))
    assert "scenes" not in views
    home_refs = referenced_entities(views["home"])
    assert {"scene.kitchen_breakfast", "scene.kitchen_cooking"} <= home_refs


def test_scene_and_script_tiles() -> None:
    script = EntityInfo("script.kitchen_dishes", "Dishes", KITCHEN)
    data = sample(scenes=(*sample().scenes, script))
    cards = section_cards(views_of(data)["scenes"])
    by_entity = {c["entity"]: c for c in cards}
    scene = by_entity["scene.kitchen_cooking"]
    run = {
        "action": "perform-action",
        "perform_action": "scene.turn_on",
        "target": {"entity_id": "scene.kitchen_cooking"},
    }
    assert scene["type"] == "tile"
    assert scene["tap_action"] == run and scene["icon_tap_action"] == run
    assert scene["hold_action"] == {"action": "none"}
    assert scene["hide_state"] is True
    assert scene["icon"] == "mdi:pot-steam"  # no own icon: picked from the name
    script_card = by_entity["script.kitchen_dishes"]
    assert script_card["tap_action"]["perform_action"] == "script.turn_on"
    assert "hide_state" not in script_card
    assert len({(c["grid_options"]["columns"], c["grid_options"]["rows"]) for c in cards}) == 1
    assert all(c["grid_options"]["rows"] <= 3 for c in cards)


def test_room_locks_are_status_only() -> None:
    lock = EntityInfo("lock.kitchen_door", "Back door", KITCHEN)
    garage = EntityInfo("cover.kitchen_garage", "Garage", KITCHEN, "garage", 3)
    data = sample(area_entities=(*sample().area_entities, garage, lock))
    tiles = section_cards(views_of(data)["home"])
    names = [c.get("entity") for c in tiles if c["type"] in ("tile", "shortcut")]
    # Lowest rank: after the coffee machine; the last one may sit behind "+N more".
    assert names.index("switch.kitchen_coffee") < names.index("cover.kitchen_garage")


def test_climate_page_square_has_no_features() -> None:
    cards = section_cards(views_of(sample())["climate"])
    assert len(cards) == 1
    assert cards[0]["type"] == "thermostat" and "features" not in cards[0]
    assert cards[0]["grid_options"]["rows"] == compute_grid(SQUARE).rows


def test_climate_page_landscape_mode_tile() -> None:
    cards = section_cards(views_of(sample(LANDSCAPE))["climate"])
    thermostat, mode, humidity = cards
    assert "features" not in thermostat
    assert mode["entity"] == "climate.kitchen_heating"
    assert mode["name"] == "Mode" and mode["hide_state"] is True
    assert mode["features"] == [
        {"type": "climate-hvac-modes", "style": "icons", "hvac_modes": ["off", "heat", "auto"]}
    ]
    assert humidity["entity"] == "sensor.kitchen_display_humidity"
    # No second room temperature next to the thermostat.
    assert "sensor.kitchen_display_temperature" not in referenced_entities(cards)


def test_climate_page_large_keeps_features() -> None:
    thermostat = section_cards(views_of(sample(PROFILES["shelly_xl"]))["climate"])[0]
    assert [f["type"] for f in thermostat["features"]] == [
        "climate-hvac-modes",
        "climate-preset-modes",
    ]
    assert thermostat["features"][1]["style"] == "icons"


def test_media_page_small_screens_use_a_tile() -> None:
    views = views_of(sample())
    rows = compute_grid(SQUARE).rows
    player, radio = section_cards(views["media"])
    assert player["type"] == "tile"
    assert player["entity"] == "media_player.kitchen_speaker"  # pinned
    assert player["state_content"] == ["media_title", "media_artist"]
    assert player["features"] == [
        {"type": "media-player-playback"},
        {"type": "media-player-volume-slider"},
    ]
    assert player["features_position"] == "bottom"
    assert player["grid_options"]["rows"] >= 3
    assert radio["entity"] == "media_player.kitchen_radio" and "features" not in radio
    assert player["grid_options"]["rows"] + radio["grid_options"]["rows"] == rows
    assert "more" not in views


def test_media_page_large_screens_use_media_control() -> None:
    profile = PROFILES["shelly_xl"]
    rows = compute_grid(profile).rows
    control, volume, radio = section_cards(views_of(sample(profile))["media"])
    assert control["type"] == "media-control"
    assert control["entity"] == "media_player.kitchen_speaker"
    assert control["grid_options"]["columns"] == 36
    assert control["grid_options"]["rows"] >= 3
    assert volume["entity"] == "media_player.kitchen_speaker"
    assert volume["name"] == "Volume" and volume["icon"] == "mdi:volume-high"
    assert volume["hide_state"] is True
    assert volume["features"] == [{"type": "media-player-volume-slider"}]
    assert volume["features_position"] == "inline"
    assert volume["grid_options"]["rows"] == 1
    assert sum(c["grid_options"]["rows"] for c in (control, volume, radio)) == rows


def test_media_more_slot_when_players_do_not_fit() -> None:
    extra = tuple(
        EntityInfo(f"media_player.kitchen_{i}", f"Player {i}", KITCHEN) for i in range(12)
    )
    views = views_of(sample(media_players=(*sample().media_players, *extra)))
    cards = section_cards(views["media"])
    more = cards[-1]
    assert more["type"] == "shortcut" and more["label"].startswith("+")
    assert more["tap_action"] == {"action": "navigate", "navigation_path": "more"}
    listed = [c["entity"] for c in section_cards(views["more"])]
    assert len(listed) == int(more["label"].split()[0][1:])
    pill = [i["path"] for i in views["home"]["footer"]["card"]["items"]]
    assert "more" not in pill
    # The More view has the pill, so there is a way back.
    assert views["more"]["footer"]["card"]["items"][0]["path"] == "home"


@pytest.mark.parametrize(
    "profile_id", ["shelly_wall_display", "shelly_x2_portrait", "shelly_xl", "tablet_portrait"]
)
def test_media_page_fills_the_rows(profile_id: str) -> None:
    profile = PROFILES[profile_id]
    grid = compute_grid(profile)
    cards = section_cards(views_of(sample(profile))["media"])
    full = [c for c in cards if c["grid_options"]["columns"] == grid.card_columns]
    assert sum(c["grid_options"]["rows"] for c in full) == grid.rows
    assert cards[0]["grid_options"]["rows"] >= 3


@pytest.mark.parametrize(
    "profile_id", ["shelly_xl", "tablet_landscape", "tablet_portrait", "shelly_x2_portrait"]
)
def test_home_looks_full_on_large_screens(profile_id: str) -> None:
    """Spare rows go to the forecast and bigger tiles, not to blank space."""
    profile = PROFILES[profile_id]
    grid = compute_grid(profile)
    spans = [
        (c["grid_options"]["columns"], c["grid_options"]["rows"])
        for c in section_cards(views_of(sample(profile))["home"])
    ]
    placements = pack(spans, grid.card_columns)
    assert rows_used(placements) == grid.rows
    covered = sum(p.rows * p.columns for p in placements if p is not None)
    assert covered == grid.rows * grid.card_columns


def test_nav_pill_live_entities() -> None:
    items = views_of(sample())["home"]["footer"]["card"]["items"]
    assert items == [
        {"path": "home", "label": "Home", "icon": "mdi:home"},
        {
            "path": "climate",
            "label": "Climate",
            "icon": "mdi:thermostat",
            "entity": "climate.kitchen_heating",
        },
        {
            "path": "media",
            "label": "Media",
            "icon": "mdi:speaker",
            "entity": "media_player.kitchen_speaker",
        },
        {"path": "scenes", "label": "Scenes", "icon": "mdi:palette"},
    ]


def test_nav_order_is_fixed() -> None:
    views = build_dashboard(sample(pages=("scenes", "climate")))["views"]
    assert [v["path"] for v in views] == ["home", "climate", "scenes"]


def test_disabled_pages_keep_entities_on_home() -> None:
    views = views_of(sample(pages=("media",), house_scenes=()))
    assert [p for p in views if p != "more"] == ["home", "media"]
    refs = referenced_entities([views["home"], views.get("more", {})])
    assert {"climate.kitchen_heating", "scene.kitchen_breakfast"} <= refs
    assert "media_player.kitchen_speaker" not in referenced_entities(section_cards(views["home"]))


def test_home_only_has_no_footer_and_more_rows() -> None:
    views = views_of(sample(pages=()))
    home = views["home"]
    assert "footer" not in home
    grid = compute_grid(SQUARE, footer=False)
    assert grid.rows == 7


def test_german_labels() -> None:
    views = views_of(sample(LANDSCAPE, language="de-DE"))
    assert [i["label"] for i in views["home"]["footer"]["card"]["items"]] == [
        "Start",
        "Klima",
        "Medien",
        "Szenen",
    ]
    info = section_cards(views["home"])[0]
    assert info["cards"][1]["cards"][0]["name"] == "Draußen"
    xl = views_of(sample(PROFILES["shelly_xl"], language="de"))
    assert any(c.get("name") == "Lautstärke" for c in section_cards(xl["media"]))
    assert any(c.get("name") == "Modus" for c in section_cards(views["climate"]))
    assert views["climate"]["title"] == "Klima"


def test_unknown_language_falls_back_to_english() -> None:
    views = views_of(sample(language="xx"))
    assert views["climate"]["title"] == "Climate"


def test_duplicate_names_get_their_area() -> None:
    kitchen = LightInfo("light.kitchen_lamp", "Lamp", KITCHEN)
    living = LightInfo("light.living_room_lamp", "Lamp", "living_room")
    data = sample(
        area_entities=(kitchen,),
        overrides=Overrides(pinned=("light.living_room_lamp",)),
    )
    data = replace(data, area_entities=(kitchen, living))
    names = {
        c["entity"]: c["name"]
        for c in section_cards(views_of(data)["home"])
        if c["type"] == "tile" and c.get("entity", "").startswith("light.")
    }
    assert names["light.kitchen_lamp"] == "Kitchen Lamp"
    assert names["light.living_room_lamp"] == "Living Room Lamp"


def test_entrance_home() -> None:
    data = sample_house.entrance_input(SQUARE)
    views = views_of(data)
    home = views["home"]
    assert "footer" not in home
    if "more" in views:  # only "+N more" leads there; its pill (Home only) leads back
        assert [i["path"] for i in views["more"]["footer"]["card"]["items"]] == ["home"]
    small = views_of(sample_house.entrance_input(sized(480, 320)))
    assert list(small) == ["home", "more"]
    assert [i["path"] for i in small["more"]["footer"]["card"]["items"]] == ["home"]
    cards = section_cards(home)
    types = [c["type"] for c in cards]
    first_summary = types.index("home-summary")
    assert cards[first_summary - 1]["entity"] == "person.ben"  # people before the summaries
    lights, security = [c for c in cards if c["type"] == "home-summary"]
    assert lights == {
        "type": "home-summary",
        "summary": "light",
        "grid_options": lights["grid_options"],
    }
    assert security["summary"] == "security"
    assert {"entity": "binary_sensor.bathroom_window"} in security["alert_entities"]
    assert "tap_action" not in security
    persons = [c for c in cards if c.get("entity", "").startswith("person.")]
    assert all(c["show_entity_picture"] is True for c in persons)
    assert "tap_action" not in persons[0]
    everything = [*cards, *(section_cards(views["more"]) if "more" in views else [])]
    for entity_id in ("lock.front_door", "alarm_control_panel.home_alarm", "cover.garage_door"):
        card = next(c for c in everything if c.get("entity") == entity_id)
        assert card["tap_action"] == {"action": "more-info"}
        assert card["icon_tap_action"] == {"action": "none"}
    refs = referenced_entities(everything)
    assert {"script.all_off", "scene.away", "scene.good_night"} <= refs
    # The "All off" scene duplicates the script by name: only the script is shown.
    assert "scene.all_off" not in referenced_entities(build_dashboard(data))


def test_window_covers_get_a_pressable_icon() -> None:
    tiles = {c.get("entity"): c for c in section_cards(views_of(sample())["home"])}
    assert tiles["cover.kitchen_blinds"]["icon_tap_action"] == {"action": "toggle"}
    assert "icon_tap_action" not in tiles["light.kitchen_ceiling"]


def test_scene_icons_from_names() -> None:
    from custom_components.walldisplay_dashboards.generator.cards import action_icon

    assert action_icon("Movie night") == "mdi:movie-open"
    assert action_icon("Frühstück") == "mdi:coffee"
    assert action_icon("Alles aus") == "mdi:power"
    assert action_icon("Gemütlich") == "mdi:palette"
    cards = {c["entity"]: c for c in section_cards(views_of(sample())["scenes"])}
    assert cards["scene.kitchen_cooking"]["icon"] == "mdi:pot-steam"
    assert cards["scene.kitchen_breakfast"]["icon"] == "mdi:coffee"
    assert "icon" not in cards["scene.away"]  # it has its own icon


def test_no_forecast_without_forecast_support() -> None:
    for profile in (PORTRAIT, PROFILES["shelly_xl"], PROFILES["tablet_portrait"]):
        without = build_dashboard(sample(profile, weather_features=0))
        assert not any(c["type"] == "weather-forecast" for c in walk(without))
    with_forecast = build_dashboard(sample(PROFILES["shelly_xl"]))
    assert any(c["type"] == "weather-forecast" for c in walk(with_forecast))
    daily = build_dashboard(sample(PROFILES["shelly_xl"], weather_features=1))
    kinds = {c["forecast_type"] for c in walk(daily) if c["type"] == "weather-forecast"}
    assert kinds == {"daily"}


def test_narrow_weather_tile_shows_temperature_only() -> None:
    info = section_cards(views_of(sample(LANDSCAPE))["home"])[0]
    assert info["cards"][1]["cards"][0]["state_content"] == ["temperature"]  # 228 px
    wide = section_cards(views_of(sample(PROFILES["shelly_xl"]))["home"])[0]
    assert wide["cards"][1]["cards"][0]["state_content"] == ["temperature", "state"]


def test_empty_room() -> None:
    views = views_of(sample_house.empty_input(SQUARE))
    assert list(views) == ["home"]
    cards = section_cards(views["home"])
    types = [c["type"] for c in cards]
    assert types.count("tile") == 2  # weather + the lamp
    assert "weather-forecast" in types


def test_empty_room_helper() -> None:
    from custom_components.walldisplay_dashboards.generator.room import is_empty_room

    data = sample_house.empty_input(SQUARE)
    assert not is_empty_room(data)
    assert is_empty_room(replace(data, area_entities=()))


@pytest.mark.parametrize(
    "name", sorted(p.stem for p in GOLDENS.glob("*.json") if p.stem != "states")
)
def test_goldens(name: str) -> None:
    """Regenerate with `python tools/preview/dump_goldens.py` after intended changes."""
    expected = json.loads((GOLDENS / f"{name}.json").read_text(encoding="utf-8"))
    assert dump_goldens.build_goldens()[name] == expected


def test_golden_states_cover_entities() -> None:
    states = json.loads((GOLDENS / "states.json").read_text(encoding="utf-8"))
    for dashboard in dump_goldens.build_goldens().values():
        assert referenced_entities(dashboard) <= states.keys()


def test_dashboard_budget_for_list() -> None:
    assert dashboard_budget(sample()) == {
        "rows": 6,
        "footer": True,
        "views": {p: {"rows": 6, "footer": True} for p in ("home", "climate", "media", "scenes")},
    }
    small = dashboard_budget(sample_house.entrance_input(sized(480, 320)))
    assert small == {
        "rows": 4,
        "footer": False,
        "views": {"home": {"rows": 4, "footer": False}, "more": {"rows": 3, "footer": True}},
    }


# Documented exceptions (design-spacing-2): one spare row on tablet Home.
EMPTY_ROW_ALLOWED = {("tablet_portrait", "home"), ("tablet_landscape", "home")}


def empty_cells(view: dict[str, Any], profile: Profile) -> tuple[int, int]:
    """(empty grid cells, cells per row) of a view."""
    grid = compute_grid(profile, footer="footer" in view)
    spans = [(c["grid_options"]["columns"], c["grid_options"]["rows"]) for c in section_cards(view)]
    covered = sum(p.rows * p.columns for p in pack(spans, grid.card_columns) if p is not None)
    return grid.rows * grid.card_columns - covered, grid.card_columns


@pytest.mark.parametrize("variant", ["kitchen", *sorted(sample_house.VARIANTS)])
@pytest.mark.parametrize("profile_id", sorted(PROFILES))
def test_no_empty_grid_area(variant: str, profile_id: str) -> None:
    profile = PROFILES[profile_id]
    if variant == "kitchen":
        data = sample_house.sample_input(profile)
    else:
        make_input, kwargs = sample_house.VARIANTS[variant]
        data = make_input(profile, **kwargs)
    for view in build_dashboard(data)["views"]:
        empty, per_row = empty_cells(view, profile)
        allowed = per_row if (profile_id, view["path"]) in EMPTY_ROW_ALLOWED else 0
        assert empty <= allowed, f"{variant} {view['path']}: {empty} empty cells"


@pytest.mark.parametrize("variant", sorted(sample_house.VARIANTS))
@pytest.mark.parametrize("profile_id", sorted(PROFILES))
def test_clock_never_exceeds_ha_max_rows(variant: str, profile_id: str) -> None:
    make_input, kwargs = sample_house.VARIANTS[variant]
    for card in walk(build_dashboard(make_input(PROFILES[profile_id], **kwargs))):
        if card["type"] == "clock" and "grid_options" in card:
            assert card["grid_options"]["rows"] <= 4


def test_names_sort_naturally() -> None:
    from custom_components.walldisplay_dashboards.generator.room import natural_key

    names = ["Lamp 10", "lamp 2", "Lamp 1", "Arbeitsplatte"]
    assert sorted(names, key=natural_key) == ["Arbeitsplatte", "Lamp 1", "lamp 2", "Lamp 10"]
    more = section_cards(views_of(sample_house.busy_input(SQUARE))["more"])
    lamps = [c["name"] for c in more if c["entity"].startswith("light.kitchen_lamp")]
    assert lamps == sorted(lamps, key=natural_key)
