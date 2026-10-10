"""Fake thermostats (heat/off, target temperature)."""

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeClimate(i) for i in items_for(hass, "climate"))


class FakeClimate(FakeEntity, ClimateEntity):
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, item):
        super().__init__(item)
        self._attr_hvac_mode = HVACMode(item.get("state", "heat"))
        self._attr_current_temperature = self._attrs.get("current_temperature", 20.5)
        self._attr_target_temperature = self._attrs.get("temperature", 21)

    async def async_set_temperature(self, **kwargs):
        self._attr_target_temperature = kwargs.get(ATTR_TEMPERATURE, self._attr_target_temperature)
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
