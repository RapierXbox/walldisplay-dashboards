"""Fake sensors (temperature, humidity, ...)."""

from homeassistant.components.sensor import SensorEntity, SensorStateClass

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeSensor(i) for i in items_for(hass, "sensor"))


class FakeSensor(FakeEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, item):
        super().__init__(item)
        self._attr_native_value = float(item.get("state", 0))
        self._attr_native_unit_of_measurement = self._attrs.get("unit_of_measurement")
