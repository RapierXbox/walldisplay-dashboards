"""Build a self-contained HTML preview of the generated wall-display dashboards.

Reads every ``tests/fixtures/expected/<profile_id>.json`` (full dashboard
``{"title", "views"}``) plus ``states.json`` (mock HA states), inlines them with
the icon paths from ``icons.json`` into ``template.html`` and writes
``preview.html`` next to this script.

    python tools/preview/build_preview.py               # goldens, else dev_sample
    python tools/preview/build_preview.py --source tools/preview/dev_sample

Icons: ``icons.json`` maps ``mdi:<name>`` to an SVG path. When the dashboards
use an icon that is missing there and ``node_modules/@mdi/js`` is installed
(``npm install`` in this folder), the path is looked up and ``icons.json`` is
updated. Without the package, missing icons render as a fallback glyph.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_SOURCE = ROOT / "tests" / "fixtures" / "expected"
DEV_SAMPLE = HERE / "dev_sample"
TEMPLATE = HERE / "template.html"
ICONS = HERE / "icons.json"
MDI_JS = HERE / "node_modules" / "@mdi" / "js" / "mdi.js"
COMPONENT = ROOT / "custom_components" / "walldisplay_dashboards"
PLACEHOLDER = "/*__PREVIEW_DATA__*/"

# Fallback copy of the profile table in docs/contracts.md; profiles.py wins when importable.
FALLBACK_PROFILES: dict[str, tuple[str, int, int, float]] = {
    "shelly_wall_display": ('Shelly Wall Display (4")', 480, 480, 1.0),
    "shelly_x1i": ("Shelly Wall Display X1i", 480, 480, 1.5),
    "shelly_x2_landscape": ("Shelly Wall Display X2 / X2i, landscape", 960, 480, 1.5),
    "shelly_x2_portrait": ("Shelly Wall Display X2 / X2i, portrait", 480, 960, 1.5),
    "shelly_xl": ("Shelly Wall Display XL / XLi", 1280, 752, 1.0),
    "nspanel_pro": ("Sonoff NSPanel Pro", 480, 480, 1.0),
    "tablet_landscape": ("Tablet, landscape (8-10\")", 1280, 800, 1.0),
    "tablet_portrait": ("Tablet, portrait (8-10\")", 800, 1280, 1.0),
}

# Icons the template needs regardless of the dashboards: domain defaults,
# state variants, weather conditions and the controls drawn by tile features.
BASE_ICONS = """
home thermostat speaker palette lightbulb lightbulb-off lightbulb-outline blinds blinds-open
blinds-horizontal blinds-horizontal-closed window-shutter window-shutter-open roller-shade roller-shade-closed
window-open window-closed garage garage-open curtains curtains-closed
speaker-off television television-off cast cast-off music music-off
toggle-switch toggle-switch-off toggle-switch-variant toggle-switch-variant-off toggle-switch-off-outline
fan fan-off script-text lock lock-open lock-open-variant power power-off
thermometer water-percent gauge eye flash flash-off motion-sensor door-open door-closed
weather-sunny weather-night weather-partly-cloudy weather-night-partly-cloudy weather-cloudy weather-fog
weather-hail weather-lightning weather-lightning-rainy weather-pouring weather-rainy weather-snowy
weather-snowy-rainy weather-windy weather-windy-variant weather-sunny-alert alert-circle-outline
minus plus play pause stop skip-previous skip-next volume-high volume-medium volume-low volume-off
help-circle-outline alert clock-outline calendar view-dashboard radiator fire snowflake sun-snowflake-variant
water-percent air-humidifier gesture-tap shuffle repeat fire snowflake thermostat-auto tune-variant menu-down
dots-vertical play-box-multiple speaker-multiple music circle-medium
texture-box account shield-check shield-off shield-outline shield-home shield-lock shield-moon bell-ring
gate gate-open valve valve-open valve-closed bullhorn arrow-up arrow-down window-shutter-alert
home-export-outline account-arrow-right volume-high speaker-play lamps security home-thermometer multimedia
alarm-plus account-multiple lightning-bolt wrench pot-steam silverware-fork-knife coffee movie-open sofa book-open-variant
weather-sunset-up home-import-outline party-popper broom brightness-7 brightness-4 countertop bed shower door arrow-left
""".split()

ICON_RE = re.compile(r"^mdi:[a-z0-9-]+$")


def load_profiles() -> dict[str, dict]:
    """Profile table from profiles.py if it imports cleanly, else the fallback."""
    table = {pid: {"id": pid, "name": n, "width": w, "height": h, "dpr": d}
             for pid, (n, w, h, d) in FALLBACK_PROFILES.items()}
    if not (COMPONENT / "profiles.py").exists():
        return table
    try:
        pkg_name = "_wdd_preview_pkg"
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(COMPONENT)]  # load submodules without running __init__.py
        sys.modules[pkg_name] = pkg
        spec = importlib.util.spec_from_file_location(f"{pkg_name}.profiles", COMPONENT / "profiles.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        found = {}
        for pid, p in mod.PROFILES.items():
            found[pid] = {"id": pid, "name": p.name, "width": p.width, "height": p.height,
                          "dpr": getattr(p, "dpr_hint", 1.0)}
        return found or table
    except Exception as err:  # noqa: BLE001 - preview must still build
        print(f"note: profiles.py not importable ({err!r}); using the table from contracts.md")
        return table


def collect_icons(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            collect_icons(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_icons(v, out)
    elif isinstance(obj, str) and ICON_RE.match(obj):
        out.add(obj)
    elif isinstance(obj, str) and "mdi:" in obj:  # icons inside markdown, e.g. <ha-icon icon="mdi:x">
        out.update(re.findall(r'icon="(mdi:[a-z0-9-]+)', obj))


def mdi_var(icon: str) -> str:
    return "mdi" + "".join(part[:1].upper() + part[1:] for part in icon[4:].split("-"))


def resolve_icons(wanted: set[str]) -> dict[str, str]:
    icons: dict[str, str] = {}
    if ICONS.exists():
        icons = json.loads(ICONS.read_text(encoding="utf-8"))
    missing = sorted(i for i in wanted if i not in icons)
    if missing and MDI_JS.exists():
        src = MDI_JS.read_text(encoding="utf-8")
        paths = dict(re.findall(r'export var (mdi\w+) = "([^"]+)"', src))
        for icon in missing:
            path = paths.get(mdi_var(icon))
            if path:
                icons[icon] = path
            else:
                print(f"warning: {icon} is not in @mdi/js")
        ICONS.write_text(json.dumps(dict(sorted(icons.items())), indent=1) + "\n", encoding="utf-8")
    elif missing:
        print(f"warning: {len(missing)} icons missing and @mdi/js not installed: {', '.join(missing[:8])}")
    return {k: v for k, v in icons.items() if k in wanted}


def profile_for(stem: str, dashboard: dict, profiles: dict[str, dict]) -> dict | None:
    """Profile for a golden named <profile_id>.json or <profile_id>@<variant>.json."""
    base, _, variant = stem.partition("@")
    if variant:
        prof = profile_for(base, dashboard, profiles)
        if prof is None:
            return None
        return {**prof, "id": stem, "base": base, "variant": variant, "name": f"{prof['name']} · {variant}"}
    meta = dashboard.get("_profile") or dashboard.get("profile")
    if isinstance(meta, dict) and meta.get("width") and meta.get("height"):
        return {"id": stem, "name": meta.get("name", stem), "width": int(meta["width"]),
                "height": int(meta["height"]), "dpr": meta.get("dpr_hint", 1.0)}
    m = re.search(r"(\d{3,4})x(\d{3,4})", stem)
    if m:
        return {"id": stem, "name": f"Custom {m[1]}×{m[2]}", "width": int(m[1]), "height": int(m[2]), "dpr": 1.0}
    if stem == "custom":
        w, h = custom_size()
        return {"id": stem, "name": f"Custom size ({w}×{h})", "width": w, "height": h, "dpr": 1.0}
    if stem in profiles:
        return dict(profiles[stem])
    return None


def custom_size() -> tuple[int, int]:
    """Size dump_goldens.py renders the "custom" golden at (default 800x480)."""
    dump = HERE / "dump_goldens.py"
    if dump.exists():
        m = re.search(r"^CUSTOM_SIZE\s*=\s*\((\d+),\s*(\d+)\)", dump.read_text(encoding="utf-8"), re.M)
        if m:
            return int(m[1]), int(m[2])
    return 800, 480


def build(source: Path, out: Path) -> Path:
    profiles = load_profiles()
    order = list(profiles)
    entries = []
    for path in sorted(source.glob("*.json")):
        if path.name in ("states.json", "areas.json"):
            continue
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        prof = profile_for(path.stem, dashboard, profiles)
        if prof is None:
            print(f"skip {path.name}: unknown profile and no WxH in the file name")
            continue
        prof["dashboard"] = dashboard
        entries.append(prof)
    if not entries:
        raise SystemExit(f"no dashboards found in {source}")
    def sort_key(p: dict) -> tuple:
        base = p.get("base", p["id"])
        return (order.index(base) if base in order else len(order), base, p.get("variant", ""))

    entries.sort(key=sort_key)

    states_path = source / "states.json"
    states = json.loads(states_path.read_text(encoding="utf-8")) if states_path.exists() else {}
    # Optional area registry for the area card: {area_id: {name, icon, temperature_entity_id, ...}}.
    areas_path = source / "areas.json"
    areas = json.loads(areas_path.read_text(encoding="utf-8")) if areas_path.exists() else {}

    wanted = set(f"mdi:{n}" for n in BASE_ICONS)
    collect_icons([p["dashboard"] for p in entries], wanted)
    collect_icons(states, wanted)
    collect_icons(areas, wanted)
    icons = resolve_icons(wanted)

    data = {
        "profiles": entries,
        "states": states,
        "areas": areas,
        "icons": icons,
        "source": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else str(source),
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    blob = blob.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE.name} lacks the {PLACEHOLDER} marker")
    html = template.replace(PLACEHOLDER, f"window.PREVIEW_DATA = {blob};", 1)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html.encode('utf-8')) / 1024:.0f} KiB, {len(entries)} profiles, "
          f"{len(icons)} icons, source {data['source']})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, help="folder with <profile_id>.json and states.json")
    ap.add_argument("--out", type=Path, default=HERE / "preview.html")
    args = ap.parse_args()
    source = args.source
    if source is None:
        has_goldens = DEFAULT_SOURCE.exists() and any(
            p.name not in ("states.json", "areas.json") for p in DEFAULT_SOURCE.glob("*.json"))
        source = DEFAULT_SOURCE if has_goldens else DEV_SAMPLE
        if not has_goldens:
            print(f"no goldens in {DEFAULT_SOURCE.relative_to(ROOT)}; using {DEV_SAMPLE.relative_to(ROOT)}")
    build(source.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
