"""Websocket commands used by the frontend strategy (see docs/contracts.md)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import entities, generator, layout, repairs
from .const import (
    CONF_IDLE_SECONDS,
    CONF_KIOSK,
    CONF_NAME,
    CONF_PAGES,
    CONF_URL_PATH,
    DEFAULT_IDLE_SECONDS,
    DEFAULT_KIOSK,
    DEFAULT_PAGES,
    DOMAIN,
    PAGE_HOME,
    WS_GENERATE,
    WS_LIST,
    WS_REPORT_VIEWPORT,
)
from .models import DashboardBudget, ViewportReport
from .sensor import signal_viewport

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

ERR_NOT_FOUND = websocket_api.ERR_NOT_FOUND  # "not_found"

# Browsers round and some WebViews lose a pixel or two to borders.
VIEWPORT_TOLERANCE_PX = 4
# Any user can report a viewport: keep it plausible, since an admin may adopt it
# through the repair flow and the strings end up in state attributes.
MAX_VIEWPORT_PX = 8192
MAX_TEXT_LENGTH = 512
_SIZE = probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=MAX_VIEWPORT_PX))
_TEXT = probatio.All(str, probatio.Length(max=MAX_TEXT_LENGTH))


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_generate)
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_report_viewport)


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


def _send_not_found(connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_error(
        msg["id"],
        ERR_NOT_FOUND,
        f"Unknown wall display {msg['entry_id']}",
        translation_key="display_not_found",
        translation_domain=DOMAIN,
        translation_placeholders={"entry_id": msg["entry_id"]},
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): WS_GENERATE,
        probatio.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_generate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Build the dashboard config for one display."""
    if (entry := _get_entry(hass, msg["entry_id"])) is None:
        _send_not_found(connection, msg)
        return
    try:
        display = entities.display_config_from_entry(hass, entry)
        data = entities.collect_input(hass, display)
        dashboard = generator.build_dashboard(data)
    except Exception as err:
        _LOGGER.exception("Could not build the dashboard of %s", entry.title)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="generate_failed",
            translation_placeholders={"name": entry.title},
        ) from err
    connection.send_result(msg["id"], dashboard)


def home_layout(hass: HomeAssistant, entry: ConfigEntry) -> DashboardBudget:
    """Row budget per view, as the generator decided it.

    Returns ``{"rows", "footer", "views": {path: {"rows", "footer"}}}`` from
    ``generator.dashboard_budget``; ``rows``/``footer`` describe Home. The
    dashboard is built once here and handed to it.
    """
    display = entities.display_config_from_entry(hass, entry)
    try:
        data = entities.collect_input(hass, display)
        dashboard = generator.build_dashboard(data)
        budget = generator.dashboard_budget(data, dashboard)
        return {
            "rows": budget["rows"],
            "footer": budget["footer"],
            "views": budget["views"],
        }
    except Exception:
        _LOGGER.exception("Could not build %s; guessing its footer from the options", entry.title)
    footer = bool(entry.options.get(CONF_PAGES, DEFAULT_PAGES))
    rows = layout.compute_grid(display.profile, footer=footer).rows
    return {"rows": rows, "footer": footer, "views": {PAGE_HOME: {"rows": rows, "footer": footer}}}


@websocket_api.websocket_command({probatio.Required("type"): WS_LIST})
@websocket_api.async_response
async def ws_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List all wall displays with their frontend behaviour settings."""
    displays = [
        {
            "entry_id": entry.entry_id,
            "url_path": entry.data.get(CONF_URL_PATH),
            "idle_seconds": int(entry.options.get(CONF_IDLE_SECONDS, DEFAULT_IDLE_SECONDS)),
            "kiosk": entry.options.get(CONF_KIOSK, DEFAULT_KIOSK),
            "home": PAGE_HOME,
            **home_layout(hass, entry),
        }
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], {"displays": displays})


def compare_viewport(width: int, height: int, profile_width: int, profile_height: int) -> bool:
    """Return True if a measured viewport matches the profile size."""
    return (
        abs(width - profile_width) <= VIEWPORT_TOLERANCE_PX
        and abs(height - profile_height) <= VIEWPORT_TOLERANCE_PX
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): WS_REPORT_VIEWPORT,
        probatio.Required("entry_id"): str,
        probatio.Required("width"): _SIZE,
        probatio.Required("height"): _SIZE,
        probatio.Required("dpr"): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0, max=10)
        ),
        probatio.Required("user_agent"): _TEXT,
        probatio.Optional("device"): probatio.Any(_TEXT, None),
    }
)
@websocket_api.async_response
async def ws_report_viewport(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store the viewport a display measured and compare it with its profile."""
    if (entry := _get_entry(hass, msg["entry_id"])) is None:
        _send_not_found(connection, msg)
        return

    profile = entities.display_config_from_entry(hass, entry).profile
    width, height = msg["width"], msg["height"]
    matches = compare_viewport(width, height, profile.width, profile.height)
    result = {
        "profile_width": profile.width,
        "profile_height": profile.height,
        "matches": matches,
    }

    viewport: ViewportReport = {
        "width": width,
        "height": height,
        "dpr": msg["dpr"],
        "user_agent": msg["user_agent"],
        "device": msg.get("device"),
        "profile_width": profile.width,
        "profile_height": profile.height,
        "matches": matches,
    }
    if (data := getattr(entry, "runtime_data", None)) is not None:
        data.viewport = viewport
        async_dispatcher_send(hass, signal_viewport(entry.entry_id))

    if matches:
        repairs.async_delete_viewport_issue(hass, entry.entry_id)
    else:
        _LOGGER.debug(
            "%s reports %sx%s, profile %s is %sx%s",
            entry.title,
            width,
            height,
            profile.id,
            profile.width,
            profile.height,
        )
        repairs.async_create_viewport_issue(
            hass,
            entry.entry_id,
            name=entry.data.get(CONF_NAME) or entry.title,
            profile=f"{profile.name} ({profile.width}×{profile.height})",
            width=width,
            height=height,
        )

    connection.send_result(msg["id"], result)
