"""Generator tests for the room options: room sensors, thermostats from any room,
the Home tile limit and the display device's own entities (pure, sample house)."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "preview"))

import sample_house

from custom_components.walldisplay_dashboards.generator import build_dashboard
from custom_components.walldisplay_dashboards.generator.info import ClimateInfo, LightInfo
from custom_components.walldisplay_dashboards.generator.room import (
    room_card_sensors,
    room_humidity,
    room_temperature,
)
from custom_components.walldisplay_dashboards.models import EntityInfo, GeneratorInput, Overrides
from custom_components.walldisplay_dashboards.profiles import PROFILES

SQUARE = PROFILES["shelly_wall_display"]
LANDSCAPE = PROFILES["shelly_x2_landscape"]
PORTRAIT = PROFILES["shelly_x2_portrait"]
KITCHEN = sample_house.KITCHEN
DISPLAY_DEVICE = "display-device"
AREA_TEMP = EntityInfo("sensor.kitchen_temperature", "Temperature", KITCHEN, "temperature")
AREA_TEMP_2 = EntityInfo("sensor.kitchen_window_temperature", "Window", KITCHEN, "temperature")
AREA_HUMIDITY = EntityInfo("sensor.kitchen_humidity", "Humidity", KITCHEN, "humidity")
LIVING_CLIMATE = ClimateInfo(
    "climate.living_room", "Living Room Thermostat", "living_room", hvac_modes=("off", "heat")
)
OFFICE_CLIMATE = ClimateInfo(
    "climate.office", "Office", "office", hvac_modes=("off", "heat", "cool")
)
SCREEN = LightInfo(
    "light.display_screen", "Bildschirm", KITCHEN, dimmable=True, device_id=DISPLAY_DEVICE
)
RELAY = EntityInfo("switch.display_relay", "Relais", KITCHEN, device_id=DISPLAY_DEVICE)


def sample(
    profile: Any = SQUARE, overrides: dict[str, Any] | None = None, **changes: Any
) -> GeneratorInput:
    """The sample kitchen with changed overrides and input fields."""
    data = sample_house.sample_input(profile)
    display = replace(
        data.display,
        overrides=replace(data.display.overrides, **(overrides or {})),
        display_device_id=DISPLAY_DEVICE,
    )
    return replace(data, display=display, **changes)


def views(data: GeneratorInput) -> dict[str, dict[str, Any]]:
    return {view["path"]: view for view in build_dashboard(data)["views"]}


def cards_of(view: dict[str, Any]) -> list[dict[str, Any]]:
    return view["sections"][0]["cards"]


def walk(node: Any):
    if isinstance(node, dict):
        if "type" in node:
            yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def room_card(data: GeneratorInput) -> dict[str, Any]:
    return next(card for card in walk(cards_of(views(data)["home"])) if card["type"] == "area")


def tile_entities(view: dict[str, Any]) -> list[str]:
    return [card["entity"] for card in cards_of(view) if "entity" in card]


# --- Room temperature and humidity -------------------------------------------


def test_room_sensor_precedence() -> None:
    """Option, then the area's designated sensor, then the display's, then an area sensor."""
    sensors = (AREA_TEMP, AREA_HUMIDITY)
    base = sample(area_sensors=sensors)
    display = sample_house.INDOOR_TEMPERATURE
    assert room_temperature(base) == display
    assert room_humidity(base) == sample_house.INDOOR_HUMIDITY

    no_display = replace(
        base, display=replace(base.display, indoor_temperature=None, indoor_humidity=None)
    )
    assert room_temperature(no_display) == AREA_TEMP.entity_id
    assert room_humidity(no_display) == AREA_HUMIDITY.entity_id
    hidden = replace(
        no_display,
        display=replace(no_display.display, overrides=Overrides(hidden=(AREA_HUMIDITY.entity_id,))),
    )
    assert room_humidity(hidden) is None

    designated = replace(base, area_temperature="sensor.designated")
    assert room_temperature(designated) == "sensor.designated"

    chosen = sample(
        overrides={"temperature_entity": "sensor.chosen", "humidity_entity": "sensor.wet"},
        area_temperature="sensor.designated",
    )
    assert room_temperature(chosen) == "sensor.chosen"
    assert room_humidity(chosen) == "sensor.wet"


def test_room_card_default_unchanged() -> None:
    """Without options the room card is HA's area card as before."""
    card = room_card(sample(LANDSCAPE))
    assert card["sensor_classes"] == ["temperature", "humidity"]
    assert "exclude_entities" not in card


