"""Shared helpers and fixtures for the backend tests.

Import the fixtures you need into a test module, e.g.
``from .helpers_backend import mock_frontend  # noqa: F401``.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.frontend import (
    DATA_EXTRA_JS_URL_ES5,
    DATA_EXTRA_MODULE_URL,
    UrlManager,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

PACKAGE = "custom_components.walldisplay_dashboards"

DOMAIN = "walldisplay_dashboards"


def entry_data(**overrides: Any) -> dict[str, Any]:
    """Config entry data using the contract keys."""
    data: dict[str, Any] = {
        "name": "Kitchen",
        "url_path": "wall-kitchen",
        "area_id": "kitchen",
        "profile": "shelly_wall_display",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def entry_options(**overrides: Any) -> dict[str, Any]:
    """Config entry options using the contract keys."""
    options: dict[str, Any] = {
        "pages": ["climate", "media", "scenes"],
        "idle_seconds": 60,
        "kiosk": "builtin",
        "pinned": [],
        "hidden": [],
        "scene_buttons": [],
        "show_in_sidebar": True,
    }
    options.update(overrides)
    return options


def make_entry(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Create and register a MockConfigEntry."""
    data = data or entry_data()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=data.get("name", "Kitchen"),
        unique_id=data["url_path"],
        data=data,
        options=options if options is not None else entry_options(),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def mock_frontend(hass: HomeAssistant) -> None:
    """Pretend the frontend is set up (the frontend package isn't installed in tests)."""
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])
    hass.data[DATA_EXTRA_JS_URL_ES5] = UrlManager(lambda *_: None, [])
    hass.config.components.add("frontend")
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "lovelace", {})


@pytest.fixture
def mock_push() -> Generator[dict[str, AsyncMock]]:
    """Patch the display link so setup doesn't talk to devices."""
    with (
        patch(f"{PACKAGE}.display_link.async_push_url", return_value="notification") as push,
        patch(f"{PACKAGE}.display_link.async_refresh_display", return_value=False) as refresh,
    ):
        yield {"push": push, "refresh": refresh}
