"""A realistic sample house for previews and golden tests.

The default display hangs in the Kitchen. `sample_input(profile)` returns the
GeneratorInput that entities.collect_input() would build for it;
`entrance_input` is a Hallway display with the entrance role and `empty_input`
a guest room with one lamp. `STATES` holds mock Home Assistant states for
every entity used.

Works without Home Assistant installed: when `homeassistant` can't be
imported, the integration package is registered by path without running its
`__init__.py` (the generator, layout, profiles and models modules are pure).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "custom_components.walldisplay_dashboards"


def ensure_package() -> None:
    """Make `custom_components.walldisplay_dashboards` importable."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if PACKAGE in sys.modules or importlib.util.find_spec("homeassistant") is not None:
        return
    namespace = types.ModuleType("custom_components")
    namespace.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "custom_components" / "walldisplay_dashboards")]
    package.__package__ = PACKAGE
    sys.modules.setdefault("custom_components", namespace)
    sys.modules[PACKAGE] = package


ensure_package()
models = importlib.import_module(f"{PACKAGE}.models")
profiles = importlib.import_module(f"{PACKAGE}.profiles")
info = importlib.import_module(f"{PACKAGE}.generator.info")
ClimateInfo = info.ClimateInfo
LightInfo = info.LightInfo

DisplayConfig = models.DisplayConfig
EntityInfo = models.EntityInfo
GeneratorInput = models.GeneratorInput
Overrides = models.Overrides
Profile = models.Profile

KITCHEN = "kitchen"
HALLWAY = "hallway"
GUEST_ROOM = "guest_room"
AREA_NAMES = {
    "kitchen": "Kitchen",
    "living_room": "Living Room",
    "bedroom": "Bedroom",
    "bathroom": "Bathroom",
    "dining_room": "Dining Room",
    "hallway": "Hallway",
    "guest_room": "Guest Room",
}

# Feature bits as Home Assistant reports them.
COVER_OPEN_CLOSE_STOP_POSITION = 1 | 2 | 4 | 8
COVER_OPEN_CLOSE_STOP = 1 | 2 | 8
CLIMATE_TARGET_TEMP_PRESET_ONOFF = 1 | 16 | 128 | 256
MEDIA_SPEAKER = 1 | 4 | 8 | 16 | 32 | 128 | 256 | 1024 | 4096 | 16384
MEDIA_RADIO = 1 | 4 | 128 | 256 | 2048 | 4096 | 16384
LOCK_OPEN = 1
ALARM_HOME_AWAY_NIGHT = 1 | 2 | 4

# --- Kitchen (the default display) ------------------------------------------
HEATING = ClimateInfo(
    "climate.kitchen_heating",
    "Heating",
    KITCHEN,
    None,
    CLIMATE_TARGET_TEMP_PRESET_ONOFF,
    hvac_modes=("off", "heat", "auto"),
    preset_modes=("comfort", "eco", "away", "boost"),
)
SPEAKER = EntityInfo("media_player.kitchen_speaker", "Speaker", KITCHEN, "speaker", MEDIA_SPEAKER)
RADIO = EntityInfo("media_player.kitchen_radio", "Radio", KITCHEN, "speaker", MEDIA_RADIO)
# UI scenes without their own icon: the generator picks one from the name.
COOKING = EntityInfo("scene.kitchen_cooking", "Cooking", KITCHEN)
BREAKFAST = EntityInfo("scene.kitchen_breakfast", "Breakfast", KITCHEN)

# Ranked as collect_input() returns them (TILE_DOMAIN_RANK, then name).
AREA_ENTITIES = (
    LightInfo("light.kitchen_ceiling", "Ceiling", KITCHEN, dimmable=True),
    LightInfo("light.kitchen_counter", "Counter", KITCHEN, dimmable=True),
    EntityInfo("cover.kitchen_blinds", "Blinds", KITCHEN, "blind", COVER_OPEN_CLOSE_STOP_POSITION),
    HEATING,
    RADIO,
    SPEAKER,
    EntityInfo("switch.kitchen_coffee", "Coffee machine", KITCHEN, "outlet", 0),
    BREAKFAST,
    COOKING,
)

# Pages are room-scoped: collect_input() passes the display's area only, by name.
CLIMATES = (HEATING,)
MEDIA_PLAYERS = (RADIO, SPEAKER)
SCENES = (BREAKFAST, COOKING)

