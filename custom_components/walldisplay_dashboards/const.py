"""Constants for Wall Display Dashboards."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "walldisplay_dashboards"
VERSION: Final = "0.1.0"

# Dashboards created by this integration live at /wall-<slug>.
URL_PREFIX: Final = "wall-"

# Frontend module served by the integration and auto-loaded on every page.
FRONTEND_URL_BASE: Final = f"/{DOMAIN}_static"
FRONTEND_SCRIPT: Final = "walldisplay.js"

# Custom dashboard strategy registered by the frontend module.
STRATEGY_TYPE: Final = "custom:wall-display"

# Websocket commands (see docs/contracts.md).
WS_GENERATE: Final = f"{DOMAIN}/generate"
WS_LIST: Final = f"{DOMAIN}/list"
WS_REPORT_VIEWPORT: Final = f"{DOMAIN}/report_viewport"

# Config entry data keys (set in the config flow, changed via reconfigure).
CONF_NAME: Final = "name"
CONF_URL_PATH: Final = "url_path"
CONF_AREA_ID: Final = "area_id"
CONF_PROFILE: Final = "profile"
CONF_WIDTH: Final = "width"
CONF_HEIGHT: Final = "height"
CONF_DISPLAY_DEVICE_ID: Final = "display_device_id"
CONF_WEATHER_ENTITY: Final = "weather_entity"

# Config entry option keys (options flow).
CONF_PAGES: Final = "pages"
CONF_IDLE_SECONDS: Final = "idle_seconds"
CONF_KIOSK: Final = "kiosk"
CONF_PINNED: Final = "pinned"
CONF_HIDDEN: Final = "hidden"
CONF_SCENE_BUTTONS: Final = "scene_buttons"
CONF_SHOW_IN_SIDEBAR: Final = "show_in_sidebar"
CONF_DISPLAY_HOST: Final = "display_host"
CONF_ROLE: Final = "role"

# Display role (options). Entrance adds house-wide status and leave-home actions.
ROLE_ROOM: Final = "room"
ROLE_ENTRANCE: Final = "entrance"
ROLES: Final = (ROLE_ROOM, ROLE_ENTRANCE)
DEFAULT_ROLE: Final = ROLE_ROOM

# Pages. "home" is always present; the others are optional.
PAGE_HOME: Final = "home"
PAGE_CLIMATE: Final = "climate"
PAGE_MEDIA: Final = "media"
PAGE_SCENES: Final = "scenes"
PAGE_MORE: Final = "more"  # automatic overflow page, never configured
OPTIONAL_PAGES: Final = (PAGE_CLIMATE, PAGE_MEDIA, PAGE_SCENES)
DEFAULT_PAGES: Final = [PAGE_CLIMATE, PAGE_MEDIA, PAGE_SCENES]

# English fallback nav labels; the generator localises them (generator owns the label table).
NAV: Final = {
    PAGE_HOME: ("Home", "mdi:home"),
    PAGE_CLIMATE: ("Climate", "mdi:thermostat"),
    PAGE_MEDIA: ("Media", "mdi:speaker"),
    PAGE_SCENES: ("Scenes", "mdi:palette"),
    PAGE_MORE: ("More", "mdi:dots-horizontal"),
}

KIOSK_BUILTIN: Final = "builtin"
KIOSK_KIOSK_MODE: Final = "kiosk_mode"
KIOSK_OFF: Final = "off"
KIOSK_MODES: Final = (KIOSK_BUILTIN, KIOSK_KIOSK_MODE, KIOSK_OFF)

DEFAULT_IDLE_SECONDS: Final = 60
DEFAULT_KIOSK: Final = KIOSK_BUILTIN

# Home tiles are filled from the area in this domain order.
TILE_DOMAIN_RANK: Final = (
    "light",
    "cover",
    "climate",
    "media_player",
    "fan",
    "switch",
    "lock",
    "alarm_control_panel",
    "scene",
    "script",
)

# Never tap-to-act: auto-added as status tiles whose tap opens more-info.
SECURE_DOMAINS: Final = ("lock", "alarm_control_panel", "valve", "siren")
SECURE_COVER_CLASSES: Final = ("garage", "gate", "door")

# Sections-view grid, measured on HA 2026.10 (see docs/contracts.md).
GRID_ROW_PX: Final = 56
GRID_GAP_PX: Final = 8
GRID_TOP_PX: Final = 12  # view row gap with the walldisplay.js spacing CSS
FOOTER_BAND_PX: Final = 92  # 12 sticky offset + 72 footer box + 8 air, from the bottom
BOTTOM_MARGIN_PX: Final = 12  # bottom padding when there is no footer
VIEW_GAP_PX: Final = 12  # side padding / column gap above 600 px wide (8 at or below)
COLUMN_MIN_PX: Final = 320
ROW_MIN_PX: Final = 48  # walldisplay.js stretches rows to fill the height, within these
ROW_MAX_PX: Final = 72
# Tile sizing; the typography pass may raise MIN_TILE_PX (the one tile-width knob).
MIN_TILE_PX: Final = 140  # vertical tiles: ~15 characters at the 16 px tile font
MIN_HORIZONTAL_TILE_PX: Final = 170  # 1-row tiles (icon beside the name) need more
GROWN_TILE_MAX_ROWS: Final = 4
