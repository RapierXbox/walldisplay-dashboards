"""Diagnostic sensor showing the viewport the display last reported."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_NAME, DOMAIN, VERSION

if TYPE_CHECKING:
    from . import WallDisplayConfigEntry

PARALLEL_UPDATES = 0

VIEWPORT_ATTRIBUTES = (
    "width",
    "height",
    "dpr",
    "user_agent",
    "device",
    "profile_width",
    "profile_height",
    "matches",
)


def signal_viewport(entry_id: str) -> str:
    """Dispatcher signal fired when a viewport report arrives."""
    return f"{DOMAIN}_viewport_{entry_id}"


def format_viewport(viewport: dict[str, Any] | None) -> str | None:
    """Return "WxH@dpr" for a viewport report."""
    if not viewport or viewport.get("width") is None or viewport.get("height") is None:
        return None
    dpr = viewport.get("dpr")
    dpr_text = f"{float(dpr):g}" if dpr is not None else "1"
    return f"{int(viewport['width'])}x{int(viewport['height'])}@{dpr_text}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WallDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the viewport sensor."""
    async_add_entities([ViewportSensor(entry)])


class ViewportSensor(RestoreEntity, SensorEntity):
    """Last viewport reported by the dashboard running on the display."""

    _attr_has_entity_name = True
    _attr_translation_key = "viewport"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:monitor-screenshot"
    _attr_should_poll = False

    def __init__(self, entry: WallDisplayConfigEntry) -> None:
        """Initialise from the config entry."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_viewport"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME) or entry.title,
            manufacturer="Wall Display Dashboards",
            model="Wall display dashboard",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _viewport(self) -> dict[str, Any] | None:
        data = getattr(self._entry, "runtime_data", None)
        return getattr(data, "viewport", None)

    @property
    def native_value(self) -> str | None:
        """Return "WxH@dpr"."""
        return format_viewport(self._viewport)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw report and the comparison with the profile."""
        viewport = self._viewport or {}
        return {key: viewport.get(key) for key in VIEWPORT_ATTRIBUTES}

    async def async_added_to_hass(self) -> None:
        """Restore the last report and listen for new ones."""
        await super().async_added_to_hass()
        data = getattr(self._entry, "runtime_data", None)
        if data is not None and data.viewport is None:
            last = await self.async_get_last_state()
            if last is not None and last.attributes.get("width") is not None:
                data.viewport = {key: last.attributes.get(key) for key in VIEWPORT_ATTRIBUTES}
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_viewport(self._entry.entry_id), self._handle_report
            )
        )

    @callback
    def _handle_report(self) -> None:
        self.async_write_ha_state()