def test_room_card_shows_the_room_sensor() -> None:
    """The area's other sensors of a class are excluded so the card shows the room sensor."""
    data = sample(
        LANDSCAPE,
        overrides={"temperature_entity": AREA_TEMP_2.entity_id},
        area_sensors=(AREA_TEMP, AREA_TEMP_2, AREA_HUMIDITY),
    )
    card = room_card(data)
    assert card["sensor_classes"] == ["temperature", "humidity"]
    assert card["exclude_entities"] == [AREA_TEMP.entity_id]

    # The display's own sensor, when it is one of the area's sensors, wins over the rest.
    own = EntityInfo(sample_house.INDOOR_HUMIDITY, "Humidity", KITCHEN, "humidity")
    classes, exclude = room_card_sensors(sample(area_sensors=(AREA_HUMIDITY, own)))
    assert classes == ["temperature", "humidity"]
    assert exclude == [AREA_HUMIDITY.entity_id]


def test_room_card_drops_a_sensor_it_cannot_show() -> None:
    """An option from another room, or one against the designated sensor, drops the class."""
    elsewhere = sample(
        LANDSCAPE, overrides={"temperature_entity": "sensor.living_room_temperature"}
    )
    assert room_card(elsewhere)["sensor_classes"] == ["humidity"]

    designated = sample(
        overrides={"humidity_entity": AREA_HUMIDITY.entity_id},
        area_humidity="sensor.designated_humidity",
        area_sensors=(AREA_HUMIDITY,),
    )
    assert room_card_sensors(designated) == (["temperature"], [])

    # The option naming the designated sensor needs nothing extra.
    same = sample(
        overrides={"humidity_entity": "sensor.designated_humidity"},
        area_humidity="sensor.designated_humidity",
    )
    assert room_card_sensors(same) == (["temperature", "humidity"], [])


def test_pill_shows_chosen_temperature() -> None:
    """The Climate pill item carries the chosen sensor; without it, only the climate."""

    def climate_item(data: GeneratorInput) -> dict[str, Any]:
        footer = views(data)["home"]["footer"]
        return next(i for i in footer["card"]["items"] if i["path"] == "climate")

    plain = climate_item(sample())
    assert plain["entity"] == sample_house.HEATING.entity_id
    assert "temperature_entity" not in plain
    chosen = climate_item(sample(overrides={"temperature_entity": AREA_TEMP.entity_id}))
    assert chosen["entity"] == sample_house.HEATING.entity_id
    assert chosen["temperature_entity"] == AREA_TEMP.entity_id


@pytest.mark.parametrize("profile", [LANDSCAPE, PORTRAIT])
def test_climate_page_room_values(profile: Any) -> None:
    """The chosen temperature joins humidity next to the thermostat (U3 only without it)."""

    def labels(data: GeneratorInput) -> dict[str, str]:
        return {
            card["entity"]: card["name"]
            for card in cards_of(views(data)["climate"])
            if card["type"] == "tile" and card["entity"].startswith("sensor.")
        }

    assert labels(sample(profile)) == {sample_house.INDOOR_HUMIDITY: "Humidity"}
    chosen = sample(profile, overrides={"temperature_entity": AREA_TEMP.entity_id})
    assert labels(chosen) == {
        AREA_TEMP.entity_id: "Temperature",
        sample_house.INDOOR_HUMIDITY: "Humidity",
    }
    german = replace(chosen, language="de")
    assert labels(german)[AREA_TEMP.entity_id] == "Temperatur"


# --- Thermostats from any room -----------------------------------------------


def test_chosen_climates_drive_the_climate_page() -> None:
    """In their order, from any room; the room's own thermostat moves to Home."""
    data = sample(
        LANDSCAPE,
        overrides={"climate_entities": (OFFICE_CLIMATE.entity_id, LIVING_CLIMATE.entity_id)},
        climates=(sample_house.HEATING, LIVING_CLIMATE, OFFICE_CLIMATE),
    )
    pages = views(data)
    climate = cards_of(pages["climate"])
    assert climate[0]["type"] == "thermostat"
    assert climate[0]["entity"] == OFFICE_CLIMATE.entity_id
    assert climate[0]["name"] == "Office"
    assert LIVING_CLIMATE.entity_id in tile_entities(pages["climate"])
    assert sample_house.HEATING.entity_id not in tile_entities(pages["climate"])
    assert sample_house.HEATING.entity_id in tile_entities(pages["home"])
    item = next(i for i in pages["home"]["footer"]["card"]["items"] if i["path"] == "climate")
    assert item["entity"] == OFFICE_CLIMATE.entity_id


