"""Fake lights (on/off + brightness)."""

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeLight(i) for i in items_for(hass, "light"))


class FakeLight(FakeEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, item):
        super().__init__(item)
        self._attr_is_on = item.get("state", "off") == "on"
        self._attr_brightness = self._attrs.get("brightness", 200)

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self._attr_brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()
