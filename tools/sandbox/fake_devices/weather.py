"""Fake weather entities. With attributes.forecast = true they also provide a daily forecast."""

from datetime import timedelta

from homeassistant.components.weather import Forecast, WeatherEntity, WeatherEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.util import dt as dt_util

from . import FakeEntity, items_for

CONDITIONS = ("sunny", "partlycloudy", "rainy", "cloudy", "sunny", "pouring", "partlycloudy")


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeWeather(i) for i in items_for(hass, "weather"))


class FakeWeather(FakeEntity, WeatherEntity):
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, item):
        super().__init__(item)
        self._attr_condition = item.get("state", "sunny")
        self._attr_native_temperature = self._attrs.get("temperature", 14)
        self._attr_humidity = self._attrs.get("humidity", 60)
        if self._attrs.get("forecast"):
            self._attr_supported_features = WeatherEntityFeature.FORECAST_DAILY

    async def async_forecast_daily(self) -> list[Forecast] | None:
        start = dt_util.start_of_local_day()
        base = float(self._attr_native_temperature)
        return [
            Forecast(
                datetime=(start + timedelta(days=i)).isoformat(),
                condition=CONDITIONS[i % len(CONDITIONS)],
                native_temperature=round(base + 3 - (i % 3), 1),
                native_templow=round(base - 5 + (i % 2), 1),
                precipitation_probability=(i * 15) % 90,
            )
            for i in range(7)
        ]
