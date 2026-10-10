"""Create and remove the Lovelace dashboard that belongs to a wall display.

The preferred path registers the dashboard in Home Assistant's own dashboards
collection, so it shows up under Settings > Dashboards like any other storage
dashboard. That collection is not exposed publicly, so it is located through
the websocket handlers lovelace registers for ``lovelace/dashboards/*``: those
are bound methods of a ``DashboardsCollectionWebSocket`` (wrapped in
``require_admin``/``async_response``) that holds ``.storage_collection``.

If the collection cannot be found, a panel is registered directly and a
``LovelaceStorage`` is injected into lovelace's dashboard map. The stored
config is the same in both cases.

User edits are respected: the title is set only when the dashboard is
created, ``show_in_sidebar`` only when the option changes, and a dashboard
the user took control of (its stored config is no longer our strategy) is
never changed or deleted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.components import frontend, websocket_api
from homeassistant.components.lovelace.const import (
    LOVELACE_DATA,
    MODE_STORAGE,
    ConfigNotFound,
)
from homeassistant.components.lovelace.dashboard import (
    CONFIG_STORAGE_KEY,
    CONFIG_STORAGE_VERSION,
    LovelaceStorage,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import collection
from homeassistant.helpers.storage import Store

from .const import (
    CONF_NAME,
    CONF_SHOW_IN_SIDEBAR,
    CONF_URL_PATH,
    DOMAIN,
    STRATEGY_TYPE,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

DASHBOARD_ICON = "mdi:tablet-dashboard"
MODE_COLLECTION = "collection"
MODE_PANEL = "panel"
MODE_FAILED = "failed"  # the url_path belongs to someone else

_COLLECTION_COMMANDS = (
    "lovelace/dashboards/create",
    "lovelace/dashboards/update",
    "lovelace/dashboards/delete",
    "lovelace/dashboards/list",
)
_FALLBACK_KEY = f"{DOMAIN}_fallback_panels"
# show_in_sidebar as last applied per url_path, so a later change made in
# Settings > Dashboards survives until the option itself changes.
_APPLIED_KEY = f"{DOMAIN}_applied"
APPLIED_STORE_KEY = f"{DOMAIN}.dashboards"
APPLIED_STORE_VERSION = 1


class _Applied:
    """Persistent record of the sidebar flag last written to each dashboard."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict[str, Any]](hass, APPLIED_STORE_VERSION, APPLIED_STORE_KEY)
        self._data: dict[str, Any] | None = None

    async def _async_data(self) -> dict[str, Any]:
        if self._data is None:
            self._data = await self._store.async_load() or {}
        return self._data

    async def async_get(self, url_path: str) -> bool | None:
        value = (await self._async_data()).get(url_path, {}).get(CONF_SHOW_IN_SIDEBAR)
        return value if isinstance(value, bool) else None

    async def async_set(self, url_path: str, show_in_sidebar: bool | None) -> None:
        """Record the applied value; None forgets the dashboard."""
        data = await self._async_data()
        wanted = None if show_in_sidebar is None else {CONF_SHOW_IN_SIDEBAR: show_in_sidebar}
        if data.get(url_path) == wanted:
            return
        if wanted is None:
            data.pop(url_path)
        else:
            data[url_path] = wanted
        await self._store.async_save(data)


def _applied(hass: HomeAssistant) -> _Applied:
    if (applied := hass.data.get(_APPLIED_KEY)) is None:
        applied = hass.data[_APPLIED_KEY] = _Applied(hass)
    return applied


def strategy_config(entry_id: str) -> dict[str, Any]:
    """Return the stored dashboard config for an entry."""
    return {"strategy": {"type": STRATEGY_TYPE, "entry_id": entry_id}}


def is_own_strategy(config: dict[str, Any] | None) -> bool:
    """Return True if a stored config is still our strategy (not taken over)."""
    if not isinstance(config, dict):
        return False
    strategy = config.get("strategy")
    return isinstance(strategy, dict) and strategy.get("type") == STRATEGY_TYPE


