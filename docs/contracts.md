# Contracts between modules

Read this before touching code. `const.py` and `models.py` are the shared contract; do not change them without the lead's agreement. If you need something new, add it to your own module.

Target: Home Assistant 2026.10 (frontend 20260930.x), Python 3.14.

## Architecture in one paragraph

Each config entry is one wall display. On setup the integration makes sure a storage-mode Lovelace dashboard exists at `/<url_path>` (`url_path` = `wall-<slug>`). That dashboard's stored config contains only

```json
{"strategy": {"type": "custom:wall-display", "entry_id": "<entry_id>"}}
```

The frontend module (`frontend/walldisplay.js`, auto-loaded through `frontend.add_extra_js_url`) defines `ll-strategy-dashboard-wall-display`. Its `generate(config, hass)` calls websocket `walldisplay_dashboards/generate` and returns what Python built. Python owns all layout logic.

## Module ownership

| Module | Owner | Notes |
|---|---|---|
| `const.py`, `models.py`, `docs/contracts.md`, `pyproject.toml`, `tests/conftest.py` | lead | shared, read-only for agents |
| `__init__.py`, `manifest.json`, `dashboards.py`, `websocket.py`, `display_link.py`, `sensor.py`, `repairs.py`, `hacs.json`, `.github/` | backend | |
| `config_flow.py`, `strings.json`, `translations/*.json` | config flow | |
| `profiles.py`, `layout.py`, `entities.py`, `generator/*` | generator | |
| `frontend/walldisplay.js`, `tools/sandbox/*` | frontend | |
| `tools/preview/*` | preview | |

## Python APIs

```python
# profiles.py
PROFILES: dict[str, Profile]                     # keyed by Profile.id
def resolve_profile(profile_id: str, width: int | None, height: int | None) -> Profile
    # "custom" uses width/height; known ids ignore them unless both are given
    # (then it's the measured size adopted via the repair flow, measured=True)

# layout.py (pure)
def compute_grid(profile: Profile) -> Grid

# entities.py (needs hass)
def display_config_from_entry(hass, entry) -> DisplayConfig
def collect_input(hass, display: DisplayConfig) -> GeneratorInput

# generator/__init__.py (pure)
def build_dashboard(data: GeneratorInput) -> dict   # full Lovelace dashboard config {"title", "views": [...]}

# dashboards.py
async def async_ensure_dashboard(hass, entry) -> str   # returns "collection", "panel" or "failed" (url_path owned by someone else); last applied sidebar flag kept in storage "walldisplay_dashboards.dashboards"
async def async_remove_dashboard(hass, entry) -> None

# display_link.py
async def async_push_url(hass, entry) -> str          # returns method used: "elevate_entity" | "elevate_http" | "notification" | "none"
async def async_refresh_display(hass, entry) -> bool
def find_display_sensors(hass, device_id) -> tuple[str | None, str | None]   # (temperature, humidity)
```

Runtime data: `entry.runtime_data` is a `WallDisplayData` dataclass defined in `__init__.py` (`type WallDisplayConfigEntry = ConfigEntry[WallDisplayData]`) with at least `viewport: ViewportReport | None` (last reported, `models.ViewportReport`) and `dashboard_mode: str`.

## Config entry layout

`entry.data`: `name`, `url_path`, `area_id`, `profile`, `width`, `height` (only for `custom` or adopted measurements), `display_device_id` (optional), `display_host` (optional IP/hostname of a ShellyElevate device without the HA integration), `weather_entity` (optional).

`entry.options`: `pages` (list, subset of `climate`, `media`, `scenes`, in nav order), `idle_seconds` (int, 0 = off), `kiosk` (`builtin` | `kiosk_mode` | `off`), `pinned` (list of entity ids of the tile domains, from any room), `hidden` (list), `scene_buttons` (list, max 2; "Favourite scenes", listed first on the Scenes page), `role` (`room` | `entrance`), `show_in_sidebar` (bool, default true), `climate_entities` (list of climate entity ids from any room; if set they drive the Climate page instead of the area's climates, the first is the main thermostat, and the page exists even without a climate in the area; the area's other climates stay on Home), `temperature_entity` / `humidity_entity` (optional sensor entity ids, absent = automatic), `max_home_tiles` (int 0–24, 0 = as many as fit; otherwise Home has at most that many slots, the last one "+N more" when entities are left over), `include_display_entities` (bool, default false: entities of the `display_device_id` device are no tiles and are excluded from the room card unless pinned).

