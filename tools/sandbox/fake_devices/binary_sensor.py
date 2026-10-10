"""Fake binary sensors (doors, windows, motion)."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeBinarySensor(i) for i in items_for(hass, "binary_sensor"))


class FakeBinarySensor(FakeEntity, BinarySensorEntity):
    def __init__(self, item):
        super().__init__(item)
        self._attr_is_on = item.get("state", "off") == "on"
