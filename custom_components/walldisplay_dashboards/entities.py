"""Read the entry and the registries into the generator's input model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_FRIENDLY_NAME, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant, State, split_entity_id
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr

from .const import (
    CONF_AREA_ID,
    CONF_CLIMATE_ENTITIES,
    CONF_DISPLAY_DEVICE_ID,
    CONF_HEIGHT,
    CONF_HIDDEN,
    CONF_HUMIDITY_ENTITY,
    CONF_IDLE_SECONDS,
    CONF_INCLUDE_DISPLAY_ENTITIES,
    CONF_KIOSK,
    CONF_MAX_HOME_TILES,
    CONF_NAME,
    CONF_PAGES,
    CONF_PINNED,
    CONF_PROFILE,
    CONF_ROLE,
    CONF_SCENE_BUTTONS,
    CONF_TEMPERATURE_ENTITY,
    CONF_URL_PATH,
    CONF_WEATHER_ENTITY,
    CONF_WIDTH,
    DEFAULT_IDLE_SECONDS,
    DEFAULT_KIOSK,
    DEFAULT_PAGES,
    DEFAULT_ROLE,
    MAX_HOME_TILES_LIMIT,
    OPTIONAL_PAGES,
    ROLE_ENTRANCE,
    ROLES,
    SECURE_DOMAINS,
    TILE_DOMAIN_RANK,
    URL_PREFIX,
)
from .display_link import find_display_sensors
from .generator.home import rank_entities
from .generator.info import ClimateInfo, LightInfo
from .generator.room import natural_key
from .models import DisplayConfig, EntityInfo, GeneratorInput, Overrides
from .names import clean_name
from .profiles import DEFAULT_PROFILE, resolve_profile

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

MAX_SCENE_BUTTONS = 2
OPENING_CLASSES = ("door", "window", "garage_door", "opening")
# Leave-home actions for the entrance role, matched on entity id or name.
ALL_OFF_NAMES = frozenset({"all off", "all_off", "alles aus", "alles_aus"})


def _str_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def _entity_option(value: Any) -> str | None:
    """A single entity id option; anything else (cleared, malformed) is unset."""
    return value if isinstance(value, str) and value else None


def _tile_limit(value: Any) -> int:
    """max_home_tiles: 0 (automatic) up to MAX_HOME_TILES_LIMIT."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(MAX_HOME_TILES_LIMIT, int(value)))


def _device_area(hass: HomeAssistant, device_id: str | None) -> str | None:
    """Area of the display device: the default when the entry names none."""
    if not device_id or (device := dr.async_get(hass).async_get(device_id)) is None:
        return None
    return device.area_id


def _role(hass: HomeAssistant, entry_id: str) -> str:
    entry = hass.config_entries.async_get_entry(entry_id)
    role = entry.options.get(CONF_ROLE, DEFAULT_ROLE) if entry else DEFAULT_ROLE
    return role if role in ROLES else DEFAULT_ROLE


def _default_weather(hass: HomeAssistant) -> str | None:
    weather = sorted(hass.states.async_entity_ids("weather"))
    return weather[0] if weather else None


