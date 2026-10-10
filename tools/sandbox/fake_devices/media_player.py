"""Fake media players (transport + volume)."""

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature as F,
    MediaPlayerState,
    MediaType,
)

from . import FakeEntity, items_for


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities(FakePlayer(i) for i in items_for(hass, "media_player"))


class FakePlayer(FakeEntity, MediaPlayerEntity):
    _attr_supported_features = (
        F.PLAY | F.PAUSE | F.STOP | F.NEXT_TRACK | F.PREVIOUS_TRACK
        | F.VOLUME_SET | F.VOLUME_MUTE | F.TURN_ON | F.TURN_OFF
    )
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, item):
        super().__init__(item)
        self._attr_state = MediaPlayerState(item.get("state", "paused"))
        self._attr_volume_level = self._attrs.get("volume_level", 0.3)
        self._attr_is_volume_muted = False
        self._attr_media_title = self._attrs.get("media_title", "Track title")
        self._attr_media_artist = self._attrs.get("media_artist", "Artist")

    def _st(self, state):
        self._attr_state = state
        self.async_write_ha_state()

    async def async_media_play(self):
        self._st(MediaPlayerState.PLAYING)

    async def async_media_pause(self):
        self._st(MediaPlayerState.PAUSED)

    async def async_media_stop(self):
        self._st(MediaPlayerState.IDLE)

    async def async_turn_on(self):
        self._st(MediaPlayerState.IDLE)

    async def async_turn_off(self):
        self._st(MediaPlayerState.OFF)

    async def async_media_next_track(self):
        self.async_write_ha_state()

    async def async_media_previous_track(self):
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute):
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()
