"""Tests for the tile name cleanup (room and floor names)."""

from __future__ import annotations

import pytest

from custom_components.walldisplay_dashboards.names import clean_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # The names from the 480 px Shelly in the area Ben on the floor OG.
        ("Licht Ben OG", "Licht"),
        ("Licht Eingang Ben OG", "Licht Eingang"),
        ("Raffstore OG Ben Nord", "Raffstore Nord"),
        ("Raffstore OG Ben West", "Raffstore West"),
        ("Ben Bett Licht", "Bett Licht"),
    ],
)
def test_area_and_floor_removed(name: str, expected: str) -> None:
    """Area and floor go, as whole words anywhere in the name."""
    assert clean_name(name, "Ben", "OG") == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Kitchen Ceiling", "Ceiling"),
        ("kitchen - counter light", "Counter light"),  # any case, dangling dash dropped
        ("Ceiling (Kitchen)", "Ceiling"),  # empty brackets dropped
        ("Ceiling - Kitchen - North", "Ceiling - North"),  # one separator left
        ("Kitchen: Ceiling", "Ceiling"),
        ("Ceiling   light Kitchen", "Ceiling light"),  # spaces collapsed
        ("kitchen_ceiling", "Ceiling"),
    ],
)
def test_separators_tidied(name: str, expected: str) -> None:
    assert clean_name(name, "Kitchen") == expected


def test_names_kept() -> None:
    """Only whole words; never an empty name; untouched names stay exactly as they are."""
    assert clean_name("Kitchenette lamp", "Kitchen") == "Kitchenette lamp"
    assert clean_name("Benjamin's lamp", "Ben", "OG") == "Benjamin's lamp"
    assert clean_name("Kitchen", "Kitchen") == "Kitchen"
    assert clean_name("Ben OG", "Ben", "OG") == "Ben OG"
    assert clean_name("Licht: Decke", "Ben") == "Licht: Decke"
    assert clean_name("Ceiling", None, "") == "Ceiling"
    assert clean_name("ceiling  lamp", None) == "ceiling  lamp"


def test_multi_word_area() -> None:
    """Longer names first, so a floor inside an area name doesn't break the area."""
    assert clean_name("Living Room Lamp", "Living Room") == "Lamp"
    assert clean_name("Lamp living  room upstairs", "Living Room", "Upstairs") == "Lamp"
    assert clean_name("Guest Room Lamp", "Guest Room", "Room") == "Lamp"
