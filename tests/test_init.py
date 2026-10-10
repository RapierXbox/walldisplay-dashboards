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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.walldisplay_dashboards import (
    REGISTRY_DEBOUNCE_SECONDS,
    async_setup,
    display_link,
)
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


async def test_foreign_url_path_fails_setup(hass: HomeAssistant, push) -> None:
    """If another panel owns the url_path, setup fails (translated) and nothing is pushed."""
    from homeassistant.components import frontend

    frontend.async_register_built_in_panel(hass, "iframe", frontend_url_path=URL)
    entry = make_entry(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason == (
        f"The address /{URL} is already used by another dashboard or panel. "
        "Remove that dashboard or panel, then reload this entry"
    )
    assert entry.error_reason_translation_key == "url_path_taken"
    assert entry.runtime_data.dashboard_mode == "failed"
    assert hass.data[DATA_PANELS][URL].component_name == "iframe"
    push["push"].assert_not_awaited()
    assert not dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)


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


def _light(hass: HomeAssistant, object_id: str, name: str, area_id: str) -> str:
    """A registered light with a state, in an area."""
    registry = er.async_get(hass)
    light = registry.async_get_or_create("light", "test", object_id, suggested_object_id=object_id)
    hass.states.async_set(light.entity_id, "off", {"friendly_name": name})
    registry.async_update_entity(light.entity_id, area_id=area_id)
    return light.entity_id


class _Clock:
    """Moves time past the registry debouncer, one cooldown per step."""

    def __init__(self) -> None:
        self.now = dt_util.utcnow()

    async def step(self, hass: HomeAssistant) -> None:
        await hass.async_block_till_done()
        self.now += timedelta(seconds=REGISTRY_DEBOUNCE_SECONDS + 1)
        async_fire_time_changed(hass, self.now)
        await hass.async_block_till_done()


async def test_registry_change_regenerates(hass: HomeAssistant, push) -> None:
    """Registry updates fire lovelace_updated only for displays whose dashboard changed."""
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen").id
    hall = areas.async_create("Hall").id
    entry = make_entry(hass, entry_data(area_id=kitchen))
    await _setup(hass, entry)
    second = make_entry(hass, entry_data(name="Hall", url_path="wall-hall", area_id=hall))
    await _setup(hass, second)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)
    clock = _Clock()

    # Nothing either display shows.
    areas.async_create("Pantry")
    areas.async_create("Cellar")
    await clock.step(hass)
    assert events == []

    # A light in the kitchen: the kitchen display only, once for the burst.
    _light(hass, "kitchen_ceiling", "Ceiling", kitchen)
    _light(hass, "kitchen_counter", "Counter", kitchen)
    await clock.step(hass)
    await clock.step(hass)
    assert [e.data["url_path"] for e in events] == [URL]

    # Both rooms change.
    events.clear()
    _light(hass, "kitchen_island", "Island", kitchen)
    _light(hass, "hall_ceiling", "Hall lamp", hall)
    await clock.step(hass)
    await clock.step(hass)
    assert sorted(e.data["url_path"] for e in events) == ["wall-hall", URL]


async def test_unrelated_entity_rename_is_ignored(hass: HomeAssistant, push) -> None:
    """Renaming an entity in another room fires nothing; one in the room fires."""
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen").id
    bedroom = areas.async_create("Bedroom").id
    ceiling = _light(hass, "kitchen_ceiling", "Ceiling", kitchen)
    bedside = _light(hass, "bedside", "Bedside", bedroom)
    await _setup(hass, make_entry(hass, entry_data(area_id=kitchen)))
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)
    clock = _Clock()

    registry = er.async_get(hass)
    registry.async_update_entity(bedside, name="Reading lamp")
    await clock.step(hass)
    assert events == []

    registry.async_update_entity(ceiling, name="Main light")
    await clock.step(hass)
    await clock.step(hass)
    assert [e.data["url_path"] for e in events] == [URL]


async def test_floor_rename_regenerates(hass: HomeAssistant, push) -> None:
    """Floor names are dropped from tile names, so a floor rename can change the dashboard."""
    floors = fr.async_get(hass)
    ground = floors.async_create("Ground")
    kitchen = ar.async_get(hass).async_create("Kitchen", floor_id=ground.floor_id).id
    _light(hass, "ground_light", "Ground light", kitchen)
    await _setup(hass, make_entry(hass, entry_data(area_id=kitchen)))
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)

    floors.async_update(ground.floor_id, name="Upstairs")
    await _Clock().step(hass)
    assert [e.data["url_path"] for e in events] == [URL]


async def test_failed_rebuild_fires_once(hass: HomeAssistant, push) -> None:
    """A dashboard that can't be built is announced once (panels show the error)."""
    entry = make_entry(hass)
    await _setup(hass, entry)
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)
    clock = _Clock()
    with patch(f"{PACKAGE}.generator.build_dashboard", side_effect=RuntimeError("boom")):
        ar.async_get(hass).async_create("Pantry")
        await clock.step(hass)
        assert [e.data["url_path"] for e in events] == [URL]
        ar.async_get(hass).async_create("Cellar")
        await clock.step(hass)
        await clock.step(hass)
        assert len(events) == 1
    # Built again: the panels need the real dashboard back.
    ar.async_get(hass).async_create("Attic")
    await clock.step(hass)
    await clock.step(hass)
    assert len(events) == 2


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


async def test_room_check_error_is_logged(
    hass: HomeAssistant, push, issue_registry: ir.IssueRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    """A room that can't be read is logged; setup still succeeds and no issue is raised."""
    entry = make_entry(hass)
    with patch(f"{PACKAGE}.entities.collect_input", side_effect=RuntimeError("registry broken")):
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert "Could not check the room of Kitchen" in caplog.text
    assert issue_registry.async_get_issue(DOMAIN, f"empty_room_{entry.entry_id}") is None


async def test_remove_entry_not_loaded(hass: HomeAssistant, push, hass_storage) -> None:
    """Removing an entry that was never set up in this run still forgets its push record."""
    entry = make_entry(hass)
    other = "other-entry"
    record = {"url_path": URL, "display_device_id": None, "display_host": None}
    hass_storage[PUSH_STORE] = {
        "version": 1,
        "key": PUSH_STORE,
        "data": {entry.entry_id: record, other: record},
    }
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[PUSH_STORE]["data"] == {other: record}
