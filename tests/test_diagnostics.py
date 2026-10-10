"""Tests for the config entry diagnostics."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.walldisplay_dashboards.diagnostics import async_get_config_entry_diagnostics

from .helpers_backend import (  # noqa: F401
    PACKAGE,
    entry_data,
    entry_options,
    make_entry,
    mock_frontend,
    mock_push,
)

pytestmark = pytest.mark.usefixtures("mock_frontend", "mock_push")


@pytest.fixture
def kitchen(hass: HomeAssistant) -> str:
    """A Kitchen area with two lights and a thermostat."""
    area_id = ar.async_get(hass).async_create("Kitchen").id
    ent_reg = er.async_get(hass)
    for domain, object_id, state in (
        ("light", "ceiling", "on"),
        ("light", "counter", "off"),
        ("climate", "radiator", "heat"),
    ):
        reg = ent_reg.async_get_or_create(domain, "test", object_id, suggested_object_id=object_id)
        ent_reg.async_update_entity(reg.entity_id, area_id=area_id)
        hass.states.async_set(reg.entity_id, state, {"friendly_name": object_id.title()})
    return area_id


async def test_diagnostics(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, kitchen: str
) -> None:
    """Diagnostics show entry, profile, viewport, mode, budget and views, host redacted."""
    assert await async_setup_component(hass, "diagnostics", {})
    entry = make_entry(
        hass,
        entry_data(area_id=kitchen, display_host="192.168.1.50"),
        entry_options(pages=["climate"]),
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    viewport = {"width": 480, "height": 480, "dpr": 1.5, "user_agent": "UA", "device": None}
    entry.runtime_data.viewport = viewport

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result == {
        "entry": {
            "title": "Kitchen",
            "version": 1,
            "minor_version": 1,
            "data": {
                "name": "Kitchen",
                "url_path": "wall-kitchen",
                "area_id": kitchen,
                "profile": "shelly_wall_display",
                "display_host": "**REDACTED**",
            },
            "options": entry_options(pages=["climate"]),
        },
        "dashboard_mode": "collection",
        "push_method": "notification",
        "viewport": viewport,
        "profile": {
            "id": "shelly_wall_display",
            "name": 'Shelly Wall Display (4")',
            "width": 480,
            "height": 480,
            "dpr_hint": 1.0,
            "measured": False,
            "orientation": "square",
        },
        "area_name": "Kitchen",
        "role": "room",
        "language": "en",
        "budget": {
            "rows": 6,
            "footer": True,
            "views": {
                "home": {"rows": 6, "footer": True},
                "climate": {"rows": 6, "footer": True},
            },
        },
        "views": [
            # Two light tiles and the status strip.
            {"path": "home", "footer": True, "sections": 1, "cards": 3},
            {"path": "climate", "footer": True, "sections": 1, "cards": 1},
        ],
    }


async def test_diagnostics_generator_error(hass: HomeAssistant, kitchen: str) -> None:
    """A failing build is reported instead of breaking the download."""
    entry = make_entry(hass, entry_data(area_id=kitchen))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(f"{PACKAGE}.generator.build_dashboard", side_effect=RuntimeError("boom")):
        result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["error"] == "RuntimeError: boom"
    assert result["profile"]["id"] == "shelly_wall_display"
    assert "views" not in result
    assert result["dashboard_mode"] == "collection"
