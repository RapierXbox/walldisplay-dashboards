"""Fake switches."""

from homeassistant.components.switch import SwitchEntity

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeSwitch(i) for i in items_for(hass, "switch"))


class FakeSwitch(FakeEntity, SwitchEntity):
    def __init__(self, item):
        super().__init__(item)
        self._attr_is_on = item.get("state", "off") == "on"

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()
