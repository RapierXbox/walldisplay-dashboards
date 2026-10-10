"""Wall Display Dashboards: one generated Lovelace dashboard per wall display."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, EVENT_LOVELACE_UPDATED, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.floor_registry import EVENT_FLOOR_REGISTRY_UPDATED
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from . import dashboards, display_link, entities, repairs, websocket
from .const import (
    CONF_DISPLAY_DEVICE_ID,
    CONF_DISPLAY_HOST,
    CONF_HEIGHT,
    CONF_NAME,
    CONF_PROFILE,
    CONF_URL_PATH,
    CONF_WIDTH,
    DOMAIN,
    FRONTEND_SCRIPT,
    FRONTEND_URL_BASE,
    VERSION,
)
from .generator.room import is_empty_room
from .models import GeneratorInput, ViewportReport
from .profiles import DEFAULT_PROFILE, resolve_profile
from .websocket import async_register_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FRONTEND_DIR = Path(__file__).parent / "frontend"
# Registry changes come in bursts (an integration adding a device, a rename in the UI).
# Rebuilding is cheap in Python, but every lovelace_updated makes each open panel fetch
# and re-render its whole dashboard, which takes seconds on a wall display's CPU.
REGISTRY_DEBOUNCE_SECONDS = 5.0
PUSH_STORE_VERSION = 1
PUSH_STORE_KEY = f"{DOMAIN}.pushed"
MANUFACTURER = "Wall Display Dashboards"
_BUILD_FAILED = "failed"  # digest stand-in for a dashboard that could not be built


@dataclass
class WallDisplayData:
    """Runtime data of one wall display entry."""

    dashboard_mode: str = ""
    viewport: ViewportReport | None = None
    url_path: str = ""
    push_method: str | None = None


type WallDisplayConfigEntry = ConfigEntry[WallDisplayData]


@dataclass
class _DomainData:
    """Integration-wide state, created once per Home Assistant run."""

    push_store: Store[dict[str, Any]]
    pushed: dict[str, dict[str, Any]] | None = None
    set_up_entries: set[str] = field(default_factory=set)
    unsub_registry: list[CALLBACK_TYPE] = field(default_factory=list)
    debouncer: Debouncer[None] | None = None
    # Digest of the dashboard open panels were last told about, per entry (lovelace_updated
    # only fires when a rebuild differs from it).
    digests: dict[str, str] = field(default_factory=dict)
    registered: bool = False  # static path, frontend module and websocket commands


DATA_KEY: HassKey[_DomainData] = HassKey(DOMAIN)


def _domain_data(hass: HomeAssistant) -> _DomainData:
    if (data := hass.data.get(DATA_KEY)) is None:
        data = hass.data[DATA_KEY] = _DomainData(
            push_store=Store(hass, PUSH_STORE_VERSION, PUSH_STORE_KEY)
        )
    return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the frontend module and register the websocket commands (once)."""
    domain = _domain_data(hass)
    if domain.registered:
        return True
    domain.registered = True

    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=True)]
    )
    frontend.add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{FRONTEND_SCRIPT}?v={VERSION}")
    async_register_commands(hass)
    return True


def _push_signature(entry: ConfigEntry) -> dict[str, Any]:
    """What the display was last pointed at; a change triggers a new push."""
    return {
        CONF_URL_PATH: entry.data.get(CONF_URL_PATH),
        CONF_DISPLAY_DEVICE_ID: entry.data.get(CONF_DISPLAY_DEVICE_ID),
        CONF_DISPLAY_HOST: entry.data.get(CONF_DISPLAY_HOST),
    }


async def _async_push_if_needed(hass: HomeAssistant, entry: WallDisplayConfigEntry) -> None:
    domain = _domain_data(hass)
    if domain.pushed is None:
        domain.pushed = await domain.push_store.async_load() or {}
    signature = _push_signature(entry)
    if domain.pushed.get(entry.entry_id) == signature:
        return
    method = await display_link.async_push_url(hass, entry)
    entry.runtime_data.push_method = method
    _LOGGER.debug("Pushed dashboard URL for %s via %s", entry.title, method)
    if method != display_link.METHOD_NONE:
        domain.pushed[entry.entry_id] = signature
        await domain.push_store.async_save(domain.pushed)


