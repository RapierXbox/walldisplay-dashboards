"""Short tile names: drop the room and floor from entity names. Pure Python.

"Licht Ben OG" in the area Ben on the floor OG is "Licht" on Ben's display:
the dashboard already says which room it is, and a 480 px tile has no space
to repeat it.
"""

from __future__ import annotations

import re

# Characters that join the parts of a name ("Kitchen - Ceiling", "Ben: Licht").
NAME_SEPARATORS = " -:_·–"
_PUNCTUATION = re.escape(NAME_SEPARATORS.replace(" ", ""))
# A run of separators and spaces between two parts of a name.
_SEPARATOR_RUN = re.compile(rf"[\s{_PUNCTUATION}]+")
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")


def _word_pattern(word: str) -> re.Pattern[str]:
    """`word` as a whole word (not inside "Benjamin"), with the spaces before it."""
    parts = r"\s+".join(re.escape(part) for part in word.split())
    return re.compile(rf"\s*(?<![^\W_]){parts}(?![^\W_])", re.IGNORECASE)


def _tidy_run(match: re.Match[str]) -> str:
    """Collapse what stripping left between two parts: "Licht -  - Nord" -> "Licht - Nord"."""
    run = match.group()
    marks = [char for char in run if not char.isspace()]
    if not marks:
        return " "
    before = " " if run[0].isspace() else ""
    after = " " if run[-1].isspace() else ""
    return f"{before}{marks[0]}{after}"


def clean_name(name: str, *words: str | None) -> str:
    """Remove the area and floor names (`words`) from an entity name.

    Whole words only, anywhere in the name and in any case; separators left
    dangling are dropped and spaces collapsed. A name that would end up empty
    (it is only the room) stays as it is.
    """
    result = name
    for word in sorted({w.strip() for w in words if w and w.strip()}, key=len, reverse=True):
        result = _word_pattern(word).sub("", result)
    if result == name:
        return name
    result = _EMPTY_BRACKETS.sub("", result)
    result = _SEPARATOR_RUN.sub(_tidy_run, result).strip(NAME_SEPARATORS + " \t")
    if not result:
        return name
    return result[:1].upper() + result[1:]