def display_config_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> DisplayConfig:
    """Resolve entry data and options into a DisplayConfig."""
    data, options = entry.data, entry.options
    profile = resolve_profile(
        data.get(CONF_PROFILE, DEFAULT_PROFILE), data.get(CONF_WIDTH), data.get(CONF_HEIGHT)
    )
    pages: list[str] = []
    for page in _str_list(options.get(CONF_PAGES, DEFAULT_PAGES)):
        if page in OPTIONAL_PAGES and page not in pages:
            pages.append(page)
    temperature, humidity = find_display_sensors(hass, data.get(CONF_DISPLAY_DEVICE_ID))
    name = data.get(CONF_NAME) or entry.title
    area_id = data.get(CONF_AREA_ID) or _device_area(hass, data.get(CONF_DISPLAY_DEVICE_ID))
    return DisplayConfig(
        entry_id=entry.entry_id,
        name=name,
        url_path=data.get(CONF_URL_PATH) or f"{URL_PREFIX}{entry.entry_id}",
        area_id=area_id,
        profile=profile,
        pages=tuple(pages),
        weather_entity=data.get(CONF_WEATHER_ENTITY) or _default_weather(hass),
        indoor_temperature=temperature,
        indoor_humidity=humidity,
        idle_seconds=int(options.get(CONF_IDLE_SECONDS, DEFAULT_IDLE_SECONDS)),
        kiosk=options.get(CONF_KIOSK, DEFAULT_KIOSK),
        overrides=Overrides(
            pinned=_str_list(options.get(CONF_PINNED)),
            hidden=_str_list(options.get(CONF_HIDDEN)),
            scene_buttons=_str_list(options.get(CONF_SCENE_BUTTONS))[:MAX_SCENE_BUTTONS],
            climate_entities=_str_list(options.get(CONF_CLIMATE_ENTITIES)),
            temperature_entity=_entity_option(options.get(CONF_TEMPERATURE_ENTITY)),
            humidity_entity=_entity_option(options.get(CONF_HUMIDITY_ENTITY)),
            max_home_tiles=_tile_limit(options.get(CONF_MAX_HOME_TILES)),
            include_display_entities=bool(options.get(CONF_INCLUDE_DISPLAY_ENTITIES, False)),
        ),
        display_device_id=data.get(CONF_DISPLAY_DEVICE_ID) or None,
    )


class _Lookup:
    """Registry views shared by one collect_input() call."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entities = er.async_get(hass)
        self.devices = dr.async_get(hass)
        areas = ar.async_get(hass).async_list_areas()
        floors = fr.async_get(hass)
        self.area_names = {area.id: area.name for area in areas}
        self.floor_names = {
            area.id: floor.name
            for area in areas
            if area.floor_id and (floor := floors.async_get_floor(area.floor_id)) is not None
        }

    def area_of(self, entry: er.RegistryEntry | None) -> str | None:
        """Entity's own area, else its device's area."""
        if entry is None:
            return None
        if entry.area_id:
            return entry.area_id
        if entry.device_id and (device := self.devices.async_get(entry.device_id)):
            return device.area_id
        return None

    def visible(self, entity_id: str) -> tuple[er.RegistryEntry | None, State] | None:
        """(registry entry, state) for an entity a dashboard may show, else None."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        entry = self.entities.async_get(entity_id)
        if entry is not None and (
            entry.entity_category is not None
            or entry.hidden_by is not None
            or entry.disabled_by is not None
        ):
            return None
        return entry, state

    def info(self, entity_id: str) -> EntityInfo | None:
        found = self.visible(entity_id)
        if found is None:
            return None
        entry, state = found
        area_id = self.area_of(entry)
        raw = (
            (entry.name or entry.original_name if entry else None)
            or state.attributes.get(ATTR_FRIENDLY_NAME)
            or split_entity_id(entity_id)[1].replace("_", " ").capitalize()
        )
        device_class = (
            entry.device_class or entry.original_device_class if entry else None
        ) or state.attributes.get(ATTR_DEVICE_CLASS)
        features = state.attributes.get(ATTR_SUPPORTED_FEATURES)
        if not isinstance(features, int):
            features = entry.supported_features if entry else 0
        fields: dict[str, Any] = {
            "entity_id": entity_id,
            # The room and floor are on the dashboard already: "Licht Ben OG" -> "Licht".
            "name": clean_name(
                str(raw),
                self.area_names.get(area_id or ""),
                self.floor_names.get(area_id or ""),
            ),
            "area_id": area_id,
            "device_class": str(device_class) if device_class else None,
            "supported_features": features or 0,
            "icon": (entry.icon or entry.original_icon if entry else None)
            or state.attributes.get("icon"),
            "device_id": entry.device_id if entry else None,
        }
        if state.domain == "climate":
            return ClimateInfo(
                **fields,
                hvac_modes=_str_list(state.attributes.get("hvac_modes")),
                preset_modes=_str_list(state.attributes.get("preset_modes")),
            )
        if state.domain == "light":
            modes = set(_str_list(state.attributes.get("supported_color_modes")))
            return LightInfo(**fields, dimmable=bool(modes - {"onoff"}))
        return EntityInfo(**fields)


