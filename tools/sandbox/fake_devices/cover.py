"""Fake covers with position."""

from homeassistant.components.cover import ATTR_POSITION, CoverEntity, CoverEntityFeature

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeCover(i) for i in items_for(hass, "cover"))


class FakeCover(FakeEntity, CoverEntity):
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, item):
        super().__init__(item)
        default = 100 if item.get("state") == "open" else 0
        self._attr_current_cover_position = self._attrs.get("current_position", default)

    @property
    def is_closed(self):
        return self._attr_current_cover_position == 0

    def _set(self, pos):
        self._attr_current_cover_position = pos
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs):
        self._set(100)

    async def async_close_cover(self, **kwargs):
        self._set(0)

    async def async_stop_cover(self, **kwargs):
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs):
        self._set(kwargs[ATTR_POSITION])