@callback
def fire_lovelace_updated(hass: HomeAssistant, url_paths: list[str]) -> None:
    """Tell open dashboards to fetch (and so regenerate) their config."""
    for url_path in url_paths:
        hass.bus.async_fire(EVENT_LOVELACE_UPDATED, {"url_path": url_path})


def _loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and CONF_URL_PATH in entry.data
    ]


@callback
def _async_check_empty_room(
    hass: HomeAssistant, entry: ConfigEntry, data: GeneratorInput | None = None
) -> None:
    """Raise (or clear) the empty-room issue: no tiles and no pages (U18)."""
    try:
        if data is None:
            data = entities.collect_input(hass, entities.display_config_from_entry(hass, entry))
        empty = is_empty_room(data)
    except Exception:
        _LOGGER.exception("Could not check the room of %s", entry.title)
        return
    repairs.async_update_empty_room_issue(
        hass, entry.entry_id, empty=empty, name=data.display.name, area=data.area_name
    )


@callback
def _async_rebuild(hass: HomeAssistant, entry: ConfigEntry, *, keep: bool = True) -> bool:
    """Rebuild one display's dashboard and check its room.

    Returns True if open panels must re-render: the dashboard differs from the one
    they were last told about, or it can't be built (they then show the error).
    """
    digests = _domain_data(hass).digests
    try:
        built = websocket.build(hass, entry, keep=keep)
    except Exception:
        _LOGGER.debug("Could not rebuild the dashboard of %s", entry.title, exc_info=True)
        websocket.forget(hass, entry.entry_id)
        _async_check_empty_room(hass, entry)
        # Panels then show the error dashboard: tell them once, not on every update.
        previous = digests.get(entry.entry_id)
        digests[entry.entry_id] = _BUILD_FAILED
        return previous != _BUILD_FAILED
    _async_check_empty_room(hass, entry, built.data)
    previous = digests.get(entry.entry_id)
    digests[entry.entry_id] = built.digest
    return previous != built.digest


@callback
def _async_start_registry_listener(hass: HomeAssistant) -> None:
    domain = _domain_data(hass)
    if domain.unsub_registry:
        return

    @callback
    def _regenerate() -> None:
        # Only displays whose dashboard actually changed: most registry updates (a
        # device's firmware, an entity in another room) don't touch any of them.
        changed = [entry for entry in _loaded_entries(hass) if _async_rebuild(hass, entry)]
        fire_lovelace_updated(hass, [entry.data[CONF_URL_PATH] for entry in changed])

    domain.debouncer = debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=REGISTRY_DEBOUNCE_SECONDS,
        immediate=False,
        function=_regenerate,
    )

    @callback
    def _on_registry_update(event: Event[Any]) -> None:
        debouncer.async_schedule_call()

    @callback
    def _on_core_config_update(event: Event) -> None:
        # Labels are localised in Python, so a language change needs a rebuild.
        if "language" in event.data:
            debouncer.async_schedule_call()

    # Persons are registered entities, so adding or removing one (entrance role)
    # already arrives as an entity registry update; their state is live in the tiles.
    domain.unsub_registry = [
        hass.bus.async_listen(EVENT_AREA_REGISTRY_UPDATED, _on_registry_update),
        hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, _on_registry_update),
        hass.bus.async_listen(EVENT_DEVICE_REGISTRY_UPDATED, _on_registry_update),
        # Floor names are dropped from tile names.
        hass.bus.async_listen(EVENT_FLOOR_REGISTRY_UPDATED, _on_registry_update),
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _on_core_config_update),
    ]


