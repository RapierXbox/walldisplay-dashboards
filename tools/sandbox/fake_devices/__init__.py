"""Test-only integration for the sandbox: registry-backed fake entities with areas.

POSTed states (/api/states) have no entity registry entry, so they cannot be
assigned to an area. This component reads /config/fake_devices.json and creates
real entities (with unique ids) for the platforms below, then assigns each one
to the area named in the JSON (the area is created if it does not exist).

configuration.yaml:
    fake_devices:

JSON format:
    {"entities": [{"entity_id": "light.kitchen_ceiling", "name": "Ceiling",
                   "area": "Kitchen", "state": "on", "attributes": {...}}]}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity

DOMAIN = "fake_devices"
PLATFORMS = (
    Platform.LIGHT,
    Platform.COVER,
    Platform.CLIMATE,
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.WEATHER,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
)
_LOGGER = logging.getLogger(__name__)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        _LOGGER.warning("%s not found, no fake entities created", path)
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("entities", [])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Load the JSON and set up one platform per domain."""
    items = await hass.async_add_executor_job(
        _load, Path(hass.config.path("fake_devices.json"))
    )
    by_domain: dict[str, list[dict]] = {}
    for item in items:
        by_domain.setdefault(item["entity_id"].split(".", 1)[0], []).append(item)
    hass.data[DOMAIN] = by_domain
    for platform in PLATFORMS:
        if by_domain.get(platform.value):
            hass.async_create_task(
                async_load_platform(hass, platform, DOMAIN, {}, config)
            )
    return True


class FakeEntity(Entity):
    """Common base: unique id from the JSON entity id, area assigned once added."""

    _attr_should_poll = False

    def __init__(self, item: dict) -> None:
        self._item = item
        self._attrs = dict(item.get("attributes", {}))
        self.entity_id = item["entity_id"]
        self._attr_unique_id = f"fake_{item['entity_id']}"
        self._attr_name = item.get("name") or self._attrs.get("friendly_name")
        self._attr_icon = self._attrs.get("icon")
        self._attr_device_class = self._attrs.get("device_class")

    async def async_added_to_hass(self) -> None:
        area = self._item.get("area")
        if not area or not self.registry_entry:
            return
        area_entry = ar.async_get(self.hass).async_get_or_create(area)
        if self.registry_entry.area_id != area_entry.id:
            er.async_get(self.hass).async_update_entity(
                self.entity_id, area_id=area_entry.id
            )


def items_for(hass: HomeAssistant, domain: str) -> list[dict]:
    return hass.data.get(DOMAIN, {}).get(domain, [])
