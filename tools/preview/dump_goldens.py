"""Write the golden dashboards for the sample house.

    python tools/preview/dump_goldens.py

Writes tests/fixtures/expected/<profile_id>.json for every profile in
PROFILES (custom at 800x480), <profile_id>@<variant>.json for the sample
variants (sample_house.GOLDEN_VARIANTS) and tests/fixtures/expected/states.json with mock
states for every entity the dashboards use. Needs no Home Assistant install.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_house  # noqa: E402

PACKAGE = sample_house.PACKAGE
OUT = sample_house.ROOT / "tests" / "fixtures" / "expected"
CUSTOM_SIZE = (800, 480)


def golden_profiles() -> list:
    """Every known profile, plus custom at 800x480."""
    profiles = importlib.import_module(f"{PACKAGE}.profiles")
    result = [p for pid, p in profiles.PROFILES.items() if pid != profiles.CUSTOM]
    result.append(profiles.resolve_profile(profiles.CUSTOM, *CUSTOM_SIZE))
    return result


def build_goldens() -> dict[str, dict]:
    """Golden name -> dashboard config.

    One per profile for the kitchen display, plus `<profile>@<variant>` for
    the variants in sample_house.GOLDEN_VARIANTS (entrance role, German, empty
    room, no forecast, busy room).
    """
    generator = importlib.import_module(f"{PACKAGE}.generator")
    profiles = importlib.import_module(f"{PACKAGE}.profiles")
    result = {
        profile.id: generator.build_dashboard(sample_house.sample_input(profile))
        for profile in golden_profiles()
    }
    for profile_id, variant in sample_house.GOLDEN_VARIANTS:
        make_input, kwargs = sample_house.VARIANTS[variant]
        data = make_input(profiles.PROFILES[profile_id], **kwargs)
        result[f"{profile_id}@{variant}"] = generator.build_dashboard(data)
    return result


def used_states(dashboards: dict[str, dict]) -> dict[str, dict]:
    """Mock states for every entity referenced by the dashboards."""
    cards = importlib.import_module(f"{PACKAGE}.generator.cards")
    used: set[str] = set()
    for dashboard in dashboards.values():
        used |= cards.referenced_entities(dashboard)
    missing = used - sample_house.STATES.keys()
    if missing:
        raise SystemExit(f"No mock state for: {', '.join(sorted(missing))}")
    # Every sample entity, so the preview can also show the More views.
    return dict(sorted(sample_house.STATES.items()))


def _dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help="output folder")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    dashboards = build_goldens()
    for profile_id, dashboard in dashboards.items():
        _dump(args.out / f"{profile_id}.json", dashboard)
    _dump(args.out / "states.json", used_states(dashboards))

    for name, dashboard in dashboards.items():
        views = ", ".join(
            f"{v['path']}:{len(v['sections'][0]['cards'])}" for v in dashboard["views"]
        )
        print(f"{name:32} {views}")
    print(f"Wrote {len(dashboards)} dashboards and states.json to {args.out}")


if __name__ == "__main__":
    main()
