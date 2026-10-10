"""Config flow for Wall Display Dashboards: one config entry per wall display."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

import probatio
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    AreaSelector,
    BooleanSelector,
    DeviceSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_AREA_ID,
    CONF_CLIMATE_ENTITIES,
    CONF_DISPLAY_DEVICE_ID,
    CONF_DISPLAY_HOST,
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
    CONF_SHOW_IN_SIDEBAR,
    CONF_TEMPERATURE_ENTITY,
    CONF_URL_PATH,
    CONF_WEATHER_ENTITY,
    CONF_WIDTH,
    DEFAULT_IDLE_SECONDS,
    DEFAULT_KIOSK,
    DEFAULT_PAGES,
    DEFAULT_ROLE,
    DOMAIN,
    KIOSK_MODES,
    MAX_HOME_TILES_LIMIT,
    OPTIONAL_PAGES,
    ROLES,
    TILE_DOMAIN_RANK,
    URL_PREFIX,
)
from .profiles import CUSTOM as PROFILE_CUSTOM
from .profiles import PROFILES

MIN_SIZE_PX = 240
MAX_SIZE_PX = 2560
MAX_SCENE_BUTTONS = 2

# Data keys the reconfigure step may change; everything else (name, url_path) stays.
_RECONFIGURABLE_KEYS = (
    CONF_AREA_ID,
    CONF_PROFILE,
    CONF_WIDTH,
    CONF_HEIGHT,
    CONF_DISPLAY_DEVICE_ID,
    CONF_DISPLAY_HOST,
    CONF_WEATHER_ENTITY,
)


def default_options() -> dict[str, Any]:
    """Options stored on a new entry."""
    return {
        CONF_ROLE: DEFAULT_ROLE,
        CONF_PAGES: list(DEFAULT_PAGES),
        CONF_IDLE_SECONDS: DEFAULT_IDLE_SECONDS,
        CONF_KIOSK: DEFAULT_KIOSK,
        CONF_PINNED: [],
        CONF_HIDDEN: [],
        CONF_SCENE_BUTTONS: [],
        CONF_CLIMATE_ENTITIES: [],
        CONF_MAX_HOME_TILES: 0,
        CONF_INCLUDE_DISPLAY_ENTITIES: False,
        CONF_SHOW_IN_SIDEBAR: True,
    }


def url_path_for_name(name: str) -> str:
    """Return the dashboard url_path for a display name."""
    return URL_PREFIX + slugify(name, separator="-")


def _profile_ids() -> list[str]:
    """Profile ids for the model dropdown; "custom" always last."""
    ids = [profile_id for profile_id in PROFILES if profile_id != PROFILE_CUSTOM]
    ids.append(PROFILE_CUSTOM)
    return ids


def _first_weather_entity(hass: HomeAssistant) -> str | None:
    """Return the first weather entity, if any."""
    entity_ids = sorted(hass.states.async_entity_ids("weather"))
    return entity_ids[0] if entity_ids else None


def _sensor_selector(device_class: str) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="sensor", device_class=device_class))


def _role_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(ROLES), mode=SelectSelectorMode.LIST, translation_key="role"
        )
    )


def _display_schema(*, new_entry: bool) -> probatio.Schema:
    """Schema for the user step (new_entry) and the reconfigure step."""
    schema: dict[Any, Any] = {}
    if new_entry:
        schema[probatio.Required(CONF_NAME)] = TextSelector()
    # Device before area: an empty area falls back to the device's area (P1-9).
    schema[probatio.Optional(CONF_DISPLAY_DEVICE_ID)] = DeviceSelector()
    schema[probatio.Optional(CONF_AREA_ID)] = AreaSelector()
    schema[probatio.Required(CONF_PROFILE)] = SelectSelector(
        SelectSelectorConfig(
            options=_profile_ids(),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="profile",
        )
    )
    if new_entry:
        schema[probatio.Required(CONF_ROLE, default=DEFAULT_ROLE)] = _role_selector()
    schema.update(
        {
            probatio.Optional(CONF_DISPLAY_HOST): TextSelector(),
            probatio.Optional(CONF_WEATHER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="weather")
            ),
        }
    )
    return probatio.Schema(schema)


def _size_schema() -> probatio.Schema:
    """Schema for the custom_size step."""
    size = NumberSelector(
        NumberSelectorConfig(
            min=MIN_SIZE_PX,
            max=MAX_SIZE_PX,
            step=1,
            unit_of_measurement="px",
            mode=NumberSelectorMode.BOX,
        )
    )
    return probatio.Schema(
        {
            probatio.Required(CONF_WIDTH): size,
            probatio.Required(CONF_HEIGHT): size,
        }
    )


def _device_area(hass: HomeAssistant, device_id: str | None) -> str | None:
    """Area of the display device, if it has one."""
    if device_id and (device := dr.async_get(hass).async_get(device_id)):
        return device.area_id
    return None


def _clean_display_input(hass: HomeAssistant, user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise user/reconfigure input into entry data fields.

    An empty area is taken from the display device. The result has no area_id
    if neither is set; the caller turns that into an error.
    """
    data: dict[str, Any] = {CONF_PROFILE: user_input[CONF_PROFILE]}
    area_id = user_input.get(CONF_AREA_ID) or _device_area(
        hass, user_input.get(CONF_DISPLAY_DEVICE_ID)
    )
    if area_id:
        data[CONF_AREA_ID] = area_id
    host = str(user_input.get(CONF_DISPLAY_HOST) or "").strip()
    if host:
        data[CONF_DISPLAY_HOST] = host
    for key in (CONF_DISPLAY_DEVICE_ID, CONF_WEATHER_ENTITY):
        if value := user_input.get(key):
            data[key] = value
    return data