Room temperature and humidity (`generator.room.room_temperature` / `room_humidity`), per class: the `temperature_entity` / `humidity_entity` option, else the area registry's `temperature_entity_id` / `humidity_entity_id`, else the display device's sensor (`find_display_sensors`), else the first visible area sensor of that class. Used by:
- Home's Indoor tile (below): the room temperature, else the room humidity. The room card (HA's `area` card) can't be pointed at an entity and averages the area's sensors, so it always has `sensor_classes: []` (name, alert badges and room controls only; `exclude_entities` = the display device's own entities). The indoor value shows once, from one source (U3, design pass 3);
- the Climate page side info: humidity always, temperature only when the option is set (otherwise the thermostat shows it, U3);
- the nav pill: with the temperature option, the Climate item carries `temperature_entity` and shows that sensor's value instead of the climate's current temperature.

Tile names (`names.clean_name`): the entity's own name (registry name, original name, else friendly name) without the area name and the area's floor name, as whole words anywhere and in any case; dangling separators are dropped and spaces collapsed; a name that would become empty is kept as it is.

`unique_id` = `url_path`.

## Websocket commands

All require an authenticated connection. None require admin, because the panel user is a non-admin.

| type | request | response |
|---|---|---|
| `walldisplay_dashboards/generate` | `{entry_id: str}` | the dashboard config dict from `build_dashboard` |
| `walldisplay_dashboards/list` | `{}` | `{displays: [{entry_id, url_path, idle_seconds, kiosk, home: "home", rows: int, footer: bool, views: {<path>: {rows: int, footer: bool}}}]}`, from `generator.dashboard_budget(data, dashboard)`. `rows`/`footer` describe Home; `views` has one entry per generated view (the More view can have the pill when Home has none). `footer`: the view has the nav footer; `rows`: `layout.compute_grid(profile, footer).rows`. If building fails: Home only, footer guessed from the `pages` option. |
| `walldisplay_dashboards/report_viewport` | `{entry_id, width: int, height: int, dpr: float, user_agent: str, device?: str}` | `{profile_width, profile_height, matches: bool}` |

Unknown `entry_id` → error code `not_found`.

## Generated dashboard shape

- Every view: `type: sections`, `max_columns: grid.section_columns`, `top_margin: false`, `footer: nav_footer(...)`.
- View paths: `home`, `climate`, `media`, `scenes`. `home` is first. The footer contains one shortcut card per page with **relative** `navigation_path` (`"home"`, not `"/wall-kitchen/home"`).
- Nav labels are localised by the generator (English fallback `const.NAV`: `Home | Climate | Media | Scenes`), max 8 characters; the pill shows a climate's current temperature instead of its label.
- Home tiles: `type: tile`, `vertical: true` when `tile_rows == 2`. Toggleable domains get `tap_action: toggle` and `hold_action: more-info`. Scenes and scripts become `type: shortcut` cards with `perform-action` (`scene.turn_on` / `script.turn_on`).
  - Square 480 (design pass 3, owner decision "big up to 6, then list"): up to 6 controls are big vertical tiles (3 × 2 grid at 4 × 2 or 2 × 2 at 6 × 2). More than 6 become a compact 2-column list of 1-row horizontal tiles (6 columns each, a lone last tile spans the row): 7–8 with the 2-row strip (and the Indoor tile), 9–10 with a 1-row strip, beyond that 9 tiles plus "+N more". A `max_home_tiles` of 6 or less keeps big tiles, the last slot "+N more". Other profiles keep the fill rules (rule 4 below).
- Status strip (square/portrait): clock card (`clock_size: small`, `no_background: true`) and a weather tile, 1 row.
  - Indoor climate (design pass 3): when a room temperature (else humidity) is known (precedence above), Home shows the Indoor tile, the twin of the weather tile: `{type: tile, entity: <room temperature>, name: "Indoor"/"Innen", icon: mdi:home-thermometer-outline, tap_action: more-info, icon_tap_action: none}` (a climate entity as the source adds `state_content: [current_temperature]`; a humidity-only room uses the humidity sensor with `mdi:water-percent`). Temperature only (owner decision): humidity stays on the Climate page and in more-info. Square/portrait: the clock spans the strip on the left; the right half stacks the weather tile over the Indoor tile (6 × 1 each in a 2-row strip; an odd height gives the extra row to the weather). A 1-row strip (more than 8 controls on 480) has no Indoor tile. Landscape: the Indoor tile follows the weather tile in the info column, vertical like it from 8 rows, before the room card.
- Info column (landscape): clock, date, weather, the Indoor tile, the room card (no sensor values), the forecast when rows allow. It takes `info_columns` card columns.
- Heat page: one tile per climate entity with feature `target-temperature`.
- Media page: tiles with `media-player-playback` (prev/play-pause/next) and `media-player-volume-slider`, `features_position: inline` where width allows.
- Scenes page: shortcut cards; the display's area first.
- Nothing may exceed `grid.rows`. Overflow is cut and logged at debug level.

## Design rules v2 (user feedback round 1, supersedes the shape above where they conflict)

1. **Nav = floating pill.** The footer is `{"card": {"type": "custom:wall-display-nav", "items": [{"path": "home", "label": "Home", "icon": "mdi:home"}, ...]}, "max_width": <px>}`. The card is defined in `frontend/walldisplay.js`:
   - one rounded capsule (border-radius = height / 2), centred, card background with a soft shadow;
   - each item shows its icon above its short label (11–12 px);
   - the item whose `path` equals the current view path (last URL segment) is filled with a tint of `--primary-color` and its icon/label take `--primary-color`;
   - tapping pushes `/<dashboard>/<path>` and fires `location-changed`;
   - `getGridOptions()` → `{columns: "full", rows: 1}`; height 56 px;
   - pill width ≈ 76 px per item + 8 px padding, never wider than the screen minus 16 px.
2. **Every entity appears in exactly one place.** Domains that have a page enabled are removed from Home:
   - `climate` → Heat;
   - `media_player` → Media;
   - `scene` + `script` → Scenes.

   If that page is disabled in the options, or doesn't exist, the entities stay on Home.
3. **Pages are room-scoped,** using the display's area only, not the whole house, and full-screen. A page exists only if the area has entities for it AND it is enabled in options. Nav order: Home, Heat, Media, Scenes.
   - **Heat:** the area's primary climate entity (pinned first, else first) as a native `thermostat` card filling the available rows. Add feature `climate-hvac-modes` (with the entity's hvac_modes) when it has more than one mode, and `climate-preset-modes` when it has presets and the space allows.
     - Square: the thermostat takes all R rows × full width.
     - Landscape: thermostat about ⅔ wide × R rows; the side column holds the room's temperature/humidity sensors (display sensors or area sensors) plus any additional climate entities in the area as tiles. Tapping a tile opens more-info.
     - Portrait: thermostat on top, extras below.
   - **Media:** the area's primary media player as a native `media-control` card (artwork, title, transport controls) filling most rows, plus a tile with `media-player-volume-slider` underneath (1 row, `hide_state`, inline). Additional players in the area become small tiles that open more-info; in landscape they go in a side column.
   - **Scenes:** the area's scenes and scripts as big `shortcut` cards (vertical, icon + label) filling the screen in a 2- or 3-column grid; pinned/scene_buttons first.
