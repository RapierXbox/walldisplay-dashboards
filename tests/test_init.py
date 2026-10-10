"""Tests for setting up, reloading and removing a wall display entry."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.websocket_api import DOMAIN as WS_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.walldisplay_dashboards import async_setup, display_link
from custom_components.walldisplay_dashboards.const import (
    DOMAIN,
    FRONTEND_SCRIPT,
    FRONTEND_URL_BASE,
    STRATEGY_TYPE,
    VERSION,
    WS_GENERATE,
    WS_LIST,
    WS_REPORT_VIEWPORT,
)

from .helpers_backend import (  # noqa: F401
    PACKAGE,
    entry_data,
    make_entry,
    mock_frontend,
)

URL = "wall-kitchen"
PUSH_STORE = f"{DOMAIN}.pushed"

pytestmark = pytest.mark.usefixtures("mock_frontend")


@pytest.fixture
def push() -> Generator[dict[str, AsyncMock]]:
    """Patch the display link so setup doesn't talk to devices."""
    with (
        patch(f"{PACKAGE}.display_link.async_push_url", return_value="notification") as push_url,
        patch(f"{PACKAGE}.display_link.async_refresh_display", return_value=False) as refresh,
    ):
        yield {"push": push_url, "refresh": refresh}


async def _setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_entry(hass: HomeAssistant, push, hass_storage) -> None:
    """Setup serves the module, registers commands, creates the dashboard and pushes once."""
    entry = make_entry(hass)
    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    script = f"{FRONTEND_URL_BASE}/{FRONTEND_SCRIPT}?v={VERSION}"
    assert script in hass.data[DATA_EXTRA_MODULE_URL].urls
    for command in (WS_GENERATE, WS_LIST, WS_REPORT_VIEWPORT):
        assert command in hass.data[WS_DOMAIN]
    assert entry.runtime_data.dashboard_mode == "collection"
    assert entry.runtime_data.viewport is None
    assert URL in hass.data[DATA_PANELS]
    stored = await hass.data[LOVELACE_DATA].dashboards[URL].async_load(False)
    assert stored == {"strategy": {"type": STRATEGY_TYPE, "entry_id": entry.entry_id}}

    push["push"].assert_awaited_once()
    push["refresh"].assert_not_awaited()
    assert hass_storage[PUSH_STORE]["data"][entry.entry_id]["url_path"] == URL


async def test_foreign_url_path_is_not_pushed(hass: HomeAssistant, push) -> None:
    """If another panel owns the url_path, setup goes on but nothing is pushed."""
    from homeassistant.components import frontend

    frontend.async_register_built_in_panel(hass, "iframe", frontend_url_path=URL)
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.dashboard_mode == "failed"
    assert hass.data[DATA_PANELS][URL].component_name == "iframe"
    push["push"].assert_not_awaited()


async def test_async_setup_is_guarded(hass: HomeAssistant, push) -> None:
    """Calling async_setup again doesn't register routes twice."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert await async_setup(hass, {})


async def test_reload_refreshes_without_push(hass: HomeAssistant, push) -> None:
    """A reload fires lovelace_updated and refreshes the display, no new push."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    push["push"].assert_awaited_once()
    push["refresh"].assert_awaited_once()
    assert {"url_path": URL} in [e.data for e in events]


async def test_no_push_after_restart(hass: HomeAssistant, push, hass_storage) -> None:
    """A display already pointed at the dashboard isn't pushed again."""
    entry = make_entry(hass)
    hass_storage[PUSH_STORE] = {
        "version": 1,
        "key": PUSH_STORE,
        "data": {
            entry.entry_id: {"url_path": URL, "display_device_id": None, "display_host": None}
        },
    }
    await _setup(hass, entry)
    push["push"].assert_not_awaited()
    push["refresh"].assert_not_awaited()


async def test_push_again_when_target_changes(hass: HomeAssistant, push) -> None:
    """Changing the display host (reconfigure) pushes the URL again."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    hass.config_entries.async_update_entry(entry, data=entry_data(display_host="10.0.0.5"))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert push["push"].await_count == 2


async def test_failed_push_is_retried(hass: HomeAssistant, push, hass_storage) -> None:
    """A push that did nothing ("none") is retried on the next setup."""
    push["push"].return_value = "none"
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert entry.entry_id not in hass_storage.get(PUSH_STORE, {}).get("data", {})
    assert entry.runtime_data.push_method == "none"


async def test_unload_keeps_dashboard(hass: HomeAssistant, push) -> None:
    """Unloading leaves the dashboard in place."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert URL in hass.data[DATA_PANELS]
    assert URL in hass.data[LOVELACE_DATA].dashboards


