"""Shared data model. Pure Python: no Home Assistant imports.

Everything the dashboard generator needs is passed in as these objects, so the
generator can be tested and previewed without a running Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Orientation = Literal["square", "landscape", "portrait"]


@dataclass(frozen=True, slots=True)
class Profile:
    """A display model and the CSS viewport its browser reports."""

    id: str
    name: str
    width: int  # CSS px
    height: int  # CSS px
    dpr_hint: float = 1.0
    measured: bool = False  # True once the size comes from a real device

    @property
    def orientation(self) -> Orientation:
        ratio = self.width / self.height
        if ratio > 1.2:
            return "landscape"
        if ratio < 1 / 1.2:
            return "portrait"
        return "square"


@dataclass(frozen=True, slots=True)
class Grid:
    """Layout budget for one profile (output of layout.compute_grid)."""

    section_columns: int  # sections side by side (1-3)
    card_columns: int  # 12 per section column
    rows: int  # grid rows available above the footer
    tile_rows: int  # height of one home tile in grid rows (1 or 2)
    tile_columns: int  # width of one home tile in card columns
    tiles_per_row: int
    max_tiles: int
    info_columns: int  # 0 = no info column (square/portrait layouts)


@dataclass(frozen=True, slots=True)
class EntityInfo:
    """What the generator needs to know about one entity."""

    entity_id: str
    name: str
    area_id: str | None = None
    device_class: str | None = None
    supported_features: int = 0
    icon: str | None = None  # the entity's own icon (registry or state), if any

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class Overrides:
    """User adjustments from the options flow."""

    pinned: tuple[str, ...] = ()  # shown first, in this order
    hidden: tuple[str, ...] = ()  # never shown
    scene_buttons: tuple[str, ...] = ()  # favourite scenes/scripts: first on Scenes


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    """One wall display (one config entry), resolved from entry data + options."""

    entry_id: str
    name: str
    url_path: str
    area_id: str | None
    profile: Profile
    pages: tuple[str, ...]  # optional pages in nav order; "home" is implicit
    weather_entity: str | None = None
    indoor_temperature: str | None = None  # sensor entity of the display itself
    indoor_humidity: str | None = None
    idle_seconds: int = 60
    kiosk: str = "builtin"
    overrides: Overrides = field(default_factory=Overrides)


@dataclass(frozen=True, slots=True)
class GeneratorInput:
    """Everything build_dashboard() reads. Built by entities.collect_input()."""

    display: DisplayConfig
    area_name: str
    area_entities: tuple[EntityInfo, ...]  # entities in the display's area
    climates: tuple[EntityInfo, ...]  # climate entities in the display's area
    media_players: tuple[EntityInfo, ...]  # media players in the display's area
    scenes: tuple[EntityInfo, ...]  # scenes + scripts in the display's area
    area_names: dict[str, str] = field(default_factory=dict)  # area_id -> name
    area_sensors: tuple[EntityInfo, ...] = ()  # area temperature/humidity sensors
    language: str = "en"  # hass.config.language; the generator localises its labels
    role: str = "room"  # options "role": "room" | "entrance"
    area_temperature: str | None = None  # area registry temperature_entity_id
    area_humidity: str | None = None  # area registry humidity_entity_id
    house_scenes: tuple[EntityInfo, ...] = ()  # scenes without an area
    weather_features: int = 0  # supported_features of the weather entity (forecast types)
    # Entrance role only (empty otherwise):
    persons: tuple[EntityInfo, ...] = ()
    house_lights: tuple[str, ...] = ()  # every light; counted while on
    openings: tuple[str, ...] = ()  # door/window binary sensors; counted while open
    house_secure: tuple[EntityInfo, ...] = ()  # locks and alarm panels, read-only
    leave_home: tuple[EntityInfo, ...] = ()  # "All off" scripts/scenes
