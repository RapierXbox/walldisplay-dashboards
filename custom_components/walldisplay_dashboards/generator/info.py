"""EntityInfo subclasses carrying the extra attributes some cards need."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import EntityInfo


@dataclass(frozen=True, slots=True)
class ClimateInfo(EntityInfo):
    """Climate entity plus the modes the thermostat features need."""

    hvac_modes: tuple[str, ...] = ()
    preset_modes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LightInfo(EntityInfo):
    """Light entity; dimmable lights get a brightness feature on big tiles."""

    dimmable: bool = False