# --- House-wide --------------------------------------------------------------
AWAY = EntityInfo("scene.away", "Away", None, icon="mdi:home-export-outline")
GOOD_NIGHT = EntityInfo("scene.good_night", "Good night", None, icon="mdi:weather-night")
ALL_OFF = EntityInfo("script.all_off", "All off", None, icon="mdi:power")
# A scene with the same name as the script: the entrance shows only the script.
ALL_OFF_SCENE = EntityInfo("scene.all_off", "All off", None, icon="mdi:power-plug-off")
HOUSE_SCENES = (ALL_OFF_SCENE, AWAY, GOOD_NIGHT)  # area-less scenes, by name
PERSONS = (EntityInfo("person.anna", "Anna"), EntityInfo("person.ben", "Ben"))
FRONT_DOOR_LOCK = EntityInfo("lock.front_door", "Front door", "hallway", None, LOCK_OPEN)
ALARM = EntityInfo("alarm_control_panel.home_alarm", "Alarm", None, None, ALARM_HOME_AWAY_NIGHT)
HOUSE_SECURE = (ALARM, FRONT_DOOR_LOCK)
OPENINGS = (
    "binary_sensor.front_door",
    "binary_sensor.garage_door",
    "binary_sensor.bathroom_window",
    "binary_sensor.living_room_window",
)

# --- Hallway (entrance display) ----------------------------------------------
HALLWAY_ENTITIES = (
    LightInfo("light.hallway_ceiling", "Ceiling", HALLWAY, dimmable=False),
    EntityInfo("cover.garage_door", "Garage door", HALLWAY, "garage", COVER_OPEN_CLOSE_STOP),
    FRONT_DOOR_LOCK,
)

# --- Guest room (nearly empty) -----------------------------------------------
GUEST_ENTITIES = (LightInfo("light.guest_room_lamp", "Lamp", GUEST_ROOM, dimmable=True),)

HOUSE_LIGHTS = tuple(
    e.entity_id for e in (*AREA_ENTITIES, *HALLWAY_ENTITIES, *GUEST_ENTITIES) if e.domain == "light"
)

WEATHER = "weather.forecast_home"
WEATHER_FEATURES = 1 | 2  # daily and hourly forecasts (met.no)
INDOOR_TEMPERATURE = "sensor.kitchen_display_temperature"
INDOOR_HUMIDITY = "sensor.kitchen_display_humidity"


def sample_display(profile: Any, **changes: Any) -> Any:
    """DisplayConfig for the kitchen display with the given profile."""
    config: dict[str, Any] = {
        "entry_id": "sample_kitchen",
        "name": "Kitchen",
        "url_path": "wall-kitchen",
        "area_id": KITCHEN,
        "profile": profile,
        "pages": ("climate", "media", "scenes"),
        "weather_entity": WEATHER,
        "indoor_temperature": INDOOR_TEMPERATURE,
        "indoor_humidity": INDOOR_HUMIDITY,
        "idle_seconds": 60,
        "kiosk": "builtin",
        # The speaker is pinned so it is the Media page's main player.
        "overrides": Overrides(pinned=(SPEAKER.entity_id,)),
    }
    config.update(changes)
    return DisplayConfig(**config)


def _default_profile(profile: Any | None) -> Any:
    return profile if profile is not None else profiles.PROFILES["shelly_wall_display"]


def sample_input(
    profile: Any | None = None,
    *,
    language: str = "en",
    weather_features: int | None = None,
    extra_entities: tuple[Any, ...] = (),
) -> Any:
    """GeneratorInput for the kitchen display (default: Shelly Wall Display)."""
    return GeneratorInput(
        display=sample_display(_default_profile(profile)),
        area_name=AREA_NAMES[KITCHEN],
        area_entities=AREA_ENTITIES + extra_entities,
        climates=CLIMATES,
        media_players=MEDIA_PLAYERS,
        scenes=SCENES,
        area_names=dict(AREA_NAMES),
        language=language,
        house_scenes=HOUSE_SCENES,
        weather_features=WEATHER_FEATURES if weather_features is None else weather_features,
    )


# A busy kitchen: 14 more lamps than fit, so Home overflows into the More view.
BUSY_LAMPS = tuple(
    LightInfo(f"light.kitchen_lamp_{i:02}", f"Lamp {i}", KITCHEN, dimmable=True)
    for i in range(1, 15)
)


def busy_input(profile: Any | None = None, *, language: str = "en") -> Any:
    return sample_input(profile, language=language, extra_entities=BUSY_LAMPS)


