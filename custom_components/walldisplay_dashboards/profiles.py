"""Known wall display models and their CSS viewports. Pure Python."""

from __future__ import annotations

from dataclasses import replace

from .models import Profile

CUSTOM = "custom"
DEFAULT_PROFILE = "shelly_wall_display"
# Size used for "custom" when no width/height were stored.
CUSTOM_DEFAULT_SIZE = (480, 480)

PROFILES: dict[str, Profile] = {
    p.id: p
    for p in (
        Profile("shelly_wall_display", 'Shelly Wall Display (4")', 480, 480, 1.0),
        Profile("shelly_x1i", "Shelly Wall Display X1i", 480, 480, 1.5),
        Profile("shelly_x2_landscape", "Shelly Wall Display X2 / X2i, landscape", 960, 480, 1.5),
        Profile("shelly_x2_portrait", "Shelly Wall Display X2 / X2i, portrait", 480, 960, 1.5),
        Profile("shelly_xl", "Shelly Wall Display XL / XLi", 1280, 752, 1.0),
        Profile("nspanel_pro", "Sonoff NSPanel Pro", 480, 480, 1.0),
        Profile("tablet_landscape", 'Tablet, landscape (8–10")', 1280, 800, 1.0),
        Profile("tablet_portrait", 'Tablet, portrait (8–10")', 800, 1280, 1.0),
        Profile(CUSTOM, "Custom size", *CUSTOM_DEFAULT_SIZE, 1.0),
    )
}


def _valid(size: int | None) -> bool:
    return isinstance(size, int) and not isinstance(size, bool) and size > 0


def resolve_profile(profile_id: str, width: int | None, height: int | None) -> Profile:
    """Return the profile for an entry.

    "custom" takes width/height. A known id ignores them unless both are given,
    in which case they are a measured size adopted through the repair flow.
    Unknown ids fall back to the custom size if given, else the default display.
    """
    sized = _valid(width) and _valid(height)
    if profile_id == CUSTOM or profile_id not in PROFILES:
        if sized:
            return replace(PROFILES[CUSTOM], width=width, height=height)
        if profile_id == CUSTOM:
            return PROFILES[CUSTOM]
        return PROFILES[DEFAULT_PROFILE]
    profile = PROFILES[profile_id]
    if sized:
        return replace(profile, width=width, height=height, measured=True)
    return profile
