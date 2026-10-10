# Visual design review (round 1)

Scope: everything visual except spacing (see `docs/design-spacing.md`, approved; this builds on
its 12 px frame and stretched rows). Basis: sandbox HA 2026.10.0 / frontend 20260930.x, light and
dark, all profiles plus `@de` and `@entrance`, and the preview mockup. Before/after shots:
`tools/sandbox/out/design/review.html`, made with `tools/sandbox/design/proto.mjs`, which emulates
the approved spacing and measures font sizes and truncation. Everything uses native cards and
options, or our own `walldisplay.js`. Card options and CSS properties were checked in the frontend
source at tag 20260930.0.

## Visual direction

The panel should feel like a calm appliance, like a good thermostat or an oven display, and not
like a web page. **Status is type:** the clock, date and outside temperature are large, quiet and
never tappable. **Controls are cards:** every tile is the same shape, and an icon in a tinted
circle means "you can press this". Colour carries state only (HA state colours). The accent
(`--primary-color`) marks only "where am I" in the pill. **No text under 14 px.** At 2 m you see
the time, which lights are on (amber circles) and which page you are on. Dark at night: the
screen is never the brightest thing in the hallway.

## Issues

### P0

**1. Text is too small for a 4" panel.** *Where:* every profile. On the 480 × 480 (≈ 170 ppi at
DPR 1), HA's defaults are tile state and weather 12 px (about 1.8 mm tall), tile names 14 px,
pill labels 12 px, the small clock's date 12 px with AM/PM at 10 px, and the small clock itself
24 px. *Why:* the panel is read at 1–2 m. Every panel we target has about the same pixel density
(150–170 CSS px per inch) and the same viewing distance, so text needs one **fixed** scale, not
a factor from the viewport. Only the *tile width* grows with the screen, and that is handled by
two width steps for tile names. *Mechanism (checked in the source):* `typography.globals.ts`
declares `--ha-font-size-xs … -5xl` on `html` as `calc(Npx * var(--ha-font-size-scale))`. They
resolve there, so setting only the scale lower down changes nothing. The tokens must be
redeclared. Tile text reads `--ha-tile-info-primary/secondary-font-size` (defaults `m`/`s`). The
digital clock reads `--ha-clock-card-digital-font-size-small|medium|large` (24 px /
`calc(48px*scale)` / `calc(64px*scale)`), with its date at `s` (small), `l` (medium) or `2xl`
(large). The thermostat labels use `l`/`m`/`2xl`, the weather forecast `s`/`m`/`l`/`2xl`, and
media-control uses `em` (base 14 px). *Fix (`walldisplay.js`):* extend `LAYOUT_CSS.root` (the
`#view` block in hui-root's shadow root, which already has the spacing variables). Same gating,
so more-info dialogs and HA's own pages are untouched:
```css
#view {
  --ha-view-sections-row-gap: 12px; --ha-view-sections-column-gap: 12px;   /* spacing, as is */
  font-size: 16px;                       /* em-based text: media-control, markdown */
  --ha-font-size-scale: 1.15;            /* clock medium/large and other calc(* scale) */
  --ha-font-size-xs: 12px; --ha-font-size-s: 14px; --ha-font-size-m: 16px; --ha-font-size-l: 18px;
  --ha-font-size-xl: 22px; --ha-font-size-2xl: 26px; --ha-font-size-3xl: 32px;
  --ha-font-size-4xl: 36px; --ha-font-size-5xl: 46px;
  --ha-clock-card-digital-font-size-small: 40px;
}
@media (min-width: 900px)  { #view { --ha-tile-info-primary-font-size: 18px; } }
@media (min-width: 1200px) { #view { --ha-tile-info-primary-font-size: 20px;
  --ha-tile-info-secondary-font-size: 16px; --ha-clock-card-digital-font-size-large: 88px; } }
```
Pill (`NAV_CSS`): `.label { font-size: 14px; line-height: 16px; font-weight: 500; }`. The button
has 46 px inside: 24 px icon + 2 px gap + 16 px label = 42. The temperature label ("21.5°") gets
the same 14/500 and 700 when active (#2).

*Measured in the sandbox (CSS px, before → after):*

| | 480 × 480 | 960 × 480 | 1280 × 752 |
|---|---|---|---|
| tile name / state | 14 / 12 → **16 / 14** | 14 / 12 → **18 / 14** | 14 / 12 → **20 / 16** |
| weather and room card text | 12 → 14 | 12 → 14 | 12 → 16 |
| clock (small strip) / date | 24 / 12 → **40 / 14** | medium 48 / 16 → 55 / 18 | large 64 / 24 → 88 / 26 |
| thermostat name / mode label | 16 / 16 → 18 / 18 | same | same |
| pill label | 12 → **14** | 12 → 14 | 12 → 14 |
| smallest text on screen | 10 (AM) → 12 (AM) | 12 → 14 | 12 → 14 |

*Truncation (480 tile content ≈ 130 px, 960 info column ≈ 162 px):* no English label truncates.
German ones fit too: "Kaffeemaschine", "Geschirrspüler", "Kücheninsel", "Geöffnet · 100 %",
"Medien", "Szenen", "Lautstärke". The limit on 3-up 480 tiles is now about 15 characters
(the 20-character "Arbeitsplattenleiste" now shows an ellipsis; at 14 px it fit). One regression:
in the 960 info column, "14,2 °C · Teilweise bewölkt" no longer fits at 14 px. *Generator rule:*
a horizontal weather tile whose text width (`columns × column_px − 72`) is under 200 px gets
`state_content: ["temperature"]`, because its icon already shows the condition. Elsewhere keep
`["temperature", "state"]` (U11). *Test:* extend `shoot.mjs` from nav labels to every element
with `text-overflow: ellipsis` whose `max-content` width exceeds its box, and add a minimum of
14 px for visible text (AM/PM excepted).

**2. The pill's hierarchy is upside down.** *Where:* every page, worst in light mode. *Why:*
inactive icons use `--primary-text-color`, so they outweigh the active item, which is an 18 %
tint. "Playing" tints the Media icon `--primary-color` and adds a same-blue dot, so it reads as
a second selection. U13's climate tint isn't implemented. *Fix (`NAV_CSS`, plus the label rule
in #1):*
```css
ha-icon { --mdc-icon-size: 24px; color: var(--secondary-text-color); }
button.active { background: color-mix(in srgb, var(--primary-color) 20%, transparent); color: var(--primary-color); }
button.active .label { font-weight: 700; }
button.active ha-icon { color: var(--primary-color); }
.live ha-icon { color: var(--state-media_player-active-color, #03a9f4); }   /* delete .live .icon::after */
.heat ha-icon { color: var(--state-climate-heat-color, #ff5722); }
.cool ha-icon { color: var(--state-climate-cool-color, #2196f3); }
button.active.live ha-icon, button.active.heat ha-icon, button.active.cool ha-icon { color: var(--primary-color); }
.pill { box-shadow: 0 1px 2px rgba(0,0,0,.20), 0 6px 20px rgba(0,0,0,.18); }  /* border unchanged */
```
In `_updateLive()`: while the player is `playing`, swap the icon to `mdi:speaker-play`, so the
cue isn't colour-only, then restore `item.icon`. A climate item gets `heat` or `cool` from
`hvac_action` (`heating`/`cooling`). Without `hvac_action`, use `state === "heat"` and
`current_temperature < temperature`. Add `hvac_action` and `temperature` to the `set hass`
signature. Item size 76 × 56 and the theme-independent border stay.

**3. Some tile icons have a circle and some don't.** *Where:* Home. Lights and switches have
circles, window covers don't. *Why:* `ha-tile-icon` paints its background only when
`interactive`, and the default icon action is `toggle` only for `DOMAINS_TOGGLE`, which doesn't
include cover. *Fix (generator, `cards.entity_card`):* for non-secure covers, set
`icon_tap_action: {action: toggle}`, the same as the body tap. Rule: **circle = pressable**.
Secure tiles, persons, weather and the area card keep plain icons, because they are status.

### P1

**4. The forecast card duplicates the weather.** *Where:* portrait, XL and tablet Home with a
weather entity that has no forecasts. *Why:* `weather-forecast` with `show_current: false`
then renders the current weather at full width, next to "Outside", with the entity name ("Home")
as a stray label. *Fix (generator; lead: `weather_features: int` in `GeneratorInput`):*
`forecast_type: hourly` if `features & 2`, `daily` if `& 1`, otherwise no forecast card (the
rows go back through spacing D4).

**5. The entrance counts look foreign.** The markdown "3 lights on" / "2 open" cards have no tile
layout, sit top-aligned in 2-row slots and use labels we translate ourselves. *Fix
(`cards.count_cards`):* use the native `home-summary` cards (tile look, localised by HA, no
default tap action): `{type: home-summary, summary: light}` and `{type: home-summary, summary:
security, alert_entities: [{entity: <opening>} …]}` ("Lights · 3 on", "Security · 1 warning",
plus lock and alarm status). Drop the `light_on_*` and `open_*` labels.

**6. Scenes all look the same.** UI scenes without an icon give seven `mdi:palette` circles.
*Fix (lead: `icon: str | None` in `EntityInfo`, from `entry.icon or entry.original_icon or
attributes.icon`):* only for `scene`/`script` with **no own icon**, use the first keyword match
on the name (en + de), else `mdi:palette` (U14 holds). cook|koch → `pot-steam`;
dinner|essen → `silverware-fork-knife`; breakfast|frühstück → `coffee`; movie|film|tv|kino →
`movie-open`; relax|entspann → `sofa`; read|lesen → `book-open-variant`;
night|nacht|sleep|schlaf → `weather-night`; morning|morgen → `weather-sunset-up`;
away|abwesend|leave → `home-export-outline`; arrive|ankommen → `home-import-outline`; all
off|alles aus → `power`; party → `party-popper`; clean|putzen → `broom`; bright|hell →
`brightness-7`; dim|gedimmt → `brightness-4` (all `mdi:`).

**7. The media page is a bright blue slab at night.** `media-control` without artwork fills
itself with `--primary-color` (`.no-image`), which makes it the brightest and biggest accent
area on a dark panel. See decision 2.

### P2

**8. The volume tile shows the speaker twice** (tile icon + mute button). Use
`{type: media-player-volume-slider, show_mute_button: false}`. Mute stays in more-info.
**9. The room card shows a placeholder icon:** `area` draws `mdiTextureBox` when the area has no
icon, and the card has no `icon` option. Add a fixable repair, "Give <area> an icon", that
suggests one by keyword (living → `sofa`, kitchen → `countertop`, bed → `bed`, bath → `shower`,
hall|flur → `door`) and writes it only after the admin confirms.
**10. Long names:** horizontal 1-row tiles narrower than 170 px go 2 per row (hand-off to the
spacing pass).
**11. More page:** a lone pill item reads like a stray button. With a single target, use
`icon: mdi:arrow-left` and keep the label.
**12. German:** with #1, #5 and the #1 weather rule, nothing truncates. The date punctuation
comes from HA's `date_format` parts. Leave it.

Checked, keep as is: the background-less clock beside a carded weather tile. Horizontal tiles
in the strip and info column with vertical tiles in the grid. Amber and grey light circles.
Scenes keep their own icons. The thermostat card. The `area-controls` button.

## Dark mode and a night look: what an integration can do

- **Shipping a theme:** no public API. Themes live in `hass.data["frontend_themes"]`, loaded
  only from `frontend: themes:` in YAML, and `frontend.reload_themes` *replaces* that dict, so
  an injected theme vanishes on reload. Writing into another component's data isn't accepted
  practice.
- **Per-view `theme`:** works on sections views, but it can only name a theme the user already has.
- **What we can do natively:** (a) the `#view` variables above, on our dashboards only.
  (b) ux P2-1: for non-admin panel users, `walldisplay.js` fires `settheme` with
  `{dark: sun.sun is below_horizon}` on `home-assistant`. That writes the panel user's theme
  preference (local storage and synced user data, `themes-mixin.ts`). (c) Optionally, a `theme`
  select in the options flow (existing user themes) written to every view. HA's dark palette
  (#111 background, #1c1c1c cards, dark-tuned state colours) is already right for panels.

## Decisions for the product owner

1. **Night look:** *recommended:* no shipped theme. Auto-dark from sunset to sunrise for panel
   users (b), plus the view variables (a). The theme option (c) only if users ask.
2. **Media page card:** `media-control` (current P0-5) or a `tile` with
   `state_content: [media_title, media_artist]`, `features: [{type: media-player-playback},
   {type: media-player-volume-slider}]` and `features_position: bottom`, using the control rows
   plus the volume row. *Recommended:* the tile on ≤ 960 px screens. It's calm in the dark, fits
   any row count without `rows: "auto"` measurements and replaces the volume tile. Keep
   `media-control` on XL and tablets, where artwork earns the space.

## Pass 2: review of the implemented state

Basis: the re-shoot from 10 Oct, 12:31–12:36 (all profiles, `@de`, `@entrance`, `@night`), the
preview, and `walldisplay.js` as live. Prototypes are in `tools/sandbox/out/design2/review.html`.
They inject the live `LAYOUT_CSS` and emulate the approved spacing.

**Answers.** *Type:* balanced. The clock (55–88 px) is clearly the hero. Tile names (16/18/20)
sit one step below. Pill labels at 14/500, with the active one at 700, read as navigation, not
content. Nothing is too heavy, so don't go bigger. *Pill:* right in both themes. Heat orange and
speaker-play are clear, and the active tint stays legible on dark. *Night:* works. The brightest
things left are saturated amber fills (the brightness slider, about 300 × 40 px of `#ffc107`, and
"on" circles) and the near-white clock (P1-3). *German:* no truncation ("Heizbetrieb",
"Draußen 14,2 °C", "Start/Klima/Medien/Szenen"). Nothing to do. *Still generic:* orientation
mix-ups (P0), the placeholder area icon, the thermostat's ⋮, and tall scene cells.

### P0

**P2-1. The entrance mixes orientations.** The `home-summary` cards are horizontal inside a grid
of vertical 2-row tiles ("Lights", "Security"). *Fix (`cards.count_cards` or the summary
builder):* `vertical: true` when the slot has `rows >= 2`, the same rule as `entity_card`.
`home-summary` supports `vertical` (2 rows, min 3 columns).

**P2-2. The media tile floats.** On ≤ 960 px the horizontal tile puts its icon and text
mid-left in an empty 3–5-row area above the controls. *Fix (`media.py`):* `vertical: true` (icon,
name and "title · artist" centred above the controls) and `icon_tap_action: {action:
more-info}`. That gives the icon its circle (circle = pressable) and opens source and grouping
controls.

### P1

**P2-3. Night skin.** *Fix (`walldisplay.js`):* while `autoDark` has applied night (`want ===
true`), set `data-wd-night` on hui-root's `#view` (remove it otherwise and on leave). Add this to
`LAYOUT_CSS.root`:
```css
#view[data-wd-night] { background: #0b0b0b; --ha-card-background: #151515;
  --primary-text-color: #c4c4c4; --secondary-text-color: #8a8a8a; --primary-color: #2a90b5;
  --state-active-color: #c79100; --state-light-active-color: #c79100;
  --state-switch-active-color: #c79100; --state-input_boolean-active-color: #c79100;
  --state-media_player-active-color: #2a8fc0; --state-climate-heat-color: #d9531e; }
```
The state colours resolve on `html` (like the font tokens), so each one must be redeclared:
overriding `--amber-color` does nothing. Lights with an RGB colour keep their own colour.
Measured: mean screen luminance drops 23 % (34 → 26 and 32 → 25 of 255), and the 99th
percentile drops 14 % (209 → 180 and 225 → 196). Text contrast is #c4c4c4 on #151515 ≈ 10.5:1
and #8a8a8a ≈ 5.3:1 (AA). The pill inherits all of it.

**P2-4. The climate "Mode" tile breaks circle = pressable.** It is a control with a plain icon.
*Fix (`climate._mode_tile`):* `icon_tap_action: {action: more-info}`.

### P2

- **P2-5. Scenes on XL and tablets:** tall cells with 36 px icons look empty. I tested horizontal
  tiles and they were worse (the text hugs the left edge), so the cell height is the problem.
  Hand-off to spacing: scene tiles at most 2 rows on large screens too.
- **P2-6. Still open from pass 1:** #9 the placeholder area icon (now the most "generic HA" item
  on every landscape and portrait Home), #8 the double speaker on the XL/tablet volume tile, and
  #11 the lone More pill (no More view in this run).
- **P2-7. The thermostat card's** regular-weight header and ⋮ are native, with no option to hide
  them. Leave them. Its name already equals the room.

### Decisions for the product owner (pass 2)

1. **Night skin** (P2-3: dimmer text, deeper state colours and darker surfaces after sunset, on
   our dashboards only). *Recommended:* yes.
2. **Area icons:** a fixable repair that writes a suggested icon to the area after the admin
   confirms, or leave HA's hatched placeholder. *Recommended:* the repair.
