"""Fake scenes (activation is a no-op)."""

from homeassistant.components.scene import Scene

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakeScene(i) for i in items_for(hass, "scene"))


class FakeScene(FakeEntity, Scene):
    async def async_activate(self, **kwargs):
        return