4. **Home tiles scale to fill the space.** With n tiles, choose the grid (tiles per row × tile rows) that best fills the tile area: prefer square-ish tiles, a tile height ≥ 2 rows when possible, and no empty half screen. On square 480 with 4 tiles that's 2×2 at 6 columns × 2 rows. On landscape/XL the tiles get taller and wider. Vertical tiles for ≥ 2 rows.
5. **Info column (landscape) / status strip:** clock with date, weather, indoor temperature/humidity. No scene buttons when the Scenes page exists.

## Design rules v3 (round 2 feedback; supersedes v2 where they conflict)

The product owner approved changes from `docs/ux.md`, with these decisions:

- **Adopt:**
  - ux.md B **P0-1 … P0-7**, with one change to P0-1 (below);
  - **P1-2** live pill;
  - **P1-3** room card;
  - **P1-4** "+N more" page (`PAGE_MORE`, path `more`);
  - **P1-5** localised labels;
  - **P1-6** inline features on big tiles;
  - **P1-7** forecast fill;
  - **P1-8** scenes threshold and empty-room repair;
  - **P1-9** default area from the display device;
  - **P2-2** entrance role;
  - the ux.md section C edits to v2.
- **Not now:** P1-1 alert slot, P2-1, P2-3, P2-4, P2-5.
- **Security, changing P0-1:** locks, alarm panels, valves, sirens and garage/gate/door covers ARE auto-added from the room (lowest rank). They are always **status-only**: `tap_action: more-info`, `icon_tap_action: none`, `hold_action: more-info`, no features. Constants: `const.SECURE_DOMAINS` and `const.SECURE_COVER_CLASSES`.
- **Role option:** `CONF_ROLE`, `room` (default) or `entrance`, stored in options.
  - Entrance adds house-wide status to Home: `person` tiles; lights left on and open doors/windows as counts; read-only lock and alarm state.
  - It also adds leave-home actions: an "All off" script/scene if one exists, plus area-less scenes such as Away.
  - This needs an `entrance` input. The generator agent defines the extra GeneratorInput fields (defaults only) and `entities.collect_input` fills them.