def entrance_input(profile: Any | None = None, *, language: str = "en") -> Any:
    """GeneratorInput for a Hallway display with the entrance role."""
    display = sample_display(
        _default_profile(profile),
        entry_id="sample_hallway",
        name="Hallway",
        url_path="wall-hallway",
        area_id=HALLWAY,
        indoor_temperature=None,
        indoor_humidity=None,
        overrides=Overrides(),
    )
    return GeneratorInput(
        display=display,
        area_name=AREA_NAMES[HALLWAY],
        area_entities=HALLWAY_ENTITIES,
        climates=(),
        media_players=(),
        scenes=(),
        area_names=dict(AREA_NAMES),
        language=language,
        role="entrance",
        weather_features=WEATHER_FEATURES,
        house_scenes=HOUSE_SCENES,
        persons=PERSONS,
        house_lights=HOUSE_LIGHTS,
        openings=OPENINGS,
        house_secure=HOUSE_SECURE,
        leave_home=(ALL_OFF,),
    )


def empty_input(profile: Any | None = None, *, language: str = "en") -> Any:
    """GeneratorInput for a guest room with a single lamp."""
    display = sample_display(
        _default_profile(profile),
        entry_id="sample_guest_room",
        name="Guest Room",
        url_path="wall-guest-room",
        area_id=GUEST_ROOM,
        indoor_temperature=None,
        indoor_humidity=None,
        overrides=Overrides(),
    )
    return GeneratorInput(
        display=display,
        area_name=AREA_NAMES[GUEST_ROOM],
        area_entities=GUEST_ENTITIES,
        climates=(),
        media_players=(),
        scenes=(),
        area_names=dict(AREA_NAMES),
        language=language,
        weather_features=WEATHER_FEATURES,
    )


# Sample variants: name -> (input builder, keyword arguments).
VARIANTS = {
    "entrance": (entrance_input, {}),
    "de": (sample_input, {"language": "de"}),
    "empty": (empty_input, {}),
    "noforecast": (sample_input, {"weather_features": 0}),  # weather without forecasts
    "busy": (busy_input, {}),
}
# Extra goldens: <profile>@<variant>.json
GOLDEN_VARIANTS = (
    ("shelly_wall_display", "entrance"),
    ("shelly_x2_landscape", "de"),
    ("shelly_wall_display", "empty"),
    ("shelly_x2_portrait", "noforecast"),
    ("shelly_xl", "noforecast"),
    ("tablet_landscape", "noforecast"),
    ("tablet_portrait", "noforecast"),
    ("shelly_wall_display", "busy"),
    ("shelly_x2_landscape", "busy"),
)


def _state(state: str, **attributes: Any) -> dict[str, Any]:
    return {"state": state, "attributes": attributes}


