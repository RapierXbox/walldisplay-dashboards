"""Tests for dashboard creation and removal."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.components.lovelace.dashboard import (
    DashboardsCollection,
    LovelaceStorage,
)
from homeassistant.core import HomeAssistant

from custom_components.walldisplay_dashboards import dashboards
from custom_components.walldisplay_dashboards.const import STRATEGY_TYPE

from .helpers_backend import entry_data, entry_options, make_entry, mock_frontend  # noqa: F401

URL = "wall-kitchen"

pytestmark = pytest.mark.usefixtures("mock_frontend")


async def _stored(hass: HomeAssistant, url_path: str = URL) -> dict | None:
    try:
        return await hass.data[LOVELACE_DATA].dashboards[url_path].async_load(False)
    except ConfigNotFound:
        return None


def _items(hass: HomeAssistant) -> list[dict]:
    coll = dashboards.find_dashboards_collection(hass)
    assert coll is not None
    return [item for item in coll.async_items() if item["url_path"] == URL]


async def test_find_collection(hass: HomeAssistant) -> None:
    """The real DashboardsCollection is found through the websocket handlers."""
    assert isinstance(dashboards.find_dashboards_collection(hass), DashboardsCollection)


async def test_find_collection_missing(hass: HomeAssistant) -> None:
    """No handlers registered means no collection."""
    with patch.dict(hass.data, {"websocket_api": {}}):
        assert dashboards.find_dashboards_collection(hass) is None


async def test_create_via_collection(hass: HomeAssistant) -> None:
    """A new dashboard lands in the collection with our strategy config."""
    entry = make_entry(hass)

    assert await dashboards.async_ensure_dashboard(hass, entry) == "collection"

    (item,) = _items(hass)
    assert item["title"] == "Kitchen"
    assert item["icon"] == "mdi:tablet-dashboard"
    assert item["show_in_sidebar"] is True
    assert item["require_admin"] is False
    assert item["mode"] == "storage"
    assert URL in hass.data[DATA_PANELS]
    assert await _stored(hass) == {"strategy": {"type": STRATEGY_TYPE, "entry_id": entry.entry_id}}


async def test_ensure_is_idempotent(hass: HomeAssistant) -> None:
    """Calling twice keeps one item; a changed sidebar option is applied, the title stays."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    await dashboards.async_ensure_dashboard(hass, entry)
    assert len(_items(hass)) == 1

    hass.config_entries.async_update_entry(
        entry,
        data=entry_data(name="Küche"),
        options=entry_options(show_in_sidebar=False),
    )
    events = []
    hass.bus.async_listen("lovelace_updated", events.append)
    assert await dashboards.async_ensure_dashboard(hass, entry) == "collection"
    await hass.async_block_till_done()

    (item,) = _items(hass)
    assert item["title"] == "Kitchen"  # set on creation only
    assert item["show_in_sidebar"] is False
    assert hass.data[DATA_PANELS][URL].show_in_sidebar is False
    # Config unchanged, so it isn't rewritten.
    assert events == []


async def test_user_metadata_is_kept(hass: HomeAssistant) -> None:
    """Title and sidebar edits made in Settings › Dashboards survive setup.

    The sidebar flag follows the option again only once the option changes.
    """
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    coll = dashboards.find_dashboards_collection(hass)
    (item,) = _items(hass)
    await coll.async_update_item(item["id"], {"title": "Wall", "show_in_sidebar": False})

    await dashboards.async_ensure_dashboard(hass, entry)
    (item,) = _items(hass)
    assert (item["title"], item["show_in_sidebar"]) == ("Wall", False)

    hass.config_entries.async_update_entry(entry, options=entry_options(show_in_sidebar=False))
    await dashboards.async_ensure_dashboard(hass, entry)
    await coll.async_update_item(item["id"], {"show_in_sidebar": True})
    hass.config_entries.async_update_entry(entry, options=entry_options(show_in_sidebar=False))
    await dashboards.async_ensure_dashboard(hass, entry)
    (item,) = _items(hass)
    assert item["show_in_sidebar"] is True  # option unchanged since last applied

    hass.config_entries.async_update_entry(entry, options=entry_options(show_in_sidebar=True))
    await dashboards.async_ensure_dashboard(hass, entry)
    hass.config_entries.async_update_entry(entry, options=entry_options(show_in_sidebar=False))
    await dashboards.async_ensure_dashboard(hass, entry)
    (item,) = _items(hass)
    assert (item["title"], item["show_in_sidebar"]) == ("Wall", False)


