"""Tests for the Wall Display Dashboards config flow."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.walldisplay_dashboards.const import (
    CONF_AREA_ID,
    CONF_DISPLAY_DEVICE_ID,
    CONF_DISPLAY_HOST,
    CONF_HEIGHT,
    CONF_HIDDEN,
    CONF_IDLE_SECONDS,
    CONF_KIOSK,
    CONF_NAME,
    CONF_PAGES,
    CONF_PINNED,
    CONF_PROFILE,
    CONF_ROLE,
    CONF_SCENE_BUTTONS,
    CONF_SHOW_IN_SIDEBAR,
    CONF_URL_PATH,
    CONF_WEATHER_ENTITY,
    CONF_WIDTH,
    DEFAULT_PAGES,
    DOMAIN,
    ROLES,
)
from custom_components.walldisplay_dashboards.profiles import PROFILES

PACKAGE = "custom_components.walldisplay_dashboards"
COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN


@pytest.fixture(autouse=True)
async def mock_setup_entry(hass: HomeAssistant) -> AsyncGenerator[None]:
    """Keep the backend out of config flow tests.

    The frontend package is not installed in the test environment, so the
    manifest dependency is marked as loaded instead of being set up.

    Reconfigure and options flows schedule a reload in the background. Wait
    for it before the patches go away; otherwise a reload still in flight
    runs the real setup during teardown (flaky InvalidStateError).
    """
    hass.config.components.add("frontend")
    with (
        patch(f"{PACKAGE}.async_setup", return_value=True, create=True),
        patch(f"{PACKAGE}.async_setup_entry", return_value=True),
        patch(f"{PACKAGE}.async_unload_entry", return_value=True, create=True),
    ):
        yield
        await hass.async_block_till_done()


@pytest.fixture
def area_id(hass: HomeAssistant) -> str:
    """Create an area."""
    return ar.async_get(hass).async_create("Kitchen").id


def _entry(area_id: str, **data_overrides) -> MockConfigEntry:
    data = {
        CONF_NAME: "Kitchen",
        CONF_URL_PATH: "wall-kitchen",
        CONF_AREA_ID: area_id,
        CONF_PROFILE: "shelly_wall_display",
        CONF_DISPLAY_DEVICE_ID: "device123",
        CONF_WEATHER_ENTITY: "weather.home",
        **data_overrides,
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen",
        unique_id=data[CONF_URL_PATH],
        data=data,
        options={
            CONF_PAGES: list(DEFAULT_PAGES),
            CONF_IDLE_SECONDS: 60,
            CONF_KIOSK: "builtin",
            CONF_PINNED: [],
            CONF_HIDDEN: [],
            CONF_SCENE_BUTTONS: [],
            CONF_SHOW_IN_SIDEBAR: True,
        },
    )


def _suggested(result, key: str):
    for marker in result["data_schema"].schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise KeyError(key)


async def test_user_flow(hass: HomeAssistant, area_id: str) -> None:
    """A known model creates the entry straight away."""
    hass.states.async_set("weather.home", "sunny")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert _suggested(result, CONF_WEATHER_ENTITY) == "weather.home"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kitchen Display",
            CONF_AREA_ID: area_id,
            CONF_PROFILE: "shelly_wall_display",
            CONF_DISPLAY_HOST: " 192.168.1.50 ",
            CONF_WEATHER_ENTITY: "weather.home",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen Display"
    assert result["data"] == {
        CONF_NAME: "Kitchen Display",
        CONF_URL_PATH: "wall-kitchen-display",
        CONF_AREA_ID: area_id,
        CONF_PROFILE: "shelly_wall_display",
        CONF_DISPLAY_HOST: "192.168.1.50",
        CONF_WEATHER_ENTITY: "weather.home",
    }
    assert result["options"] == {
        CONF_ROLE: "room",
        CONF_PAGES: ["climate", "media", "scenes"],
        CONF_IDLE_SECONDS: 60,
        CONF_KIOSK: "builtin",
        CONF_PINNED: [],
        CONF_HIDDEN: [],
        CONF_SCENE_BUTTONS: [],
        CONF_SHOW_IN_SIDEBAR: True,
    }
    assert result["result"].unique_id == "wall-kitchen-display"


def _display_device(hass: HomeAssistant, area_id: str | None) -> str:
    """Create a display device, optionally in an area."""
    shelly = MockConfigEntry(domain="shelly")
    shelly.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=shelly.entry_id, identifiers={("shelly", "wall1")}, name="Wall Display"
    )
    if area_id:
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    return device.id


async def test_user_flow_area_from_device(hass: HomeAssistant, area_id: str) -> None:
    """P1-9: an empty area is taken from the display device; role is stored in options."""
    device_id = _display_device(hass, area_id)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    keys = [str(k) for k in result["data_schema"].schema]
    assert keys.index(CONF_DISPLAY_DEVICE_ID) < keys.index(CONF_AREA_ID)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Hall",
            CONF_DISPLAY_DEVICE_ID: device_id,
            CONF_PROFILE: "shelly_x2_portrait",
            CONF_ROLE: "entrance",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AREA_ID] == area_id
    assert result["data"][CONF_DISPLAY_DEVICE_ID] == device_id
    assert result["options"][CONF_ROLE] == "entrance"


async def test_user_flow_area_required(hass: HomeAssistant, area_id: str) -> None:
    """No area and a device without one is an error on the area field."""
    device_id = _display_device(hass, None)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    user_input = {
        CONF_NAME: "Hall",
        CONF_DISPLAY_DEVICE_ID: device_id,
        CONF_PROFILE: "shelly_wall_display",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_AREA_ID: "area_required"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**user_input, CONF_AREA_ID: area_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AREA_ID] == area_id


async def test_user_flow_custom_size(hass: HomeAssistant, area_id: str) -> None:
    """The custom model asks for a size."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert _suggested(result, CONF_WEATHER_ENTITY) is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Hall Tablet", CONF_AREA_ID: area_id, CONF_PROFILE: "custom"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_size"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WIDTH: 600.0, CONF_HEIGHT: 1024.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_NAME: "Hall Tablet",
        CONF_URL_PATH: "wall-hall-tablet",
        CONF_AREA_ID: area_id,
        CONF_PROFILE: "custom",
        CONF_WIDTH: 600,
        CONF_HEIGHT: 1024,
    }


