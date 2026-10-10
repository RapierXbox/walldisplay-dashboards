"""Which entities go on which page.

Pages are room-scoped: only entities whose area is the display's area are
used, whatever the input lists hold (collect_input() already passes the
area's lists; filtering again keeps the generator correct for any input).
Area-less scenes (``house_scenes``) join every Scenes page after the room's
own; the entrance role shows them on Home instead.

Every entity is *controlled* in one place: a domain whose page exists leaves
Home. Read-only values (room card, pill temperature) may repeat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..const import PAGE_CLIMATE, PAGE_MEDIA, PAGE_SCENES, ROLE_ENTRANCE
from ..models import EntityInfo, GeneratorInput

PAGE_DOMAINS: dict[str, frozenset[str]] = {
    PAGE_CLIMATE: frozenset({"climate"}),
    PAGE_MEDIA: frozenset({"media_player"}),
    PAGE_SCENES: frozenset({"scene", "script"}),
}
PAGE_ORDER = (PAGE_CLIMATE, PAGE_MEDIA, PAGE_SCENES)
MIN_SCENES = 3  # fewer scenes stay on Home (U18)
AREA_COVER_CONTROLS = ("blind", "shade", "curtain", "shutter")
MAX_AREA_CONTROLS = 3


NaturalKey = tuple[tuple[int, int, str], ...]


def natural_key(text: str) -> NaturalKey:
    """Case-insensitive natural sort key: "Lamp 2" sorts before "Lamp 10"."""
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", text.casefold())
        if part
    )


def ordered(entities: Iterable[EntityInfo], first: Iterable[str] = ()) -> list[EntityInfo]:
    """Entities listed in `first` (in that order), then the rest by name."""
    priority = {entity_id: i for i, entity_id in enumerate(dict.fromkeys(first))}
    return sorted(
        entities,
        key=lambda e: (priority.get(e.entity_id, len(priority)), natural_key(e.name), e.entity_id),
    )


def is_entrance(data: GeneratorInput) -> bool:
    return data.role == ROLE_ENTRANCE


def leave_home_actions(data: GeneratorInput) -> list[EntityInfo]:
    """Entrance: "All off" plus area-less scenes such as Away, shown on Home.

    Entries with the same name are shown once, the script winning over the
    scene (a house often has both an "All off" scene and script).
    """
    if not is_entrance(data):
        return []
    hidden = set(data.display.overrides.hidden)
    first = [e.entity_id for e in data.leave_home]
    candidates = ordered(
        {e.entity_id: e for e in (*data.leave_home, *data.house_scenes)}.values(), first
    )
    by_name: dict[str, EntityInfo] = {}
    for entity in candidates:
        if entity.entity_id in hidden:
            continue
        key = entity.name.casefold()
        current = by_name.get(key)
        if current is None or (entity.domain == "script" and current.domain != "script"):
            by_name[key] = entity
    kept = {e.entity_id for e in by_name.values()}
    return [e for e in candidates if e.entity_id in kept]


def _room(
    data: GeneratorInput, source: Iterable[EntityInfo], domains: frozenset[str]
) -> dict[str, EntityInfo]:
    area_id = data.display.area_id
    hidden = set(data.display.overrides.hidden)
    found: dict[str, EntityInfo] = {}
    for entity in (*source, *data.area_entities):
        if (
            area_id
            and entity.area_id == area_id
            and entity.domain in domains
            and entity.entity_id not in hidden
        ):
            found.setdefault(entity.entity_id, entity)
    return found


def page_entities(data: GeneratorInput, page: str) -> list[EntityInfo]:
    """The page's entities; pinned (and for scenes, scene buttons) first."""
    source = {
        PAGE_CLIMATE: data.climates,
        PAGE_MEDIA: data.media_players,
        PAGE_SCENES: data.scenes,
    }[page]
    found = _room(data, source, PAGE_DOMAINS[page])
    first = list(data.display.overrides.pinned)
    if page != PAGE_SCENES:
        return ordered(found.values(), first)
    first += data.display.overrides.scene_buttons
    room = ordered(found.values(), first)
    # Entrance: leave-home candidates belong to Home (even a same-named duplicate).
    on_home = (
        {e.entity_id for e in (*data.leave_home, *data.house_scenes)}
        if is_entrance(data)
        else set()
    )
    hidden = set(data.display.overrides.hidden)
    house = [
        e
        for e in ordered(data.house_scenes)
        if e.domain == "scene"
        and e.area_id is None
        and e.entity_id not in found
        and e.entity_id not in on_home
        and e.entity_id not in hidden
    ]
    return [e for e in room if e.entity_id not in on_home] + house


def active_pages(data: GeneratorInput) -> list[str]:
    """Optional pages that are enabled and have something to show, in nav order."""
    enabled = set(data.display.pages)
    result = []
    for page in PAGE_ORDER:
        if page not in enabled:
            continue
        needed = MIN_SCENES if page == PAGE_SCENES else 1
        if len(page_entities(data, page)) >= needed:
            result.append(page)
    return result


def home_excluded_domains(data: GeneratorInput) -> frozenset[str]:
    """Domains shown on their own page instead of Home."""
    return frozenset().union(*(PAGE_DOMAINS[p] for p in active_pages(data)))


def primary(data: GeneratorInput, page: str) -> EntityInfo | None:
    entities = page_entities(data, page)
    return entities[0] if entities else None


def room_humidity(data: GeneratorInput) -> str | None:
    """Area's designated humidity sensor, else the first area sensor, else the display's."""
    if data.area_humidity:
        return data.area_humidity
    hidden = set(data.display.overrides.hidden)
    for entity in ordered(data.area_sensors):
        if entity.device_class == "humidity" and entity.entity_id not in hidden:
            return entity.entity_id
    return data.display.indoor_humidity


def room_temperature(data: GeneratorInput) -> str | None:
    """One room temperature (U3): designated sensor, primary climate, area sensor, display."""
    if data.area_temperature:
        return data.area_temperature
    if (climate := primary(data, PAGE_CLIMATE)) is not None:
        return climate.entity_id
    hidden = set(data.display.overrides.hidden)
    for entity in ordered(data.area_sensors):
        if entity.device_class == "temperature" and entity.entity_id not in hidden:
            return entity.entity_id
    return data.display.indoor_temperature


def area_controls(data: GeneratorInput) -> list[str]:
    """area-controls for the room card: lights (2+), window-type covers. Never switches."""
    hidden = set(data.display.overrides.hidden)
    area_id = data.display.area_id
    entities = [e for e in data.area_entities if e.area_id == area_id and e.entity_id not in hidden]
    controls = []
    if sum(e.domain == "light" for e in entities) >= 2:
        controls.append("light")
    present = {e.device_class for e in entities if e.domain == "cover"}
    controls += [f"cover-{c}" for c in AREA_COVER_CONTROLS if c in present]
    return controls[:MAX_AREA_CONTROLS]


def is_empty_room(data: GeneratorInput) -> bool:
    """True when the display's area has nothing to control (raise a repair issue)."""
    from .home import home_items  # local: home imports this module

    return not home_items(data) and not active_pages(data)