@callback
def _async_stop_registry_listener(hass: HomeAssistant) -> None:
    domain = _domain_data(hass)
    for unsub in domain.unsub_registry:
        unsub()
    domain.unsub_registry = []
    if domain.debouncer is not None:
        domain.debouncer.async_cancel()
        domain.debouncer = None


@callback
def async_update_device(hass: HomeAssistant, entry: ConfigEntry) -> dr.DeviceEntry:
    """Create or update the entry's service device and drop any other device.

    One device per entry, identified by the entry id, so it never changes and
    goes away with the entry. Anything else still linked to the entry (a device
    that would otherwise be orphaned) is detached from it.
    """
    url_path: str = entry.data[CONF_URL_PATH]
    profile = resolve_profile(
        entry.data.get(CONF_PROFILE, DEFAULT_PROFILE),
        entry.data.get(CONF_WIDTH),
        entry.data.get(CONF_HEIGHT),
    )
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        entry_type=dr.DeviceEntryType.SERVICE,
        name=entry.data.get(CONF_NAME) or entry.title,
        manufacturer=MANUFACTURER,
        model=profile.name,
        model_id=profile.id,
        sw_version=VERSION,
        # homeassistant:// links open the dashboard inside the frontend.
        configuration_url=f"homeassistant://{url_path}",
    )
    for other in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if other.id != device.id:
            registry.async_update_device(other.id, remove_config_entry_id=entry.entry_id)
    return device


async def async_setup_entry(hass: HomeAssistant, entry: WallDisplayConfigEntry) -> bool:
    """Set up one wall display."""
    domain = _domain_data(hass)
    is_reload = entry.entry_id in domain.set_up_entries
    url_path: str = entry.data[CONF_URL_PATH]

    entry.runtime_data = WallDisplayData(url_path=url_path)
    entry.runtime_data.dashboard_mode = await dashboards.async_ensure_dashboard(hass, entry)

    # Never point the display at a url_path that belongs to someone else.
    if entry.runtime_data.dashboard_mode == dashboards.MODE_FAILED:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="url_path_taken",
            translation_placeholders={"url_path": url_path},
        )
    await _async_push_if_needed(hass, entry)

    async_update_device(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_start_registry_listener(hass)
    domain.set_up_entries.add(entry.entry_id)

    # Open panels fetch this entry's dashboard now (setup, reload): it is the baseline
    # for change detection.
    domain.digests.pop(entry.entry_id, None)
    websocket.forget(hass, entry.entry_id)

    # After startup, so other integrations' entities have their states.
    @callback
    def _check_room(_hass: HomeAssistant) -> None:
        _async_rebuild(hass, entry, keep=False)

    entry.async_on_unload(async_at_started(hass, _check_room))

    # Not the first setup in this run: an options flow (OptionsFlowWithReload),
    # reconfigure or repair reloaded the entry. Rebuild open dashboards and
    # reload the page on the display.
    if is_reload:
        fire_lovelace_updated(hass, [url_path])
        entry.async_create_background_task(
            hass,
            display_link.async_refresh_display(hass, entry),
            f"{DOMAIN}_refresh_{entry.entry_id}",
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WallDisplayConfigEntry) -> bool:
    """Unload platforms; the dashboard itself stays."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        repairs.async_delete_empty_room_issue(hass, entry.entry_id)
    if unloaded and not [
        other
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
    ]:
        _async_stop_registry_listener(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: WallDisplayConfigEntry) -> None:
    """Entry deleted: remove its dashboard and forget the pushed URL."""
    await dashboards.async_remove_dashboard(hass, entry)
    domain = _domain_data(hass)
    domain.set_up_entries.discard(entry.entry_id)
    domain.digests.pop(entry.entry_id, None)
    websocket.forget(hass, entry.entry_id)
    if domain.pushed is None:
        domain.pushed = await domain.push_store.async_load() or {}
    if domain.pushed.pop(entry.entry_id, None) is not None:
        await domain.push_store.async_save(domain.pushed)
    repairs.async_delete_viewport_issue(hass, entry.entry_id)
    repairs.async_delete_empty_room_issue(hass, entry.entry_id)
