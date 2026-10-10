"""Tests for the service device, the sensor icon and the stale device cleanup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.const import ATTR_ICON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.walldisplay_dashboards import sensor
from custom_components.walldisplay_dashboards.const import DOMAIN, VERSION

from .helpers_backend import (  # noqa: F401
    entry_data,
    make_entry,
    mock_frontend,
    mock_push,
)

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN
SENSOR = "sensor.kitchen_measured_viewport"

pytestmark = pytest.mark.usefixtures("mock_frontend", "mock_push")


def _device(hass: HomeAssistant, entry) -> dr.DeviceEntry | None:
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )


async def _setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_device(hass: HomeAssistant) -> None:
    """Each entry gets one service device that the viewport sensor belongs to."""
    entry = make_entry(hass)
    await _setup(hass, entry)

    device = _device(hass, entry)
    assert device is not None
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.name == "Kitchen"
    assert device.manufacturer == "Wall Display Dashboards"
    assert device.model == 'Shelly Wall Display (4")'
    assert device.model_id == "shelly_wall_display"
    assert device.sw_version == VERSION
    assert device.configuration_url == "homeassistant://wall-kitchen"
    assert device.config_entry_id == entry.entry_id

    reg = er.async_get(hass).async_get(SENSOR)
    assert reg is not None
    assert reg.device_id == device.id


async def test_device_follows_profile(hass: HomeAssistant) -> None:
    """A custom size shows up as the device model; a reload updates the same device."""
    entry = make_entry(
        hass,
        entry_data(name="Hall", url_path="wall-hall", profile="custom", width=600, height=1024),
    )
    await _setup(hass, entry)
    device = _device(hass, entry)
    assert device is not None
    assert (device.model, device.model_id) == ("Custom size", "custom")

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "profile": "shelly_xl", "width": None, "height": None}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    updated = _device(hass, entry)
    assert updated is not None
    assert updated.id == device.id
    assert updated.model == "Shelly Wall Display XL / XLi"


async def test_stale_device_is_detached(hass: HomeAssistant) -> None:
    """A device linked to the entry under another identifier is removed on setup."""
    entry = make_entry(hass)
    registry = dr.async_get(hass)
    stale = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "old-identifier")}
    )
    await _setup(hass, entry)

    assert registry.async_get(stale.id) is None
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    assert [d.identifiers for d in devices] == [{(DOMAIN, entry.entry_id)}]


async def test_device_removed_with_entry(hass: HomeAssistant) -> None:
    """Deleting the entry removes its device."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _device(hass, entry) is None


async def test_icon_comes_from_icons_json(hass: HomeAssistant) -> None:
    """The sensor sets no icon in code; icons.json has one for its translation key."""
    icons = json.loads((COMPONENT_DIR / "icons.json").read_text(encoding="utf-8"))
    assert icons["entity"]["sensor"]["viewport"]["default"] == "mdi:monitor-screenshot"
    assert "_attr_icon" not in vars(sensor.ViewportSensor)

    entry = make_entry(hass)
    await _setup(hass, entry)
    state = hass.states.get(SENSOR)
    assert state is not None
    assert ATTR_ICON not in state.attributes
    reg = er.async_get(hass).async_get(SENSOR)
    assert reg is not None
    assert reg.translation_key == "viewport"
    assert reg.original_icon is None