async def test_user_flow_duplicate(hass: HomeAssistant, area_id: str) -> None:
    """A second display with the same url_path aborts."""
    _entry(area_id).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "kitchen", CONF_AREA_ID: area_id, CONF_PROFILE: "nspanel_pro"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_panel_collision(hass: HomeAssistant, area_id: str) -> None:
    """An existing panel at the same url_path is an error, not an abort."""
    hass.data["frontend_panels"] = {"wall-kitchen": object()}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    user_input = {CONF_NAME: "Kitchen", CONF_AREA_ID: area_id, CONF_PROFILE: "shelly_xl"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "url_path_taken"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**user_input, CONF_NAME: "Kitchen 2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL_PATH] == "wall-kitchen-2"


async def test_reconfigure(hass: HomeAssistant, area_id: str) -> None:
    """Reconfigure changes the display but keeps name and url_path."""
    entry = _entry(area_id)
    entry.add_to_hass(hass)
    other_area = ar.async_get(hass).async_create("Hall").id

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert CONF_NAME not in result["data_schema"].schema
    assert _suggested(result, CONF_PROFILE) == "shelly_wall_display"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_AREA_ID: other_area, CONF_PROFILE: "tablet_landscape", CONF_DISPLAY_HOST: "10.0.0.9"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Kitchen"
    assert entry.unique_id == "wall-kitchen"
    assert dict(entry.data) == {
        CONF_NAME: "Kitchen",
        CONF_URL_PATH: "wall-kitchen",
        CONF_AREA_ID: other_area,
        CONF_PROFILE: "tablet_landscape",
        CONF_DISPLAY_HOST: "10.0.0.9",
    }


async def test_reconfigure_area_from_device(hass: HomeAssistant, area_id: str) -> None:
    """Reconfigure also falls back to the display device's area."""
    hall = ar.async_get(hass).async_create("Hall").id
    device_id = _display_device(hass, hall)
    entry = _entry(area_id)
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DISPLAY_DEVICE_ID: device_id, CONF_PROFILE: "shelly_wall_display"},
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_AREA_ID] == hall
    assert entry.data[CONF_DISPLAY_DEVICE_ID] == device_id