def _iter_children(obj: Any) -> Iterable[Any]:
    """Yield objects reachable from a (possibly decorated) callable."""
    for attr in ("__wrapped__", "__self__", "func"):
        child = getattr(obj, attr, None)
        if child is not None:
            yield child
    for cell in getattr(obj, "__closure__", None) or ():
        try:
            yield cell.cell_contents
        except ValueError:  # empty cell
            continue


def _collection_from_handler(handler: Any) -> collection.StorageCollection | None:
    """Walk decorators/bound methods until a storage collection turns up."""
    seen: set[int] = set()
    stack = [handler]
    while stack:
        obj = stack.pop()
        if id(obj) in seen or len(seen) > 64:
            continue
        seen.add(id(obj))
        found = getattr(obj, "storage_collection", None)
        if isinstance(found, collection.StorageCollection):
            return found
        stack.extend(_iter_children(obj))
    return None


def find_dashboards_collection(hass: HomeAssistant) -> collection.StorageCollection | None:
    """Return lovelace's DashboardsCollection, or None if it can't be found."""
    handlers: dict[str, Any] = hass.data.get(websocket_api.DOMAIN) or {}
    for command in _COLLECTION_COMMANDS:
        registered = handlers.get(command)
        if not registered:
            continue
        handler = registered[0] if isinstance(registered, tuple) else registered
        if (found := _collection_from_handler(handler)) is not None:
            return found
    return None


def _desired_item(entry: ConfigEntry) -> dict[str, Any]:
    url_path: str = entry.data[CONF_URL_PATH]
    return {
        "url_path": url_path,
        "title": entry.data.get(CONF_NAME) or entry.title or url_path,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": bool(entry.options.get(CONF_SHOW_IN_SIDEBAR, True)),
        "require_admin": False,
        "mode": MODE_STORAGE,
    }


def _find_item(coll: collection.StorageCollection, url_path: str) -> dict[str, Any] | None:
    for item in coll.async_items():
        if item.get("url_path") == url_path:
            return item
    return None


async def _async_stored_config(hass: HomeAssistant, url_path: str) -> dict[str, Any] | None:
    """The dashboard's stored config, or None if it has none (or isn't loaded)."""
    store = hass.data[LOVELACE_DATA].dashboards.get(url_path)
    if store is None:
        return None
    try:
        return await store.async_load(False)
    except ConfigNotFound:
        return None


async def _async_taken_over(hass: HomeAssistant, url_path: str) -> bool:
    """True if the user took control: a stored config that isn't our strategy."""
    current = await _async_stored_config(hass, url_path)
    return current is not None and not is_own_strategy(current)


def _log_taken_over(url_path: str, action: str) -> None:
    _LOGGER.info(
        "Dashboard %s is no longer managed by %s (taken control); %s",
        url_path,
        DOMAIN,
        action,
    )