async def test_remove_entry_deletes_dashboard(hass: HomeAssistant, push, hass_storage) -> None:
    """Deleting the entry removes its dashboard and the push record."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert URL not in hass.data[DATA_PANELS]
    assert URL not in hass.data[LOVELACE_DATA].dashboards
    assert entry.entry_id not in hass_storage[PUSH_STORE]["data"]


async def test_registry_change_regenerates(hass: HomeAssistant, push) -> None:
    """Registry updates fire one debounced lovelace_updated per display."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    second = make_entry(hass, entry_data(name="Hall", url_path="wall-hall"))
    await _setup(hass, second)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)

    registry = ar.async_get(hass)
    registry.async_create("Pantry")
    registry.async_create("Cellar")
    await hass.async_block_till_done()
    assert events == []

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert sorted(e.data["url_path"] for e in events) == ["wall-hall", URL]


async def test_empty_room_issue(
    hass: HomeAssistant, push, issue_registry: ir.IssueRegistry
) -> None:
    """An area with nothing to show raises an issue for the admin (U18); a light clears it."""
    kitchen = ar.async_get(hass).async_create("Kitchen")
    entry = make_entry(hass, entry_data(area_id=kitchen.id))
    await _setup(hass, entry)
    issue_id = f"empty_room_{entry.entry_id}"
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert not issue.is_fixable
    assert issue.translation_key == "empty_room"
    assert issue.translation_placeholders == {"name": "Kitchen", "area": "Kitchen"}

    light = er.async_get(hass).async_get_or_create(
        "light", "test", "ceiling", suggested_object_id="kitchen_ceiling"
    )
    hass.states.async_set(light.entity_id, "off", {"friendly_name": "Kitchen Ceiling"})
    er.async_get(hass).async_update_entity(light.entity_id, area_id=kitchen.id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    # The issue goes with the entry.
    er.async_get(hass).async_remove(light.entity_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_registry_listener_stops_after_last_unload(hass: HomeAssistant, push) -> None:
    """No events once every display is unloaded."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)
    ar.async_get(hass).async_create("Pantry")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert events == []


def _options_input(result: dict, entry, **values) -> dict:
    """Answer every required field of the options form, overriding some."""
    import probatio

    answer: dict = {}
    for key in result["data_schema"].schema:
        name = str(key)
        if name in values:
            answer[name] = values[name]
        elif isinstance(key, probatio.Required):
            # What the form pre-fills: the suggested value, else the default.
            suggested = (getattr(key, "description", None) or {}).get("suggested_value")
            if suggested is None and callable(getattr(key, "default", None)):
                suggested = key.default()
            if suggested is None:
                suggested = entry.options.get(name)
            if suggested is not None:
                answer[name] = suggested
    for name, value in values.items():
        answer.setdefault(name, value)
    return answer


async def test_options_flow_end_to_end(hass: HomeAssistant) -> None:
    """Regression: finishing the real options flow reloads without errors.

    Update listeners are not allowed together with OptionsFlowWithReload; the
    reload itself must still rebuild open dashboards and refresh the display.
    """
    entry = make_entry(hass)
    real_refresh = display_link.async_refresh_display
    with patch.object(display_link, "async_refresh_display", side_effect=real_refresh) as refresh:
        await _setup(hass, entry)
        assert entry.update_listeners == []
        refresh.assert_not_called()

        events = []
        hass.bus.async_listen("lovelace_updated", events.append)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            _options_input(
                result, entry, pages=["climate"], idle_seconds=30, show_in_sidebar=False
            ),
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options["idle_seconds"] == 30
    assert entry.options["show_in_sidebar"] is False
    assert hass.data[DATA_PANELS][URL].show_in_sidebar is False
    refresh.assert_called_once()
    assert {"url_path": URL} in [e.data for e in events]


async def test_language_change_regenerates(hass: HomeAssistant, push) -> None:
    """Changing the HA language rebuilds open dashboards; other core changes don't."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)

    await hass.config.async_update(location_name="Somewhere else")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert events == []

    await hass.config.async_update(language="de")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert [e.data["url_path"] for e in events] == [URL]