def _area_error(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """Error key for the area field: missing, or deleted since it was picked."""
    area_id = data.get(CONF_AREA_ID)
    if not area_id:
        return "area_required"
    if ar.async_get(hass).async_get_area(area_id) is None:
        return "area_not_found"
    return None


class WallDisplayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one wall display."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._data: dict[str, Any] = {}
        self._role: str = DEFAULT_ROLE

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> WallDisplayOptionsFlow:
        """Return the options flow."""
        return WallDisplayOptionsFlow()

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the display's name, area, model and optional links."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            url_path = url_path_for_name(name)
            # slugify() turns a name without letters or digits into "unknown".
            if not any(char.isalnum() for char in name):
                errors[CONF_NAME] = "invalid_name"
            else:
                await self.async_set_unique_id(url_path)
                self._abort_if_unique_id_configured()
                if url_path in self.hass.data.get(DATA_PANELS, {}):
                    errors[CONF_NAME] = "url_path_taken"
            data = _clean_display_input(self.hass, user_input)
            if area_error := _area_error(self.hass, data):
                errors[CONF_AREA_ID] = area_error
            if not errors:
                self._data = {CONF_NAME: name, CONF_URL_PATH: url_path, **data}
                self._role = user_input.get(CONF_ROLE, DEFAULT_ROLE)
                if self._data[CONF_PROFILE] == PROFILE_CUSTOM:
                    return await self.async_step_custom_size()
                return self._async_create_display()

        suggested: dict[str, Any] = dict(user_input or {})
        if user_input is None and (weather := _first_weather_entity(self.hass)):
            suggested[CONF_WEATHER_ENTITY] = weather
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _display_schema(new_entry=True), suggested
            ),
            errors=errors,
        )

    async def async_step_custom_size(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the CSS viewport of a display without a built-in profile."""
        if user_input is not None and CONF_WIDTH in user_input:
            self._data[CONF_WIDTH] = int(user_input[CONF_WIDTH])
            self._data[CONF_HEIGHT] = int(user_input[CONF_HEIGHT])
            if self.source == SOURCE_RECONFIGURE:
                return self._async_update_display()
            return self._async_create_display()

        suggested: dict[str, Any] = {
            key: self._data[key] for key in (CONF_WIDTH, CONF_HEIGHT) if key in self._data
        }
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            for key in (CONF_WIDTH, CONF_HEIGHT):
                if key in entry.data:
                    suggested.setdefault(key, entry.data[key])
        return self.async_show_form(
            step_id="custom_size",
            data_schema=self.add_suggested_values_to_schema(_size_schema(), suggested),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change area, model and links. Name and url_path stay as they are."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = _clean_display_input(self.hass, user_input)
            if area_error := _area_error(self.hass, self._data):
                errors[CONF_AREA_ID] = area_error
            elif self._data[CONF_PROFILE] == PROFILE_CUSTOM:
                return await self.async_step_custom_size()
            else:
                if self._data[CONF_PROFILE] == entry.data.get(CONF_PROFILE):
                    # Keep a measured size adopted through the repair flow.
                    for key in (CONF_WIDTH, CONF_HEIGHT):
                        if key in entry.data:
                            self._data[key] = entry.data[key]
                return self._async_update_display()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _display_schema(new_entry=False),
                user_input if user_input is not None else entry.data,
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @callback
    def _async_create_display(self) -> ConfigFlowResult:
        """Create the config entry."""
        return self.async_create_entry(
            title=self._data[CONF_NAME],
            data=self._data,
            options={**default_options(), CONF_ROLE: self._role},
        )

    @callback
    def _async_update_display(self) -> ConfigFlowResult:
        """Write reconfigured data and reload."""
        entry = self._get_reconfigure_entry()
        data = {k: v for k, v in entry.data.items() if k not in _RECONFIGURABLE_KEYS}
        data.update(self._data)
        return self.async_update_reload_and_abort(entry, data=data)


class WallDisplayOptionsFlow(OptionsFlowWithReload):
    """Favourite scenes, role, pages, idle timeout, kiosk mode, tile and climate overrides."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            scene_buttons = list(user_input.get(CONF_SCENE_BUTTONS, []))
            if len(scene_buttons) > MAX_SCENE_BUTTONS:
                errors[CONF_SCENE_BUTTONS] = "too_many_scene_buttons"
            else:
                pages = set(user_input.get(CONF_PAGES, []))
                options: dict[str, Any] = {
                    CONF_ROLE: user_input.get(CONF_ROLE, DEFAULT_ROLE),
                    CONF_PAGES: [p for p in OPTIONAL_PAGES if p in pages],
                    CONF_IDLE_SECONDS: int(user_input.get(CONF_IDLE_SECONDS, DEFAULT_IDLE_SECONDS)),
                    CONF_KIOSK: user_input.get(CONF_KIOSK, DEFAULT_KIOSK),
                    CONF_PINNED: list(user_input.get(CONF_PINNED, [])),
                    CONF_HIDDEN: list(user_input.get(CONF_HIDDEN, [])),
                    CONF_SCENE_BUTTONS: scene_buttons,
                    CONF_CLIMATE_ENTITIES: list(user_input.get(CONF_CLIMATE_ENTITIES, [])),
                    CONF_MAX_HOME_TILES: int(user_input.get(CONF_MAX_HOME_TILES, 0)),
                    CONF_INCLUDE_DISPLAY_ENTITIES: bool(
                        user_input.get(CONF_INCLUDE_DISPLAY_ENTITIES, False)
                    ),
                    CONF_SHOW_IN_SIDEBAR: bool(user_input.get(CONF_SHOW_IN_SIDEBAR, True)),
                }
                # Optional sensors: a cleared field is left out (automatic).
                for key in (CONF_TEMPERATURE_ENTITY, CONF_HUMIDITY_ENTITY):
                    if value := user_input.get(key):
                        options[key] = value
                return self.async_create_entry(data=options)

        current = {**default_options(), **self.config_entry.options}
        suggested = user_input if user_input is not None else current
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(self._schema(), suggested),
            errors=errors,
        )

    def _schema(self) -> probatio.Schema:
        """Build the options schema."""
        # Pins may come from any room: every tile domain entity is offered, so
        # entities pinned earlier stay selectable.
        pinned_config = EntitySelectorConfig(domain=list(TILE_DOMAIN_RANK), multiple=True)
        return probatio.Schema(
            {
                probatio.Optional(CONF_SCENE_BUTTONS): EntitySelector(
                    EntitySelectorConfig(domain=["scene", "script"], multiple=True)
                ),
                probatio.Required(CONF_ROLE, default=DEFAULT_ROLE): _role_selector(),
                probatio.Optional(CONF_PAGES): SelectSelector(
                    SelectSelectorConfig(
                        options=list(OPTIONAL_PAGES),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="pages",
                    )
                ),
                probatio.Required(CONF_IDLE_SECONDS): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=600,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                probatio.Required(CONF_KIOSK): SelectSelector(
                    SelectSelectorConfig(
                        options=list(KIOSK_MODES),
                        mode=SelectSelectorMode.LIST,
                        translation_key="kiosk",
                    )
                ),
                probatio.Optional(CONF_PINNED): EntitySelector(pinned_config),
                probatio.Optional(CONF_HIDDEN): EntitySelector(EntitySelectorConfig(multiple=True)),
                probatio.Required(CONF_MAX_HOME_TILES, default=0): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_HOME_TILES_LIMIT, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                probatio.Required(CONF_INCLUDE_DISPLAY_ENTITIES, default=False): BooleanSelector(),
                # Climate entities may come from any room, like pins.
                probatio.Optional(CONF_CLIMATE_ENTITIES): EntitySelector(
                    EntitySelectorConfig(domain="climate", multiple=True)
                ),
                probatio.Optional(CONF_TEMPERATURE_ENTITY): _sensor_selector("temperature"),
                probatio.Optional(CONF_HUMIDITY_ENTITY): _sensor_selector("humidity"),
                probatio.Required(CONF_SHOW_IN_SIDEBAR): BooleanSelector(),
            }
        )