async def _async_save_strategy(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Write our strategy config unless the user took control of the dashboard."""
    url_path = entry.data[CONF_URL_PATH]
    store = hass.data[LOVELACE_DATA].dashboards.get(url_path)
    if store is None:
        _LOGGER.warning("Dashboard %s has no lovelace config object", url_path)
        return
    current = await _async_stored_config(hass, url_path)
    if current is not None and not is_own_strategy(current):
        _log_taken_over(url_path, "leaving it as is")
        return
    wanted = strategy_config(entry.entry_id)
    if current != wanted:
        await store.async_save(wanted)


def _fallback_paths(hass: HomeAssistant) -> set[str]:
    return hass.data.setdefault(_FALLBACK_KEY, set())


async def _async_ensure_collection(
    hass: HomeAssistant, entry: ConfigEntry, coll: collection.StorageCollection
) -> bool:
    """Create or update the dashboard item. Returns False if it can't be owned."""
    desired = _desired_item(entry)
    url_path = desired["url_path"]
    item = _find_item(coll, url_path)

    if item is None:
        # A panel we registered ourselves earlier (fallback path) must go first.
        if url_path in _fallback_paths(hass):
            frontend.async_remove_panel(hass, url_path, warn_if_unknown=False)
            hass.data[LOVELACE_DATA].dashboards.pop(url_path, None)
            _fallback_paths(hass).discard(url_path)
        try:
            await coll.async_create_item(dict(desired))
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Could not create dashboard %s: %s", url_path, err)
            return False
        await _applied(hass).async_set(url_path, desired["show_in_sidebar"])
        return True

    if await _async_taken_over(hass, url_path):
        return True  # its metadata belongs to the user now

    # The title is the user's after creation; the sidebar flag follows the
    # option only when the option changed since it was last applied.
    wanted = desired["show_in_sidebar"]
    applied = _applied(hass)
    if await applied.async_get(url_path) != wanted:
        if item.get("show_in_sidebar") != wanted:
            await coll.async_update_item(item["id"], {"show_in_sidebar": wanted})
        await applied.async_set(url_path, wanted)
    return True


def _register_fallback_panel(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the panel ourselves. Returns False if the url_path isn't ours."""
    desired = _desired_item(entry)
    url_path = desired["url_path"]
    dashboards = hass.data[LOVELACE_DATA].dashboards
    owned = _fallback_paths(hass)

    if url_path not in owned and (
        url_path in dashboards or frontend.async_panel_exists(hass, url_path)
    ):
        _LOGGER.warning("Panel %s already exists and is not ours; not touching it", url_path)
        return False

    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=desired["title"],
        sidebar_icon=desired["icon"],
        frontend_url_path=url_path,
        config={"mode": MODE_STORAGE},
        require_admin=False,
        show_in_sidebar=desired["show_in_sidebar"],
        update=True,
    )
    item = {"id": url_path, **desired}
    if (existing := dashboards.get(url_path)) is not None:
        existing.config = {**item}
    else:
        dashboards[url_path] = LovelaceStorage(hass, item)
    owned.add(url_path)
    return True


async def async_ensure_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Make sure the entry's dashboard exists.

    Returns "collection" or "panel", or "failed" when the url_path belongs to
    someone else (then nothing is touched).
    """
    coll = find_dashboards_collection(hass)
    if coll is not None:
        mode = MODE_COLLECTION
        owned = await _async_ensure_collection(hass, entry, coll)
    else:
        _LOGGER.debug("Dashboards collection not found, registering a plain panel")
        mode = MODE_PANEL
        owned = _register_fallback_panel(hass, entry)
    if not owned:
        _LOGGER.warning(
            "No dashboard for %s: /%s is already used by another dashboard or panel",
            entry.title,
            entry.data[CONF_URL_PATH],
        )
        return MODE_FAILED

    await _async_save_strategy(hass, entry)
    return mode


async def async_remove_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the entry's dashboard and its stored config, unless the user took control."""
    url_path: str = entry.data[CONF_URL_PATH]
    await _applied(hass).async_set(url_path, None)

    if await _async_taken_over(hass, url_path):
        _log_taken_over(url_path, "keeping it")
        return

    coll = find_dashboards_collection(hass)
    if coll is not None and (item := _find_item(coll, url_path)) is not None:
        # The lovelace listener removes the panel and deletes the stored config.
        await coll.async_delete_item(item["id"])
        return

    frontend.async_remove_panel(hass, url_path, warn_if_unknown=False)
    _fallback_paths(hass).discard(url_path)
    store = hass.data[LOVELACE_DATA].dashboards.pop(url_path, None)
    if store is not None:
        try:
            await store.async_delete()
        except HomeAssistantError as err:
            _LOGGER.warning("Could not delete dashboard config %s: %s", url_path, err)
        return

    # Not loaded in this run: drop the storage file directly, if it is ours.
    store = Store[dict[str, Any]](hass, CONFIG_STORAGE_VERSION, CONFIG_STORAGE_KEY.format(url_path))
    stored = await store.async_load()
    config = stored.get("config") if isinstance(stored, dict) else None
    if config is not None and not is_own_strategy(config):
        _log_taken_over(url_path, "keeping it")
        return
    await store.async_remove()