async def test_reconfigure_custom_size(hass: HomeAssistant, area_id: str) -> None:
    """Switching to custom asks for the size, prefilled from the entry."""
    entry = _entry(area_id, **{CONF_PROFILE: "custom", CONF_WIDTH: 500, CONF_HEIGHT: 700})
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA_ID: area_id, CONF_PROFILE: "custom"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_size"
    assert _suggested(result, CONF_WIDTH) == 500

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WIDTH: 800, CONF_HEIGHT: 600}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_WIDTH] == 800
    assert entry.data[CONF_HEIGHT] == 600
    assert entry.data[CONF_URL_PATH] == "wall-kitchen"


async def test_reconfigure_keeps_adopted_size(hass: HomeAssistant, area_id: str) -> None:
    """A measured size adopted for a known model survives if the model is unchanged."""
    entry = _entry(area_id, **{CONF_WIDTH: 482, CONF_HEIGHT: 478})
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA_ID: area_id, CONF_PROFILE: "shelly_wall_display"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert (entry.data[CONF_WIDTH], entry.data[CONF_HEIGHT]) == (482, 478)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA_ID: area_id, CONF_PROFILE: "nspanel_pro"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert CONF_WIDTH not in entry.data
    assert CONF_HEIGHT not in entry.data


async def test_options_flow(hass: HomeAssistant, area_id: str) -> None:
    """Options: scene button limit, page order, defaults for cleared lists."""
    entry = _entry(area_id)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _suggested(result, CONF_IDLE_SECONDS) == 60
    assert _suggested(result, CONF_KIOSK) == "builtin"
    assert _suggested(result, CONF_ROLE) == "room"
    keys = [str(k) for k in result["data_schema"].schema]
    assert keys[:2] == [CONF_SCENE_BUTTONS, CONF_ROLE]

    user_input = {
        CONF_ROLE: "entrance",
        CONF_PAGES: ["scenes", "climate"],
        CONF_IDLE_SECONDS: 120.0,
        CONF_KIOSK: "kiosk_mode",
        CONF_PINNED: ["light.ceiling"],
        CONF_SCENE_BUTTONS: ["scene.a", "scene.b", "script.c"],
        CONF_SHOW_IN_SIDEBAR: False,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SCENE_BUTTONS: "too_many_scene_buttons"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user_input, CONF_SCENE_BUTTONS: ["scene.a", "script.c"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        CONF_ROLE: "entrance",
        CONF_PAGES: ["climate", "scenes"],
        CONF_IDLE_SECONDS: 120,
        CONF_KIOSK: "kiosk_mode",
        CONF_PINNED: ["light.ceiling"],
        CONF_HIDDEN: [],
        CONF_SCENE_BUTTONS: ["scene.a", "script.c"],
        CONF_SHOW_IN_SIDEBAR: False,
    }


async def test_options_pinned_limited_to_area(hass: HomeAssistant, area_id: str) -> None:
    """Pinned offers the area's tile entities when the area has any."""
    ent_reg = er.async_get(hass)
    light = ent_reg.async_get_or_create("light", "test", "l1", suggested_object_id="ceiling")
    ent_reg.async_update_entity(light.entity_id, area_id=area_id)
    sensor = ent_reg.async_get_or_create("sensor", "test", "s1", suggested_object_id="temp")
    ent_reg.async_update_entity(sensor.entity_id, area_id=area_id)
    entry = _entry(area_id)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    pinned = next(v for k, v in result["data_schema"].schema.items() if k == CONF_PINNED)
    assert pinned.config["include_entities"] == ["light.ceiling"]


def _keys(tree, prefix: str = "") -> set[str]:
    if not isinstance(tree, dict):
        return {prefix}
    return set().union(*(_keys(v, f"{prefix}.{k}") for k, v in tree.items()))


def test_translations_match() -> None:
    """strings.json and en.json are identical; de.json has the same keys."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((COMPONENT_DIR / "translations" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((COMPONENT_DIR / "translations" / "de.json").read_text(encoding="utf-8"))
    assert strings == en
    assert _keys(de) == _keys(en)
    assert set(en["selector"]["profile"]["options"]) == set(PROFILES)
    assert set(en["selector"]["role"]["options"]) == set(ROLES)
    assert en["selector"]["pages"]["options"]["climate"] == "Climate"
    assert de["selector"]["pages"]["options"]["climate"] == "Klima"
