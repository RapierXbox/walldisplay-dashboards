"""The Indoor tile on Home (design pass 3, pure, sample house).

The twin of the weather tile: the room temperature (precedence in
docs/contracts.md), name "Indoor"/"Innen", a plain icon, tap for more-info.
Square: under the weather tile beside the 2-row clock. Landscape/portrait:
under the weather tile, and the room card shows no sensor values.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "preview"))

import sample_house

from custom_components.walldisplay_dashboards.generator import build_dashboard
from custom_components.walldisplay_dashboards.generator.cards import indoor_tile
from custom_components.walldisplay_dashboards.generator.room import indoor_sensors
from custom_components.walldisplay_dashboards.models import (
    EntityInfo,
    GeneratorInput,
    Overrides,
    Profile,
)
from custom_components.walldisplay_dashboards.profiles import PROFILES

SQUARE = PROFILES["shelly_wall_display"]
LANDSCAPE = PROFILES["shelly_x2_landscape"]
PORTRAIT = PROFILES["shelly_x2_portrait"]
KITCHEN = sample_house.KITCHEN
TEMP = sample_house.INDOOR_TEMPERATURE
HUMIDITY = sample_house.INDOOR_HUMIDITY
ELSEWHERE = "sensor.living_room_temperature"
ICON = "mdi:home-thermometer-outline"


def kitchen(profile: Profile = SQUARE, **changes: Any) -> GeneratorInput:
    """The sample kitchen; display fields (overrides, sensors, weather) go to the display."""
    data = sample_house.sample_input(profile)
    fields = ("overrides", "indoor_temperature", "indoor_humidity", "weather_entity")
    display = {k: changes.pop(k) for k in list(changes) if k in fields}
    return replace(data, display=replace(data.display, **display), **changes)


def without_sensors(profile: Profile = SQUARE) -> GeneratorInput:
    return kitchen(profile, indoor_temperature=None, indoor_humidity=None, area_sensors=())


def home(data: GeneratorInput) -> list[dict[str, Any]]:
    return build_dashboard(data)["views"][0]["sections"][0]["cards"]


def walk(node: Any):
    if isinstance(node, dict):
        if "type" in node:
            yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def indoor_tiles(data: GeneratorInput) -> list[dict[str, Any]]:
    return [c for c in walk(home(data)) if c.get("icon") in (ICON, "mdi:water-percent")]


def size(card: dict[str, Any]) -> tuple[int, int]:
    return card["grid_options"]["columns"], card["grid_options"]["rows"]


def info_parts(data: GeneratorInput) -> list[dict[str, Any]]:
    info = home(data)[0]
    assert info["type"] == "grid"
    return info["cards"][1]["cards"]


# --- The tile ---------------------------------------------------------------


def test_indoor_tile() -> None:
    card = indoor_tile(TEMP, HUMIDITY, "de")
    assert card == {
        "type": "tile",
        "entity": TEMP,
        "name": "Innen",
        "icon": ICON,
        "tap_action": {"action": "more-info"},
        "icon_tap_action": {"action": "none"},
    }
    assert indoor_tile(TEMP, None, "en")["name"] == "Indoor"  # type: ignore[index]
    humidity_only = indoor_tile(None, HUMIDITY, "en")
    assert humidity_only is not None
    assert humidity_only["entity"] == HUMIDITY and humidity_only["icon"] == "mdi:water-percent"
    climate = indoor_tile("climate.kitchen", None, "en", vertical=True)
    assert climate is not None
    assert climate["state_content"] == ["current_temperature"] and climate["vertical"] is True
    assert indoor_tile(None, None, "en") is None


# --- Square -----------------------------------------------------------------


@pytest.mark.parametrize("profile_id", ["shelly_wall_display", "shelly_x1i", "nspanel_pro"])
def test_square_twin_tiles(profile_id: str) -> None:
    profile = PROFILES[profile_id]
    before = home(without_sensors(profile))
    clock, weather, indoor, *tiles = home(kitchen(profile))
    assert clock["type"] == "clock" and size(clock) == (6, 2)
    assert weather["name"] == "Outside" and size(weather) == (6, 1) and "vertical" not in weather
    assert weather["state_content"] == ["temperature"]  # 228 px: temperature only
    assert indoor["type"] == "tile" and indoor["entity"] == TEMP and indoor["name"] == "Indoor"
    assert size(indoor) == size(weather) and "vertical" not in indoor
    assert "state_content" not in indoor  # temperature only: humidity is on Climate
    # Same strip height as without the Indoor tile; the tiles keep their size.
    assert size(before[0]) == size(clock)
    assert [size(t) for t in tiles] == [size(t) for t in before[2:]]


def test_square_without_indoor_sensors_is_unchanged() -> None:
    clock, weather, *_ = home(without_sensors())
    assert size(clock) == size(weather) == (6, 2)
    assert weather["vertical"] is True
    assert weather["state_content"] == ["temperature", "state"]
    assert not indoor_tiles(without_sensors())


def test_square_german_labels_and_options() -> None:
    _, weather, indoor, *_ = home(sample_house.ben_input(SQUARE))
    assert weather["name"] == "Draußen"
    assert indoor["name"] == "Innen"
    # The option wins over the display's own sensor (precedence in docs/contracts.md).
    assert indoor["entity"] == sample_house.BEN_TEMPERATURE.entity_id


def test_square_one_row_strip_has_no_indoor_tile() -> None:
    """More than 8 controls: a 1-row strip and the compact list (nothing taken from it)."""
    cards = home(sample_house.busy_input(SQUARE))
    assert size(cards[0]) == (6, 1)
    assert [c["type"] for c in cards[:2]] == ["clock", "tile"]
    assert not indoor_tiles(sample_house.busy_input(SQUARE))


def test_square_without_weather() -> None:
    clock, indoor, *_ = home(kitchen(weather_entity=None))
    assert size(clock) == (6, 2)
    assert indoor["name"] == "Indoor" and size(indoor) == (6, 2) and indoor["vertical"] is True


def guest_room(profile: Profile, temperature: str | None) -> GeneratorInput:
    """One lamp and no pages: the strip gets the spare rows (and the forecast)."""
    data = sample_house.empty_input(profile)
    return replace(data, display=replace(data.display, indoor_temperature=temperature))


def test_square_strip_with_forecast() -> None:
    """2 rows for clock, weather and indoor; the forecast only with 2 more."""
    tall = Profile("custom", "Custom", 480, 560)
    plain = home(guest_room(tall, None))
    clock, weather, indoor, forecast, lamp = home(guest_room(tall, TEMP))
    assert size(clock) == (6, 2) and size(weather) == size(indoor) == (6, 1)
    assert forecast["type"] == "weather-forecast" and size(forecast) == size(plain[2])
    assert size(lamp) == size(plain[3])
    # A 3-row strip: clock, weather and indoor take it all (a 1-row forecast is cut off).
    before = home(guest_room(SQUARE, None))
    assert [c["type"] for c in before] == ["clock", "tile", "weather-forecast", "tile"]
    clock, weather, indoor, lamp = home(guest_room(SQUARE, TEMP))
    assert size(clock) == (6, 3) and size(weather) == (6, 2) and size(indoor) == (6, 1)
    assert weather["vertical"] is True and size(lamp) == size(before[3])


# --- Landscape and portrait ---------------------------------------------------


@pytest.mark.parametrize("language", ["en", "de"])
def test_landscape_indoor_tile_under_the_weather(language: str) -> None:
    data = replace(kitchen(LANDSCAPE), language=language)
    weather, indoor, room, *_ = info_parts(data)
    assert weather["name"] == {"en": "Outside", "de": "Draußen"}[language]
    assert indoor["name"] == {"en": "Indoor", "de": "Innen"}[language]
    assert indoor["entity"] == TEMP
    assert "vertical" not in weather and "vertical" not in indoor
    # One indoor value: the room card keeps name, alerts and controls, no sensors.
    assert room["type"] == "area" and room["sensor_classes"] == []
    assert room["features"] == [{"type": "area-controls", "controls": ["light", "cover-blind"]}]
    assert room["alert_classes"] == ["window", "door", "moisture"]


def test_landscape_option_feeds_the_tile() -> None:
    data = kitchen(LANDSCAPE, overrides=Overrides(temperature_entity=ELSEWHERE))
    assert info_parts(data)[1]["entity"] == ELSEWHERE


def test_landscape_tall_info_column_twins() -> None:
    """From 8 rows the weather tile is vertical, and so is its twin."""
    weather, indoor, *_ = info_parts(kitchen(PROFILES["shelly_xl"]))
    assert weather["vertical"] is True and indoor["vertical"] is True


def test_landscape_without_sensors() -> None:
    parts = info_parts(without_sensors(LANDSCAPE))
    assert [c["type"] for c in parts][:2] == ["tile", "area"]
    assert parts[1]["sensor_classes"] == []


@pytest.mark.parametrize("profile_id", ["shelly_x2_portrait", "tablet_portrait"])
def test_portrait_indoor_tile_beside_the_clock(profile_id: str) -> None:
    profile = PROFILES[profile_id]
    before = home(without_sensors(profile))
    clock, weather, indoor, room, *rest = home(kitchen(profile))
    assert size(clock) == size(before[0])
    assert size(weather)[1] + size(indoor)[1] == size(clock)[1]
    assert size(weather)[1] >= size(indoor)[1] >= 1
    assert indoor["entity"] == TEMP
    assert room["type"] == "area" and room["sensor_classes"] == []
    assert [size(c) for c in rest] == [size(c) for c in before[3:]]


def test_no_area_still_shows_the_indoor_tile() -> None:
    data = kitchen(LANDSCAPE)
    no_area = replace(data, display=replace(data.display, area_id=None))
    types = [c["type"] for c in info_parts(no_area)]
    assert "area" not in types and len(indoor_tiles(no_area)) == 1


def test_designated_and_humidity_only() -> None:
    designated = kitchen(LANDSCAPE, area_temperature="sensor.designated")
    assert indoor_sensors(designated)[0] == "sensor.designated"
    sensors = (EntityInfo("sensor.kitchen_hum", "Humidity", KITCHEN, "humidity"),)
    humid = kitchen(indoor_temperature=None, indoor_humidity=None, area_sensors=sensors)
    (tile,) = indoor_tiles(humid)
    assert tile["entity"] == "sensor.kitchen_hum"


@pytest.mark.parametrize("profile_id", sorted(PROFILES))
def test_ben_shows_the_option_everywhere(profile_id: str) -> None:
    rows = indoor_tiles(sample_house.ben_input(PROFILES[profile_id]))
    assert [(t["entity"], t["name"]) for t in rows] == [
        (sample_house.BEN_TEMPERATURE.entity_id, "Innen")
    ]
