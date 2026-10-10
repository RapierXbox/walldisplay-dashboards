"""Repair issues: a display reporting a different viewport size, and an empty room."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import CONF_HEIGHT, CONF_NAME, CONF_WIDTH, DOMAIN

ISSUE_VIEWPORT_MISMATCH = "viewport_mismatch"
ISSUE_EMPTY_ROOM = "empty_room"


def issue_id(entry_id: str) -> str:
    """Issue id for one entry."""
    return f"{ISSUE_VIEWPORT_MISMATCH}_{entry_id}"


@callback
def async_create_viewport_issue(
    hass: HomeAssistant,
    entry_id: str,
    *,
    name: str,
    profile: str,
    width: int,
    height: int,
) -> None:
    """Create (or refresh) the viewport mismatch issue for an entry."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry_id),
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_VIEWPORT_MISMATCH,
        translation_placeholders={
            "name": name,
            "profile": profile,
            "measured": f"{width}×{height}",
        },
        data={"entry_id": entry_id, "width": width, "height": height},
    )


@callback
def async_delete_viewport_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the issue for an entry if it exists."""
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry_id))


def empty_room_issue_id(entry_id: str) -> str:
    """Empty-room issue id for one entry."""
    return f"{ISSUE_EMPTY_ROOM}_{entry_id}"


@callback
def async_update_empty_room_issue(
    hass: HomeAssistant, entry_id: str, *, empty: bool, name: str, area: str
) -> None:
    """Tell the admin (not the guests on the display) that the room has nothing to show (U18)."""
    if not empty:
        async_delete_empty_room_issue(hass, entry_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        empty_room_issue_id(entry_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_EMPTY_ROOM,
        translation_placeholders={"name": name, "area": area},
    )


@callback
def async_delete_empty_room_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the empty-room issue for an entry if it exists."""
    ir.async_delete_issue(hass, DOMAIN, empty_room_issue_id(entry_id))


class ViewportMismatchRepairFlow(RepairsFlow):
    """Adopt the measured viewport size for the display."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Store the measured size."""
        self._data = data

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        """Start the flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Write the measured width/height into the entry and reload it."""
        entry = self.hass.config_entries.async_get_entry(self._data["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_WIDTH: int(self._data["width"]),
                    CONF_HEIGHT: int(self._data["height"]),
                },
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_create_entry(data={})

        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
        placeholders = (issue.translation_placeholders if issue else None) or {
            "name": entry.data.get(CONF_NAME, entry.title),
            "profile": "",
            "measured": f"{self._data['width']}×{self._data['height']}",
        }
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({}),
            description_placeholders=placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create a fix flow for our issues."""
    return ViewportMismatchRepairFlow(dict(data or {}))