- **Area-less scenes** (no area) appear on every Scenes page after the room's own. Area-less scripts don't.
- **Language:** the generator gets the HA language (`hass.config.language`, passed in `DisplayConfig`? No: add `language: str = "en"` to GeneratorInput) and localises every label it writes, with English and German shipped: nav labels, "Outside", "Volume", "More", "Indoor" and so on. The frontend localises nothing it receives.
- **Nav pill v3:** items may carry `entity`. The card shows a climate's current temperature as the item label (e.g. "21.5°") and lights up a media player's item while `playing`. If Home is the only page, there's no footer and the row budget gains the footer band (R recomputed without the 96 px band; still keep 12 px bottom margin). The shadow and outline don't depend on theme variables.
- **SPIKE facts (measured):**
  - a `vertical-stack` does NOT fill grid rows; use a `grid` card with `columns: 1`, or individual cards;
  - section widths are capped at 500 px per column;
  - 960 → 2 columns, 1280 → 3.

## Layout budget

**Layout budget (HA 2026.10, with the walldisplay.js spacing CSS).** The view's row gap is
12 px (top padding, bottom padding, the footer's sticky offset), the side padding is 12 px
above 600 px wide and 8 px at or below, and the card gutter is 8 px. With the pill footer, the
first row is at y = 12, the footer box spans H−84 … H−12, and the grid ends 16 px above the pill.
Rows: `R = floor((H − 96) / 64)` with a footer, `floor((H − 16) / 64)` without
(480 → 6, 752 → 10, 800 → 11, 960 → 13, 1280 → 18; 480 without a footer → 7). The row height is
stretched by walldisplay.js to `(H − 96)/R − 8` (no footer `(H − 16)/R − 8`), clamped 48–72
px, so generators reason in rows, never in pixels of height. Section columns:
`C = clamp(floor((W − g) / (320 + g)), 1, 3)` with g = 8 at ≤ 600 px wide, else 12.
`walldisplay_dashboards/list` returns `rows` and `footer` per display.

## Display profiles (CSS px; best guesses until measured on a device)

| id | name | W×H | DPR hint |
|---|---|---|---|
| `shelly_wall_display` | Shelly Wall Display (4") | 480×480 | 1.0 |
| `shelly_x1i` | Shelly Wall Display X1i | 480×480 | 1.5 |
| `shelly_x2_landscape` | Shelly Wall Display X2 / X2i, landscape | 960×480 | 1.5 |
| `shelly_x2_portrait` | Shelly Wall Display X2 / X2i, portrait | 480×960 | 1.5 |
| `shelly_xl` | Shelly Wall Display XL / XLi | 1280×752 | 1.0 |
| `nspanel_pro` | Sonoff NSPanel Pro | 480×480 | 1.0 |
| `tablet_landscape` | Tablet, landscape (8–10") | 1280×800 | 1.0 |
| `tablet_portrait` | Tablet, portrait (8–10") | 800×1280 | 1.0 |
| `custom` | Custom size | user | — |
