"""Every label the generator writes, in English and German (fallback English).

The frontend localises nothing it receives, so all generated text comes from
here. Nav labels stay at 8 characters or fewer.
"""

from __future__ import annotations

from ..const import NAV

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "home": "Home",
        "climate": "Climate",
        "media": "Media",
        "scenes": "Scenes",
        "more": "More",
        "outside": "Outside",
        "volume": "Volume",
        "mode": "Mode",
        "humidity": "Humidity",
        "temperature": "Temperature",
        "more_n": "+{n} more",
    },
    "de": {
        "home": "Start",
        "climate": "Klima",
        "media": "Medien",
        "scenes": "Szenen",
        "more": "Mehr",
        "outside": "Draußen",
        "volume": "Lautstärke",
        "mode": "Modus",
        "humidity": "Feuchte",
        "temperature": "Temperatur",
        "more_n": "+{n} weitere",
    },
}
MAX_NAV_LABEL = 8


def language_code(language: str | None) -> str:
    """'de-AT' -> 'de'; unknown languages fall back to English."""
    code = (language or "en").replace("_", "-").split("-", 1)[0].lower()
    return code if code in LABELS else "en"


def label(language: str | None, key: str, **values: object) -> str:
    table = LABELS[language_code(language)]
    text = table.get(key) or LABELS["en"].get(key) or NAV.get(key, (key,))[0]
    return text.format(**values) if values else text


def nav_label(language: str | None, page: str) -> str:
    return label(language, page)[:MAX_NAV_LABEL]