async def test_applied_sidebar_survives_restart(hass: HomeAssistant, hass_storage: dict) -> None:
    """The last applied sidebar flag is stored, so a restart doesn't re-apply it."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    await hass.async_block_till_done()
    assert hass_storage[dashboards.APPLIED_STORE_KEY]["data"] == {URL: {"show_in_sidebar": True}}

    await dashboards.async_remove_dashboard(hass, entry)
    await hass.async_block_till_done()
    assert hass_storage[dashboards.APPLIED_STORE_KEY]["data"] == {}


async def test_strategy_entry_id_refreshed(hass: HomeAssistant) -> None:
    """A stale entry_id in our own strategy config is replaced."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    await (
        hass.data[LOVELACE_DATA]
        .dashboards[URL]
        .async_save({"strategy": {"type": STRATEGY_TYPE, "entry_id": "old"}})
    )
    await dashboards.async_ensure_dashboard(hass, entry)
    assert (await _stored(hass))["strategy"]["entry_id"] == entry.entry_id


async def test_take_control_is_preserved(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """After "Take control" the user's config is never overwritten."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    taken = {"views": [{"title": "Mine", "cards": []}]}
    await hass.data[LOVELACE_DATA].dashboards[URL].async_save(taken)

    with caplog.at_level(logging.INFO):
        assert await dashboards.async_ensure_dashboard(hass, entry) == "collection"

    assert await _stored(hass) == taken
    assert "taken control" in caplog.text


async def test_take_control_keeps_metadata(hass: HomeAssistant) -> None:
    """A taken-over dashboard's sidebar flag is the user's, whatever the option says."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    await hass.data[LOVELACE_DATA].dashboards[URL].async_save({"views": []})
    hass.config_entries.async_update_entry(entry, options=entry_options(show_in_sidebar=False))
    await dashboards.async_ensure_dashboard(hass, entry)
    (item,) = _items(hass)
    assert item["show_in_sidebar"] is True


async def test_fallback_panel(hass: HomeAssistant) -> None:
    """Without the collection a panel plus injected storage is used."""
    entry = make_entry(hass)
    with patch.object(dashboards, "find_dashboards_collection", return_value=None):
        assert await dashboards.async_ensure_dashboard(hass, entry) == "panel"
        # Idempotent as well.
        assert await dashboards.async_ensure_dashboard(hass, entry) == "panel"

    panel = hass.data[DATA_PANELS][URL]
    assert panel.component_name == "lovelace"
    assert panel.config == {"mode": "storage"}
    assert panel.sidebar_title == "Kitchen"
    assert panel.sidebar_icon == "mdi:tablet-dashboard"
    assert panel.require_admin is False
    assert isinstance(hass.data[LOVELACE_DATA].dashboards[URL], LovelaceStorage)
    assert await _stored(hass) == {"strategy": {"type": STRATEGY_TYPE, "entry_id": entry.entry_id}}


async def test_fallback_take_control_preserved(hass: HomeAssistant) -> None:
    """The fallback path also leaves a taken-over config alone."""
    entry = make_entry(hass)
    with patch.object(dashboards, "find_dashboards_collection", return_value=None):
        await dashboards.async_ensure_dashboard(hass, entry)
        taken = {"views": []}
        await hass.data[LOVELACE_DATA].dashboards[URL].async_save(taken)
        await dashboards.async_ensure_dashboard(hass, entry)
    assert await _stored(hass) == taken


async def test_fallback_does_not_steal_foreign_panel(hass: HomeAssistant) -> None:
    """A panel someone else registered at our url_path is left alone."""
    from homeassistant.components import frontend

    frontend.async_register_built_in_panel(hass, "iframe", frontend_url_path=URL)
    entry = make_entry(hass)
    with patch.object(dashboards, "find_dashboards_collection", return_value=None):
        assert await dashboards.async_ensure_dashboard(hass, entry) == "failed"
    assert hass.data[DATA_PANELS][URL].component_name == "iframe"
    assert URL not in hass.data[LOVELACE_DATA].dashboards


async def test_collection_does_not_steal_foreign_panel(hass: HomeAssistant) -> None:
    """If the collection refuses the url_path, nothing is overwritten."""
    from homeassistant.components import frontend

    frontend.async_register_built_in_panel(hass, "iframe", frontend_url_path=URL)
    entry = make_entry(hass)
    assert await dashboards.async_ensure_dashboard(hass, entry) == "failed"
    assert hass.data[DATA_PANELS][URL].component_name == "iframe"
    assert _items(hass) == []


async def test_fallback_upgraded_to_collection(hass: HomeAssistant) -> None:
    """A fallback panel from earlier is replaced by a collection item."""
    entry = make_entry(hass)
    with patch.object(dashboards, "find_dashboards_collection", return_value=None):
        await dashboards.async_ensure_dashboard(hass, entry)
    assert await dashboards.async_ensure_dashboard(hass, entry) == "collection"
    assert len(_items(hass)) == 1
    assert await _stored(hass) == {"strategy": {"type": STRATEGY_TYPE, "entry_id": entry.entry_id}}


async def test_remove_via_collection(hass: HomeAssistant, hass_storage: dict) -> None:
    """Removing deletes the item, the panel and the stored config."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    await hass.async_block_till_done()

    await dashboards.async_remove_dashboard(hass, entry)
    await hass.async_block_till_done()

    assert _items(hass) == []
    assert URL not in hass.data[DATA_PANELS]
    assert URL not in hass.data[LOVELACE_DATA].dashboards
    assert f"lovelace.{URL}" not in hass_storage


async def test_remove_keeps_taken_over(hass: HomeAssistant) -> None:
    """Removing the entry never deletes a dashboard the user took control of."""
    entry = make_entry(hass)
    await dashboards.async_ensure_dashboard(hass, entry)
    taken = {"views": [{"title": "Mine", "cards": []}]}
    await hass.data[LOVELACE_DATA].dashboards[URL].async_save(taken)

    await dashboards.async_remove_dashboard(hass, entry)
    await hass.async_block_till_done()

    assert len(_items(hass)) == 1
    assert URL in hass.data[DATA_PANELS]
    assert await _stored(hass) == taken


async def test_remove_fallback(hass: HomeAssistant, hass_storage: dict) -> None:
    """Removing a fallback dashboard drops the panel and its storage."""
    entry = make_entry(hass)
    with patch.object(dashboards, "find_dashboards_collection", return_value=None):
        await dashboards.async_ensure_dashboard(hass, entry)
        await dashboards.async_remove_dashboard(hass, entry)
    await hass.async_block_till_done()

    assert URL not in hass.data[DATA_PANELS]
    assert URL not in hass.data[LOVELACE_DATA].dashboards
    assert f"lovelace.{URL}" not in hass_storage


@pytest.mark.parametrize(("config", "kept"), [(None, False), ({"views": []}, True)])
async def test_remove_unknown_dashboard(
    hass: HomeAssistant, hass_storage: dict, config: dict | None, kept: bool
) -> None:
    """Removing a dashboard that isn't loaded drops its storage file, unless taken over."""
    entry = make_entry(hass)
    stored = config or dashboards.strategy_config(entry.entry_id)
    hass_storage[f"lovelace.{URL}"] = {
        "version": 1,
        "key": f"lovelace.{URL}",
        "data": {"config": stored},
    }
    await dashboards.async_remove_dashboard(hass, entry)
    await hass.async_block_till_done()
    assert (f"lovelace.{URL}" in hass_storage) is kept
