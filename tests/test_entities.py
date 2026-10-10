"""Tests for reading entries and registries into GeneratorInput."""

from __future__ import annotations

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    floor_registry as fr,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.walldisplay_dashboards.const import DOMAIN
from custom_components.walldisplay_dashboards.entities import (
    collect_input,
    display_config_from_entry,
)


def _device(hass: HomeAssistant, owner: MockConfigEntry, key: str, area_id: str | None) -> str:
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("test", key)}, name=key
    )
    if area_id:
        registry.async_update_device(device.id, area_id=area_id)
    return device.id


def _entity(
    hass: HomeAssistant,
    domain: str,
    key: str,
    state: str,
    *,
    name: str | None = None,
    friendly_name: str | None = None,
    area_id: str | None = None,
    device_id: str | None = None,
    attributes: dict | None = None,
    **registry_kwargs,
) -> str:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain, "test", key, device_id=device_id, original_name=name, **registry_kwargs
    )
    if area_id:
        registry.async_update_entity(entry.entity_id, area_id=area_id)
    attrs = dict(attributes or {})
    attrs["friendly_name"] = friendly_name or name or key
    hass.states.async_set(entry.entity_id, state, attrs)
    return entry.entity_id


async def _house(hass: HomeAssistant) -> dict[str, str]:
    """Kitchen display plus a few rooms. Returns entity ids by short key."""
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen").id
    living = areas.async_create("Living Room").id
    owner = MockConfigEntry(domain="test")
    owner.add_to_hass(hass)
    kitchen_device = _device(hass, owner, "kitchen_lights", kitchen)
    living_device = _device(hass, owner, "living_tv", living)
    display_device = _device(hass, owner, "display", kitchen)

    ids = {
        "ceiling": _entity(
            hass,
            "light",
            "ceiling",
            "on",
            name="Kitchen Ceiling",
            area_id=kitchen,
            attributes={"supported_color_modes": ["brightness"]},
        ),
        # Area comes from the device.
        "counter": _entity(
            hass, "light", "counter", "off", name="Kitchen Counter", device_id=kitchen_device
        ),
        # Own area overrides the device area.
        "moved": _entity(
            hass, "light", "moved", "off", name="Reading", device_id=kitchen_device, area_id=living
        ),
        "config": _entity(
            hass,
            "switch",
            "child_lock",
            "off",
            name="Child lock",
            device_id=kitchen_device,
            entity_category=EntityCategory.CONFIG,
        ),
        "diag": _entity(
            hass,
            "switch",
            "diag",
            "off",
            name="Diag",
            area_id=kitchen,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        "hidden": _entity(
            hass,
            "switch",
            "hidden",
            "off",
            name="Hidden",
            area_id=kitchen,
            hidden_by=er.RegistryEntryHider.USER,
        ),
        "coffee": _entity(hass, "switch", "coffee", "off", name="Kitchen Coffee", area_id=kitchen),
        "blinds": _entity(hass, "cover", "blinds", "open", name="Blinds", area_id=kitchen),
        "heating": _entity(
            hass,
            "climate",
            "kitchen_heat",
            "heat",
            name="Kitchen Heating",
            area_id=kitchen,
            attributes={
                "current_temperature": 20.5,
                "supported_features": 385,
                "hvac_modes": ["off", "heat"],
                "preset_modes": ["eco", "comfort"],
            },
        ),
        "living_climate": _entity(
            hass, "climate", "living_heat", "heat", name="Thermostat", area_id=living
        ),
        "tv": _entity(hass, "media_player", "tv", "off", name="TV", device_id=living_device),
        "cooking": _entity(
            hass, "scene", "cooking", "scening", name="Kitchen Cooking", area_id=kitchen
        ),
        "movie": _entity(hass, "scene", "movie", "scening", name="Movie night", area_id=living),
        "all_off": _entity(hass, "script", "all_off", "off", name="All off"),
        "away": _entity(hass, "scene", "away", "scening", name="Away"),
        "back_door": _entity(
            hass, "lock", "back_door", "locked", name="Back door", area_id=kitchen
        ),
        "alarm": _entity(hass, "alarm_control_panel", "alarm", "armed_home", name="Alarm"),
        "window": _entity(
            hass,
            "binary_sensor",
            "living_window",
            "on",
            name="Living Room Window",
            area_id=living,
            original_device_class="window",
        ),
        "sensor": _entity(hass, "sensor", "kitchen_power", "12", name="Power", area_id=kitchen),
        "temp": _entity(
            hass,
            "sensor",
            "display_temp",
            "21.3",
            name="Display Temperature",
            device_id=display_device,
            original_device_class="temperature",
            attributes={"device_class": "temperature", "unit_of_measurement": "°C"},
        ),
        "hum": _entity(
            hass,
            "sensor",
            "display_hum",
            "47",
            name="Display Humidity",
            device_id=display_device,
            attributes={"device_class": "humidity", "unit_of_measurement": "%"},
        ),
    }
    hass.states.async_set("weather.home", "sunny", {"temperature": 14})
    hass.states.async_set("person.anna", "home", {"friendly_name": "Anna"})
    ids["kitchen"] = kitchen
    ids["living"] = living
    ids["display_device"] = display_device
    return ids


def _display_entry(hass: HomeAssistant, ids: dict[str, str], **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen",
        unique_id="wall-kitchen",
        data={
            "name": "Kitchen",
            "url_path": "wall-kitchen",
            "area_id": ids["kitchen"],
            "profile": "shelly_wall_display",
            "display_device_id": ids["display_device"],
        },
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


async def test_display_config(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(
        hass,
        ids,
        pages=["scenes", "bogus", "climate"],
        pinned=[ids["coffee"]],
        hidden=[ids["blinds"]],
        scene_buttons=[ids["movie"], ids["cooking"], ids["all_off"]],
        idle_seconds=30,
        kiosk="off",
    )
    display = display_config_from_entry(hass, entry)
    assert display.entry_id == entry.entry_id
    assert display.name == "Kitchen"
    assert display.url_path == "wall-kitchen"
    assert display.profile.id == "shelly_wall_display"
    assert (display.profile.width, display.profile.height) == (480, 480)
    assert display.pages == ("scenes", "climate")
    assert display.weather_entity == "weather.home"
    assert display.indoor_temperature == ids["temp"]
    assert display.indoor_humidity == ids["hum"]
    assert display.idle_seconds == 30
    assert display.kiosk == "off"
    assert display.overrides.pinned == (ids["coffee"],)
    assert display.overrides.hidden == (ids["blinds"],)
    assert display.overrides.scene_buttons == (ids["movie"], ids["cooking"])


async def test_display_config_defaults(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(hass, ids)
    display = display_config_from_entry(hass, entry)
    assert display.pages == ("climate", "media", "scenes")
    assert display.idle_seconds == 60
    assert display.kiosk == "builtin"


async def test_custom_profile_size(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(hass, ids)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "profile": "custom", "width": 800, "height": 480}
    )
    profile = display_config_from_entry(hass, entry).profile
    assert (profile.id, profile.width, profile.height) == ("custom", 800, 480)


async def test_collect_input(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(hass, ids)
    data = collect_input(hass, display_config_from_entry(hass, entry))

    area = {e.entity_id: e for e in data.area_entities}
    assert data.area_name == "Kitchen"
    assert ids["ceiling"] in area and ids["counter"] in area
    assert ids["moved"] not in area
    for skipped in ("config", "diag", "hidden", "sensor"):
        assert ids[skipped] not in area
    assert area[ids["ceiling"]].name == "Ceiling"
    assert area[ids["counter"]].name == "Counter"
    assert area[ids["counter"]].area_id == ids["kitchen"]
    assert area[ids["heating"]].supported_features == 385

    # Ranked: lights, cover, climate, switch, scene; secure domains last.
    domains = [e.domain for e in data.area_entities]
    assert domains == ["light", "light", "cover", "climate", "switch", "scene", "lock"]
    assert area[ids["ceiling"]].dimmable is True
    assert area[ids["counter"]].dimmable is False
    assert data.language == "en"
    assert data.role == "room"
    assert [e.entity_id for e in data.house_scenes] == [ids["away"]]
    assert data.persons == () and data.house_lights == () and data.leave_home == ()

    # Pages are room-scoped: only the Kitchen's climates, players and scenes.
    assert [e.entity_id for e in data.climates] == [ids["heating"]]
    assert data.climates[0].hvac_modes == ("off", "heat")
    assert data.climates[0].preset_modes == ("eco", "comfort")
    assert data.media_players == ()
    assert [e.entity_id for e in data.scenes] == [ids["cooking"]]
    assert {e.entity_id for e in data.area_sensors} == {ids["temp"], ids["hum"]}
    assert data.area_names[ids["living"]] == "Living Room"


async def test_collect_input_overrides(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(
        hass, ids, pinned=[ids["coffee"], ids["tv"]], hidden=[ids["ceiling"], ids["heating"]]
    )
    data = collect_input(hass, display_config_from_entry(hass, entry))
    order = [e.entity_id for e in data.area_entities]
    assert order[:2] == [ids["coffee"], ids["tv"]]
    assert ids["ceiling"] not in order
    assert data.climates == ()
    assert ids["cooking"] in {e.entity_id for e in data.scenes}


async def test_generator_runs_on_collected_input(hass: HomeAssistant) -> None:
    from custom_components.walldisplay_dashboards.generator import build_dashboard

    ids = await _house(hass)
    entry = _display_entry(hass, ids)
    dashboard = build_dashboard(collect_input(hass, display_config_from_entry(hass, entry)))
    # No media player in the Kitchen and only 2 scenes (Cooking, Away): Home and Climate.
    assert [v["path"] for v in dashboard["views"]] == ["home", "climate"]


async def test_collect_input_entrance(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    entry = _display_entry(hass, ids, role="entrance")
    data = collect_input(hass, display_config_from_entry(hass, entry))
    assert data.role == "entrance"
    assert [e.entity_id for e in data.persons] == ["person.anna"]
    assert set(data.house_lights) == {ids["ceiling"], ids["counter"], ids["moved"]}
    assert data.openings == (ids["window"],)
    assert {e.entity_id for e in data.house_secure} == {ids["back_door"], ids["alarm"]}
    assert [e.entity_id for e in data.leave_home] == [ids["all_off"]]


async def test_language_and_area_defaults(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    await hass.config.async_update(language="de")
    entry = _display_entry(hass, ids)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "area_id": None})
    display = display_config_from_entry(hass, entry)
    assert display.area_id == ids["kitchen"]  # from the display device
    data = collect_input(hass, display)
    assert data.language == "de"


async def test_area_designated_sensors(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    ar.async_get(hass).async_update(
        ids["kitchen"], temperature_entity_id=ids["temp"], humidity_entity_id=ids["hum"]
    )
    entry = _display_entry(hass, ids)
    data = collect_input(hass, display_config_from_entry(hass, entry))
    assert (data.area_temperature, data.area_humidity) == (ids["temp"], ids["hum"])


async def test_icons_and_weather_features(hass: HomeAssistant) -> None:
    ids = await _house(hass)
    hass.states.async_set("weather.home", "sunny", {"temperature": 14, "supported_features": 3})
    er.async_get(hass).async_update_entity(ids["cooking"], icon="mdi:pot-steam")
    entry = _display_entry(hass, ids)
    data = collect_input(hass, display_config_from_entry(hass, entry))
    assert data.weather_features == 3
    scenes = {e.entity_id: e for e in data.scenes}
    assert scenes[ids["cooking"]].icon == "mdi:pot-steam"
    house = {e.entity_id: e for e in data.house_scenes}
    assert house[ids["away"]].icon is None


async def test_display_config_room_options(hass: HomeAssistant) -> None:
    """The room sensor, thermostat, tile limit and display entity options are read."""
    ids = await _house(hass)
    entry = _display_entry(
        hass,
        ids,
        climate_entities=[ids["living_climate"], ids["heating"]],
        temperature_entity=ids["temp"],
        humidity_entity="",
        max_home_tiles=6.0,
        include_display_entities=True,
    )
    display = display_config_from_entry(hass, entry)
    overrides = display.overrides
    assert overrides.climate_entities == (ids["living_climate"], ids["heating"])
    assert overrides.temperature_entity == ids["temp"]
    assert overrides.humidity_entity is None  # cleared
    assert overrides.max_home_tiles == 6
    assert overrides.include_display_entities is True
    assert display.display_device_id == ids["display_device"]


@pytest.mark.parametrize(("value", "limit"), [(None, 0), (30, 24), (-3, 0), ("6", 0), (True, 0)])
async def test_max_home_tiles_bounds(hass: HomeAssistant, value: object, limit: int) -> None:
    """Out-of-range or malformed tile limits fall back into 0-24 (0 = automatic)."""
    ids = await _house(hass)
    entry = _display_entry(hass, ids, max_home_tiles=value)
    assert display_config_from_entry(hass, entry).overrides.max_home_tiles == limit


async def test_single_entity_options(hass: HomeAssistant) -> None:
    """A single id where a list is stored still counts; an unknown device has no area."""
    ids = await _house(hass)
    entry = _display_entry(hass, ids, pinned=ids["coffee"])
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "area_id": None, "display_device_id": "gone"}
    )
    display = display_config_from_entry(hass, entry)
    assert display.overrides.pinned == (ids["coffee"],)
    assert display.area_id is None
    data = collect_input(hass, display)
    # No area: only the pinned entity, and no room pages.
    assert [e.entity_id for e in data.area_entities] == [ids["coffee"]]
    assert data.climates == () and data.scenes == ()


async def test_pinned_without_state_is_skipped(hass: HomeAssistant) -> None:
    """A pinned entity that has no state (removed integration) is left out."""
    ids = await _house(hass)
    entry = _display_entry(hass, ids, pinned=["light.removed", ids["tv"]])
    data = collect_input(hass, display_config_from_entry(hass, entry))
    order = [e.entity_id for e in data.area_entities]
    assert "light.removed" not in order
    assert order[0] == ids["tv"]  # from the Living Room


async def test_climate_entities_from_any_room(hass: HomeAssistant) -> None:
    """Chosen thermostats join the input and drive the Climate page, the first as main."""
    from custom_components.walldisplay_dashboards.generator import build_dashboard

    ids = await _house(hass)
    entry = _display_entry(hass, ids, climate_entities=[ids["living_climate"], "sensor.no"])
    data = collect_input(hass, display_config_from_entry(hass, entry))
    assert {e.entity_id for e in data.climates} == {ids["heating"], ids["living_climate"]}

    views = {v["path"]: v for v in build_dashboard(data)["views"]}
    (thermostat,) = views["climate"]["sections"][0]["cards"][:1]
    assert thermostat["type"] == "thermostat"
    assert thermostat["entity"] == ids["living_climate"]
    assert thermostat["name"] == "Thermostat"  # its own name, not the Kitchen's
    # The Kitchen's own thermostat is not on the Climate page, so it stays on Home.
    home = views["home"]["sections"][0]["cards"]
    assert ids["heating"] in {card.get("entity") for card in home}


async def test_names_lose_room_and_floor(hass: HomeAssistant) -> None:
    """Area and floor names go from tile names, anywhere in the name (Ben on the OG)."""
    floor = fr.async_get(hass).async_create("OG")
    ben = ar.async_get(hass).async_create("Ben", floor_id=floor.floor_id).id
    names = {
        "licht": "Licht Ben OG",
        "eingang": "Licht Eingang Ben OG",
        "nord": "Raffstore OG Ben Nord",
        "west": "Raffstore OG Ben West",
        "bett": "Ben Bett Licht",
    }
    for key, name in names.items():
        domain = "cover" if "Raffstore" in name else "light"
        _entity(hass, domain, key, "off", friendly_name=name, area_id=ben)
    # A name the user gave the entity in Home Assistant is used, and cleaned the same way.
    renamed = _entity(hass, "light", "desk", "off", name="Desk lamp", area_id=ben)
    er.async_get(hass).async_update_entity(renamed, name="Schreibtisch Ben")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ben",
        data={
            "name": "Ben",
            "url_path": "wall-ben",
            "area_id": ben,
            "profile": "shelly_wall_display",
        },
    )
    entry.add_to_hass(hass)
    data = collect_input(hass, display_config_from_entry(hass, entry))
    assert sorted(e.name for e in data.area_entities) == [
        "Bett Licht",
        "Licht",
        "Licht Eingang",
        "Raffstore Nord",
        "Raffstore West",
        "Schreibtisch",
    ]


async def test_display_entities_are_not_tiles(hass: HomeAssistant) -> None:
    """The display's screen light, relay and switches aren't tiles; pinning brings one back."""
    from custom_components.walldisplay_dashboards.generator import build_dashboard

    ids = await _house(hass)
    device = ids["display_device"]
    own = {
        key: _entity(hass, domain, key, "off", name=name, device_id=device)
        for key, domain, name in (
            ("screen", "light", "Bildschirm"),
            ("mute", "switch", "Mikrofon stummschalten"),
            ("night", "switch", "Nachtmodus"),
            ("relay", "switch", "Relais"),
        )
    }

    def home_entities(**options) -> set[str]:
        entry = _display_entry(hass, ids, **options)
        data = collect_input(hass, display_config_from_entry(hass, entry))
        assert {own["screen"], own["relay"]} <= {e.entity_id for e in data.area_entities}
        home = build_dashboard(data)["views"][0]
        return {
            card.get("entity")
            for card in home["sections"][0]["cards"]
            if card.get("type") in ("tile", "shortcut")
        }

    assert not home_entities() & set(own.values())
    assert home_entities(pinned=[own["relay"]]) & set(own.values()) == {own["relay"]}
    assert home_entities(include_display_entities=True, max_home_tiles=24) >= {
        own["screen"],
        own["relay"],
    }


async def test_room_sensor_precedence_feeds_the_indoor_tile(hass: HomeAssistant) -> None:
    """Home's Indoor tile shows the room temperature: option > area registry > display > area."""
    from custom_components.walldisplay_dashboards.generator import build_dashboard

    ids = await _house(hass)
    climate = {"device_class": "temperature", "unit_of_measurement": "°C"}
    area_temp = _entity(
        hass,
        "sensor",
        "kitchen_temp",
        "20.1",
        name="Kitchen Temperature",
        area_id=ids["kitchen"],
        attributes=climate,
    )
    designated = _entity(
        hass,
        "sensor",
        "kitchen_wall",
        "20.4",
        name="Wall",
        area_id=ids["kitchen"],
        attributes=climate,
    )
    chosen = _entity(
        hass,
        "sensor",
        "living_temp",
        "19.0",
        name="Living Temperature",
        area_id=ids["living"],
        attributes=climate,
    )
    entry = _display_entry(hass, ids)

    def indoor_tile() -> list[str]:
        dashboard = build_dashboard(collect_input(hass, display_config_from_entry(hass, entry)))
        cards = dashboard["views"][0]["sections"][0]["cards"]
        (tile,) = [card for card in cards if card.get("name") == "Indoor"]
        return [tile["entity"]]

    # The display device's sensors win over the area's other sensors.
    assert indoor_tile() == [ids["temp"]]
    ar.async_get(hass).async_update(ids["kitchen"], temperature_entity_id=designated)
    assert indoor_tile() == [designated]
    hass.config_entries.async_update_entry(entry, options={"temperature_entity": chosen})
    assert indoor_tile() == [chosen]
    # Without the display device, the first visible area sensor of the class (by name).
    ar.async_get(hass).async_update(ids["kitchen"], temperature_entity_id=None)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "display_device_id": None}, options={"hidden": [ids["temp"]]}
    )
    assert indoor_tile() == [area_temp]
