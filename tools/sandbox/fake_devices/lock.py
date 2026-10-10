"""Fake locks."""

from homeassistant.components.lock import LockEntity

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeLock(i) for i in items_for(hass, "lock"))


class FakeLock(FakeEntity, LockEntity):
    def __init__(self, item):
        super().__init__(item)
        self._attr_is_locked = item.get("state", "locked") == "locked"

    async def async_lock(self, **kwargs):
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs):
        self._attr_is_locked = False
        self.async_write_ha_state()