STATES: dict[str, dict[str, Any]] = {
    "light.kitchen_ceiling": _state(
        "on",
        friendly_name="Kitchen Ceiling",
        brightness=204,
        color_mode="brightness",
        supported_color_modes=["brightness"],
        supported_features=0,
    ),
    "light.kitchen_counter": _state(
        "off",
        friendly_name="Kitchen Counter",
        color_mode=None,
        supported_color_modes=["brightness"],
        supported_features=0,
    ),
    "cover.kitchen_blinds": _state(
        "open",
        friendly_name="Kitchen Blinds",
        device_class="blind",
        current_position=65,
        supported_features=COVER_OPEN_CLOSE_STOP_POSITION,
    ),
    "climate.kitchen_heating": _state(
        "heat",
        friendly_name="Kitchen Heating",
        hvac_modes=["off", "heat", "auto"],
        hvac_action="heating",
        preset_modes=["comfort", "eco", "away", "boost"],
        preset_mode="comfort",
        current_temperature=20.5,
        temperature=21.5,
        min_temp=7,
        max_temp=30,
        target_temp_step=0.5,
        supported_features=CLIMATE_TARGET_TEMP_PRESET_ONOFF,
    ),
    "media_player.kitchen_radio": _state(
        "idle",
        friendly_name="Kitchen Radio",
        device_class="speaker",
        volume_level=0.25,
        is_volume_muted=False,
        source="FM4",
        source_list=["FM4", "Ö1", "BBC Radio 6 Music"],
        supported_features=MEDIA_RADIO,
    ),
    "media_player.kitchen_speaker": _state(
        "playing",
        friendly_name="Kitchen Speaker",
        device_class="speaker",
        volume_level=0.32,
        is_volume_muted=False,
        media_content_type="music",
        media_title="Harvest Moon",
        media_artist="Neil Young",
        media_album_name="Harvest Moon",
        media_duration=303,
        media_position=121,
        source="Spotify",
        supported_features=MEDIA_SPEAKER,
    ),
    "switch.kitchen_coffee": _state(
        "off", friendly_name="Kitchen Coffee machine", device_class="outlet"
    ),
    "scene.kitchen_cooking": _state("2026-10-08T18:02:11+00:00", friendly_name="Kitchen Cooking"),
    "scene.kitchen_breakfast": _state(
        "2026-10-09T06:45:03+00:00", friendly_name="Kitchen Breakfast"
    ),
    "weather.forecast_home": _state(
        "partlycloudy",
        friendly_name="Forecast Home",
        temperature=14.2,
        apparent_temperature=13.1,
        dew_point=8.9,
        temperature_unit="°C",
        humidity=71,
        cloud_coverage=55,
        pressure=1016.4,
        pressure_unit="hPa",
        wind_bearing=230,
        wind_speed=14.8,
        wind_speed_unit="km/h",
        visibility_unit="km",
        precipitation_unit="mm",
        attribution="Weather forecast from met.no",
        supported_features=3,
    ),
    "sensor.kitchen_display_temperature": _state(
        "21.3",
        friendly_name="Kitchen Display Temperature",
        device_class="temperature",
        state_class="measurement",
        unit_of_measurement="°C",
    ),
    "sensor.kitchen_display_humidity": _state(
        "47",
        friendly_name="Kitchen Display Humidity",
        device_class="humidity",
        state_class="measurement",
        unit_of_measurement="%",
    ),
    "light.hallway_ceiling": _state(
        "off",
        friendly_name="Hallway Ceiling",
        color_mode=None,
        supported_color_modes=["onoff"],
        supported_features=0,
    ),
    "light.guest_room_lamp": _state(
        "off",
        friendly_name="Guest Room Lamp",
        color_mode=None,
        supported_color_modes=["brightness"],
        supported_features=0,
    ),
    "cover.garage_door": _state(
        "closed",
        friendly_name="Hallway Garage door",
        device_class="garage",
        supported_features=COVER_OPEN_CLOSE_STOP,
    ),
    "lock.front_door": _state("locked", friendly_name="Front door", supported_features=LOCK_OPEN),
    "alarm_control_panel.home_alarm": _state(
        "armed_home",
        friendly_name="Alarm",
        code_arm_required=False,
        code_format=None,
        changed_by=None,
        supported_features=ALARM_HOME_AWAY_NIGHT,
    ),
    "person.anna": _state(
        "home",
        friendly_name="Anna",
        source="device_tracker.anna_phone",
        device_trackers=["device_tracker.anna_phone"],
    ),
    "person.ben": _state(
        "not_home",
        friendly_name="Ben",
        source="device_tracker.ben_phone",
        device_trackers=["device_tracker.ben_phone"],
    ),
    "binary_sensor.front_door": _state("off", friendly_name="Front door", device_class="door"),
    "binary_sensor.garage_door": _state(
        "off", friendly_name="Garage door", device_class="garage_door"
    ),
    "binary_sensor.bathroom_window": _state(
        "on", friendly_name="Bathroom Window", device_class="window"
    ),
    "binary_sensor.living_room_window": _state(
        "off", friendly_name="Living Room Window", device_class="window"
    ),
    "scene.all_off": _state(
        "2026-10-07T23:10:00+00:00", friendly_name="All off", icon="mdi:power-plug-off"
    ),
    "scene.away": _state(
        "2026-10-08T07:41:09+00:00", friendly_name="Away", icon="mdi:home-export-outline"
    ),
    "scene.good_night": _state(
        "2026-10-08T22:41:09+00:00", friendly_name="Good night", icon="mdi:weather-night"
    ),
    "script.all_off": _state(
        "off",
        friendly_name="All off",
        icon="mdi:power",
        last_triggered="2026-10-08T23:02:00+00:00",
    ),
}
STATES.update(
    {
        lamp.entity_id: _state(
            "on" if i % 3 == 0 else "off",
            friendly_name=f"Kitchen {lamp.name}",
            supported_color_modes=["brightness"],
            supported_features=0,
            **({"brightness": 180, "color_mode": "brightness"} if i % 3 == 0 else {}),
        )
        for i, lamp in enumerate(BUSY_LAMPS)
    }
)