def test_chosen_climate_page_without_room_climate() -> None:
    """A room without a thermostat still gets the Climate page from the option."""
    no_heating = tuple(e for e in sample_house.AREA_ENTITIES if e.domain != "climate")
    data = sample(
        overrides={"climate_entities": (LIVING_CLIMATE.entity_id,)},
        area_entities=no_heating,
        climates=(LIVING_CLIMATE,),
    )
    assert "climate" not in views(
        replace(data, display=replace(data.display, overrides=Overrides()))
    )
    climate = cards_of(views(data)["climate"])
    assert climate[0]["entity"] == LIVING_CLIMATE.entity_id


def test_chosen_climates_skip_hidden_and_unknown() -> None:
    """Hidden, unknown and non-climate ids are skipped; the room's thermostat is not used."""
    data = sample(
        overrides={
            "climate_entities": ("climate.gone", LIVING_CLIMATE.entity_id, AREA_TEMP.entity_id),
            "hidden": (LIVING_CLIMATE.entity_id,),
        },
        climates=(sample_house.HEATING, LIVING_CLIMATE),
        area_entities=(*sample_house.AREA_ENTITIES, AREA_TEMP),
    )
    pages = views(data)
    assert "climate" not in pages
    assert sample_house.HEATING.entity_id in tile_entities(pages["home"])


# --- Home tile limit -----------------------------------------------------------


@pytest.mark.parametrize("profile", [SQUARE, LANDSCAPE])
def test_max_home_tiles(profile: Any) -> None:
    """At most that many slots on Home, the last one "+N more"; 0 keeps the automatic fit."""
    busy = sample(profile, area_entities=sample_house.AREA_ENTITIES + sample_house.BUSY_LAMPS)
    auto = cards_of(views(busy)["home"])
    limited_data = replace(
        busy, display=replace(busy.display, overrides=Overrides(max_home_tiles=4))
    )
    limited = views(limited_data)
    slots = [c for c in cards_of(limited["home"]) if c["type"] in ("tile", "shortcut")]
    weather = [c for c in slots if c.get("entity") == sample_house.WEATHER]
    entity_slots = [c for c in slots if c not in weather]
    assert len(entity_slots) == 4
    assert entity_slots[-1]["tap_action"]["navigation_path"] == "more"
    assert "more" in limited
    assert len(auto) != len(cards_of(limited["home"]))


def test_max_home_tiles_above_the_fit() -> None:
    """A limit above what fits changes nothing; the screen still decides."""
    busy = sample(area_entities=sample_house.AREA_ENTITIES + sample_house.BUSY_LAMPS)
    raised = replace(busy, display=replace(busy.display, overrides=Overrides(max_home_tiles=24)))
    assert build_dashboard(raised) == build_dashboard(
        replace(busy, display=replace(busy.display, overrides=Overrides()))
    )


# --- The display device's own entities -------------------------------------------


def test_display_entities_left_out() -> None:
    """Screen light and relay are no tiles and no room controls, unless included or pinned."""
    entities = (*sample_house.AREA_ENTITIES, SCREEN, RELAY)
    data = sample(LANDSCAPE, area_entities=entities)
    home = views(data)["home"]
    assert not {SCREEN.entity_id, RELAY.entity_id} & set(tile_entities(home))
    card = room_card(data)
    assert card["exclude_entities"] == [SCREEN.entity_id, RELAY.entity_id]

    pinned = sample(
        LANDSCAPE,
        overrides={"pinned": (RELAY.entity_id,)},
        area_entities=entities,
    )
    assert tile_entities(views(pinned)["home"])[0] == RELAY.entity_id
    assert room_card(pinned)["exclude_entities"] == [SCREEN.entity_id]

    included = sample(
        LANDSCAPE,
        overrides={"include_display_entities": True},
        area_entities=entities,
    )
    assert {SCREEN.entity_id, RELAY.entity_id} <= set(tile_entities(views(included)["home"]))
    assert "exclude_entities" not in room_card(included)


def test_display_entities_stay_without_display_device() -> None:
    """Without a display device nothing is left out."""
    data = sample(area_entities=(*sample_house.AREA_ENTITIES, RELAY))
    data = replace(data, display=replace(data.display, display_device_id=None))
    assert RELAY.entity_id in tile_entities(views(data)["home"])


def test_display_media_player_not_on_media_page() -> None:
    """Pages use the same rule: a display's own media player isn't on the Media page."""
    own_player = EntityInfo(
        "media_player.display", "Display", KITCHEN, "speaker", 1, device_id=DISPLAY_DEVICE
    )
    data = sample(
        area_entities=(*sample_house.AREA_ENTITIES, own_player),
        media_players=(*sample_house.MEDIA_PLAYERS, own_player),
    )
    assert own_player.entity_id not in str(views(data)["media"])
