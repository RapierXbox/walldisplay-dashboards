"""Diagnostics: what the integration resolved and generated for one display.

Covers the entry, the resolved profile, the last viewport report, the
dashboard mode and the generated layout (view paths, card counts, row
budget). Entity states are left out; the display host is redacted.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import entities, generator
from .const import CONF_DISPLAY_HOST

if TYPE_CHECKING:
    from . import WallDisplayConfigEntry

_LOGGER = logging.getLogger(__name__)

TO_REDACT = {CONF_DISPLAY_HOST}


def _view_summary(view: dict[str, Any]) -> dict[str, Any]:
    sections = view.get("sections") or []
    return {
        "path": view.get("path"),
        "footer": "footer" in view,
        "sections": len(sections),
        "cards": sum(len(section.get("cards") or []) for section in sections),
    }


def _generated(hass: HomeAssistant, entry: WallDisplayConfigEntry) -> dict[str, Any]:
    """Profile, row budget and view summary; the error instead if building fails."""
    display = entities.display_config_from_entry(hass, entry)
    profile = {**asdict(display.profile), "orientation": display.profile.orientation}
    try:
        data = entities.collect_input(hass, display)
        dashboard = generator.build_dashboard(data)
        budget = generator.dashboard_budget(data, dashboard)
    except Exception as err:
        _LOGGER.exception("Could not build %s for diagnostics", entry.title)
        return {"profile": profile, "error": f"{type(err).__name__}: {err}"}
    return {
        "profile": profile,
        "area_name": data.area_name,
        "role": data.role,
        "language": data.language,
        "budget": budget,
        "views": [_view_summary(view) for view in dashboard["views"]],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WallDisplayConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "dashboard_mode": getattr(runtime, "dashboard_mode", None),
        "push_method": getattr(runtime, "push_method", None),
        "viewport": getattr(runtime, "viewport", None),
        **_generated(hass, entry),
    }