def collect_input(hass: HomeAssistant, display: DisplayConfig) -> GeneratorInput:
    """Gather everything build_dashboard() needs for one display.

    Pages are room-scoped, so climates, media players, scenes and sensors are
    the display's area only (the generator filters by area again). Pinned
    entities and the climate entities of the options come from any room. The
    entrance role adds house-wide people, counts, locks/alarms and leave-home
    actions.
    """
    lookup = _Lookup(hass)
    area_id = display.area_id
    hidden = set(display.overrides.hidden)
    role = _role(hass, display.entry_id)

    def visible(*domains: str) -> list[EntityInfo]:
        found = []
        for entity_id in sorted(hass.states.async_entity_ids(domains)):
            info = lookup.info(entity_id)
            if info is not None and entity_id not in hidden:
                found.append(info)
        return found

    def in_area(*domains: str) -> list[EntityInfo]:
        if not area_id:
            return []
        return [e for e in visible(*domains) if e.area_id == area_id]

    area_entities = in_area(*dict.fromkeys((*TILE_DOMAIN_RANK, *SECURE_DOMAINS)))
    known = {e.entity_id for e in area_entities}
    for entity_id in display.overrides.pinned:
        if entity_id not in known and (info := lookup.info(entity_id)) is not None:
            area_entities.append(info)
            known.add(entity_id)

    def by_name(entities: list[EntityInfo]) -> tuple[EntityInfo, ...]:
        return tuple(sorted(entities, key=lambda e: (natural_key(e.name), e.entity_id)))

    climates = in_area("climate")
    chosen = [e for e in display.overrides.climate_entities if e.startswith("climate.")]
    for entity_id in dict.fromkeys(chosen).keys() - {e.entity_id for e in climates}:
        if (info := lookup.info(entity_id)) is not None:
            climates.append(info)

    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    sensors = [e for e in in_area("sensor") if e.device_class in ("temperature", "humidity")]
    weather = hass.states.get(display.weather_entity) if display.weather_entity else None
    weather_features = weather.attributes.get(ATTR_SUPPORTED_FEATURES, 0) if weather else 0
    entrance: dict[str, Any] = {}
    if role == ROLE_ENTRANCE:
        actions = [
            e
            for e in visible("script", "scene")
            if e.name.casefold() in ALL_OFF_NAMES
            or e.entity_id.split(".", 1)[1].casefold() in ALL_OFF_NAMES
        ]
        entrance = {
            "persons": by_name(visible("person")),
            "house_lights": tuple(e.entity_id for e in visible("light")),
            "openings": tuple(
                e.entity_id for e in visible("binary_sensor") if e.device_class in OPENING_CLASSES
            ),
            "house_secure": by_name(visible("lock", "alarm_control_panel")),
            "leave_home": by_name(actions),
        }
    return GeneratorInput(
        display=display,
        area_name=lookup.area_names.get(area_id or "", display.name),
        area_entities=tuple(rank_entities(area_entities, display.overrides)),
        climates=by_name(climates),
        media_players=by_name(in_area("media_player")),
        scenes=by_name(in_area("scene", "script")),
        area_names=lookup.area_names,
        area_sensors=by_name(sensors),
        language=hass.config.language or "en",
        role=role,
        area_temperature=getattr(area, "temperature_entity_id", None),
        area_humidity=getattr(area, "humidity_entity_id", None),
        house_scenes=by_name([e for e in visible("scene") if e.area_id is None]),
        weather_features=weather_features if isinstance(weather_features, int) else 0,
        **entrance,
    )
