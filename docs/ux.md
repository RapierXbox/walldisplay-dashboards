# Wall display UX rules

What a generated wall-panel dashboard must feel like, and what that means for the generator.
Target: Home Assistant 2026.10 (frontend 20260930.x). Every card and option named here exists
in that release; where a rule needs new generator input, it says so. `docs/contracts.md`
stays the source of truth for module APIs. Section C lists where this file overrides
"Design rules v2".

## The usage model

A wall panel is a light switch with a screen. It hangs next to the door at 1.3–1.5 m and is
used from 0.5–2 m away for 2–5 seconds at a time, by everyone: adults, kids, guests and the
cleaner, often with wet or full hands. Nobody reads it. People glance at it ("is anything on
or open, how warm is it, what time is it") or hit one thing ("lights off") and walk on. It is
on 24/7, dims at night, and nobody but the admin ever configures it. So it must be readable at
a glance, safe against stray taps, the same every day, and good with zero setup.

## A. Principles

**U1. The room lights come first.** The panel replaces the switch it hangs next to, and its
most common job is light on or off.
Generator: `TILE_DOMAIN_RANK` light > cover > fan > switch/input_boolean. Other domains appear
on Home only when their page is off (v2.2). With 2 or more lights, the room card (U9) also
gets an "all lights" button.

**U2. One control per entity. Information may repeat.** An entity is *controlled* in exactly
one place. A read-only value, such as the room temperature in the status area or on the pill,
may also appear elsewhere. The owner wants no thermostat tile on Home, yet "how warm is it" is
the most common glance question and should not need a tap.

**U3. One room temperature, from one source.** The first of these that exists:
(1) the area's designated sensor (area registry `temperature_entity_id` /
`humidity_entity_id`), (2) the primary climate entity's `current_temperature`, (3) the first
area temperature sensor, (4) the display's own sensor.
Why: the Heat page now shows the thermostat's 20.5 °C next to a "Temperature 21.3 °C" tile.
Two numbers for one room make people doubt both. Wall displays read warm because the screen
heats the sensor, so their sensor comes last.
Generator: change the `room_sensors()` order. On the Heat page, the side column shows no
second temperature, only humidity and any extra climate entities.

**U4. Tap targets are at least one grid row.** A primary control is at least 56 px high and
96 px wide, about 10 mm on the 4" Shelly, the minimum for a finger at arm's length. The
built-in feature buttons (about 42 px) are only allowed as secondary controls inside tiles of
2 or more rows. The pill items stay 76 × 56.

**U5. Big, but not huge.** Tiles grow to fill the space, capped at **6 card columns × 2 rows
on square and portrait, 3 rows on landscape and tablets** (vertical tiles). Rows left over go
to the status area (larger clock, forecast), never to giant tiles. A 300 px tile with a 36 px
icon floating in the middle reads as broken (portrait Home, square Scenes in the current
preview).
Generator: `tile_rows = min(fill, cap)`. The status/info area takes the remainder.

**U6. Every row is exactly full.** In every row, the column spans add up to `card_columns`
exactly. Today 960×480 Home uses 9 + 7 + 7 = 23 of 24 and leaves a gap. Choose
`info_columns` so that `card_columns - info_columns` divides evenly by the tiles per row
(24 → 8 + 2×8 or 6 + 3×6). A layout test asserts it for every profile.

**U7. The layout never moves on its own.** Tile positions depend only on configuration, never
on state or time of day. Unavailable entities keep their slot. People find "the second tile" by
muscle memory, and a reflow causes wrong taps. Conditional (`visibility`) cards appear only in
the one alert slot (U10), and they all have the same size.

**U8. Safe by default: nothing dangerous on one tap.** Locks, alarm panels, valves, sirens and
covers with `device_class` `garage`, `gate` or `door` are **not** added automatically. If
pinned, each becomes a status tile: tap opens more-info, no icon action, no features.
Why: anyone inside the house, including kids and visitors, can reach the panel. HA makes the
tile *icon* a toggle for toggle domains (`getEntityDefaultTileIconAction`). Today the generator
also sets `tap_action: toggle` on every cover, so a stray tap opens the garage. The
`lock-commands` feature acts with no confirmation.

**U9. The room card summarises the room.** On landscape (info column) and portrait (under the
clock), one native `area` card replaces the Indoor and Humidity tiles:
`{type: area, area, display_type: compact, sensor_classes: [temperature, humidity],
alert_classes: [window, door, moisture], features: [{type: area-controls, controls}],
features_position: bottom}`, 2 rows.
`controls` = `light` (2 or more lights), plus any of `cover-blind`, `cover-shade`,
`cover-curtain` or `cover-shutter` that are present, at most 3. Never `switch` (outlets
include fridges), never `cover-garage`, `cover-gate` or `cover-door`.
Why: one card gives the room name, its temperature and humidity and an open-window badge, and
it does "everything off". `area-controls` turns all off if any is on, otherwise all on, which
is right for a master switch. The card's default `tap_action` is `none`.

**U10. One alert slot, at the top right.** The right-hand slot of the status strip (on
landscape, the top of the info column) shows the most important active alert, otherwise the
weather. The candidates, in this order: `binary_sensor` with device_class `smoke`,
`carbon_monoxide`, `gas` or `moisture` *anywhere in the house*, then `door`, `garage_door`,
`window` or `opening` *in this area*. At most 6.
- Alert card *i*: `{type: alert, entity: e_i, pulse: <true for smoke/CO/gas/moisture>}` with
  `visibility: [{condition: state, entity: e_i, state: "on"}]` plus, for every j < i,
  `{condition: state, entity: e_j, state_not: "on"}`.
- The weather card has `visibility` `state_not: "on"` for every e_i.

Exactly one card is ever visible, all with the same `grid_options`, so nothing reflows. Tapping
an alert opens more-info.
Why: "the bathroom window is open" and "water leak" are what a panel by the door should say
unasked, and house-wide safety alarms belong on every panel.
Generator: needs new input `alert_sensors: tuple[EntityInfo, ...]` (a lead change).

**U11. The status area: time, weather, room.**
- Square 480: one row only, clock (6 columns, `small`, short date) and the alert/weather slot
  (6 columns). No third card: it forces the weather to truncate to "Partly cloud…". The room
  temperature goes on the pill (U13) or, with no climate page, into the room card on larger
  screens.
- Portrait: clock `large` with long date (6 × 2) and alert/weather (6 × 2), then the room card
  (12 × 2).
- Landscape: clock, alert/weather, room card, then a `weather-forecast` card (`show_current:
  false, forecast_type: hourly`, 2 rows) if 3 or more rows are left.
- The weather tile is `name` = localised "Outside" with
  `state_content: [temperature, state]`. With the number first, truncation cuts the condition
  and keeps the temperature.

**U12. Short, unique, local labels.** Names drop the area prefix (already done). If that makes
names equal within a view (two "Speaker"s), both keep their full name. Generated labels (nav,
Outside, Volume, More) follow the HA language: the owner's HA is German, but the nav says
"Home | Heat". The default nav label for climate is "Climate", because many homes also cool.
Generator: `GeneratorInput.language` (`hass.config.language`), a label table (en, de, fallback
en), and a de-dupe pass.

**U13. The nav pill shows live state.** A pill item may name an entity. The Climate item then
shows the room temperature as its label ("21.5°") and tints its icon while heating or cooling.
The Media item tints its icon while the room player is `playing`. This brings back the glance
information removed from Home (U2) without a duplicate control. With only one page, there is
no pill: one item is a dead button that costs a row. The pill has its own fixed shadow plus a
1 px `--divider-color` outline, *not* `--ha-card-box-shadow`, because themes that set that to
`none` make the pill vanish into the page.

**U14. Icons come from the entity, colours from HA.** Never replace an entity's icon with a
generic one. Scenes and scripts become `tile` cards, so HA shows `mdi:pot-steam` and not seven
`mdi:palette`s. Never set `color` on tiles: HA state colours (active coloured, inactive grey)
are the one consistent signal, and the state text keeps colour from being the only cue.

**U15. A single tap does the common thing. More-info is the escape hatch.** Body tap toggles
lights, fans, switches, input_booleans and window covers. Hold opens more-info, which guests
never discover. So tiles of 3 or more rows get inline features: `light-brightness` for dimmable
lights, `cover-open-close` for covers. Square 480 never gets them.

**U16. The main control must stay usable at small sizes.** HA's thermostat shows its −/+
buttons only when the dial is at least 250 px wide (`ha-state-control-climate-temperature`,
size class `lg`), and the dial is limited by the card height. A target you can only set by
dragging a small arc is unusable at 2 m. Rule: the thermostat card gets features only while
its dial keeps 250 px or more. Otherwise the features are dropped (square) or moved to a side
tile (landscape). Mode changes are rare; −/+ is the daily action. In the same way,
`media-control` (no `getGridOptions`) must never be squeezed: give it `rows: "auto"` and budget
its measured natural height.

**U17. Nothing is silently dropped.** If more Home items exist than fit, the last slot becomes a
`shortcut` "+N more" that navigates to a `more` view. That view lists the rest as 1-row tiles.
It is not in the pill. Home holds at most 12 tiles even on tablets: past that a glance turns
into a search.

**U18. Empty is fine; blank is not.** A room with no controllable entities still gets Home:
a large clock, the alert/weather slot and the forecast. Show no "no devices" text, because
guests see it. Instead, raise a repair issue for the admin. A page is created only if it has
something to show, and a Scenes page needs **3 or more** scenes. With 1–2 scenes they stay on
Home as tiles, because two lonely buttons do not earn a pill slot.

**U19. Always on, calm at night, back to Home.** The 60 s idle return also closes more-info
(already done). At night the panel uses HA's dark mode, so a dark hallway gets no big white
cards. Brightness belongs to the device (the Shelly screensaver and backlight).

**U20. Zero setup; overrides only for exceptions.** The flow asks for the display model. The
area defaults to the display device's area. Weather, pages, order and sensors are automatic.
Options stay: pinned, hidden, pages, idle, kiosk. Hallway and kitchen panels differ by their
area's content, plus at most one "role" switch (see the open decisions).

## B. Changes to the generator (prioritised)

**P0: safety, correctness, visible defects**

- **P0-1 Safety domains (U8).** Remove `lock` from `TILE_DOMAIN_RANK`. Add
  `SECURE = {lock, alarm_control_panel, valve, siren}` plus covers with device_class in
  `{garage, gate, door}`. They are never auto-added. When pinned: `tile` with
  `tap_action: {action: more-info}`, `icon_tap_action: {action: none}`, no features.
  `TOGGLE_DOMAINS` stops applying to those covers.
- **P0-2 Scenes and scripts as tiles (U14, preview issue 1).** Replace `action_shortcut` with
  `{type: tile, entity, vertical: true, hide_state: <scene>, tap_action: A, icon_tap_action: A,
  hold_action: {action: none}}`, where
  `A = {action: perform-action, perform_action: scene.turn_on|script.turn_on, target: {entity_id}}`.
  Scripts keep their state ("Running"). Scenes page: tiles at most 2 rows high, 2 per row for
  up to 4 scenes and 3 per row above that, top-aligned. The leftover space sits above the pill.
- **P0-3 Tile cap (U5)** and **exact row sums (U6, issue 3)**, both with tests over all profiles.
- **P0-4 Thermostat keeps −/+ (U16, issue 2).** Square: thermostat at all R rows, **no
  features**. Landscape at R ≤ 6: thermostat at R rows with no features, and the side column
  gets a tile `{entity: climate, name: <"Mode">, hide_state: true, features:
  [{type: climate-hvac-modes, style: icons, hvac_modes}]}`. Larger screens keep the features on
  the card. Check in the sandbox that the dial reaches the `lg` class (250 px or more) at 480
  and 960×480.
- **P0-5 Media fits (U16, issue 4).** `media-control` uses `grid_options: {columns: full,
  rows: "auto"}`. Budget its rows from the height measured in the sandbox at each width. Below
  it: the volume tile (`name: "Volume"`, `icon: mdi:volume-high`, so the player name is not
  repeated). Extra players go next to the volume tile only if a row is free; otherwise a
  "+N more" (U17).
- **P0-6 One room temperature (U3).** Read the area's `temperature_entity_id` /
  `humidity_entity_id` in `collect_input` and apply the new order. No second temperature on the
  Heat page.
- **P0-7 Square strip = 2 cards and a weather label that fits (U11, issue 5).** Labels are
  de-duplicated (U12).

**P1: the experience upgrades**

- **P1-1 Alert slot (U10)**, with the new `alert_sensors` input.
- **P1-2 Live pill (U13).** Items get an optional `entity`. No footer when Home is the only
  page; `available_rows` then gains the footer band back (re-measure). Pill shadow and outline
  independent of the theme (issue 6).
- **P1-3 Room card (U9)** on landscape and portrait.
- **P1-4 "+N more" view (U17)**, Home capped at 12 tiles.
- **P1-5 Localised labels (U12)**, with "Climate" instead of "Heat".
- **P1-6 Inline features on tiles of 3 or more rows (U15).** On larger Heat pages:
  `climate-hvac-modes` (`style: icons`) and `climate-preset-modes` (`icons` for up to 4 presets,
  else `dropdown`).
- **P1-7 Forecast fill (U11)** when the status/info area has 3 or more spare rows.
- **P1-8 Scenes page threshold (U18)** and the empty-room repair issue.
- **P1-9 Default area = the display device's area** (owner: config flow).

**P2: later**

- **P2-1** Night dark mode while `sun.sun` is `below_horizon` (frontend module).
- **P2-2** Entrance role (if approved): open doors and windows house-wide, `person` tiles with
  `show_entity_picture`, "All off"/"Away", and read-only lock and alarm state.
- **P2-3** User-picked extra alerts (washer done, mail) appended to the U10 chain.
- **P2-4** Light groups: a `light` group covering all room lights replaces the individual tiles.
  Needs `members` in `EntityInfo`.
- **P2-5** A `media-player-source` feature for players with 2 or more sources, when space
  allows.

Not doing, on purpose: time-of-day reordering or "smart" suggestions (breaks U7); heading badges
for status (too small at 2 m); the `toggle-group` card (only its icon is tappable and it has no
card background); the `lock-commands` feature (no confirmation); the `target-temperature`
feature on the thermostat card (not in that card's supported feature list).

## C. Changes to Design rules v2

1. **v2.1 pill:** add the optional `entity` on items (U13). No pill for a single page. Labels up
   to 8 characters (the pill does not truncate like the old shortcut grid did). "Heat" becomes
   "Climate", localised. Use a theme-independent shadow and outline.
2. **v2.2:** say "one *control* per entity". Read-only values may repeat (U2).
3. **v2.3 Heat:** features only while the dial keeps −/+ (U16), and no second room temperature
   (U3). **Media:** `rows: "auto"` for media-control, and the volume tile is named "Volume".
   **Scenes:** tiles, not shortcuts, capped at 2 rows; the page only from 3 scenes up.
4. **v2.4:** add the size cap (U5) and exact row sums (U6). "No empty half screen" is met by
   growing the status area, not the tiles.
5. **v2.5:** square = clock + one alert/weather slot, no Indoor tile. Landscape and portrait use
   the room card instead of the Indoor/Humidity tiles (U9, U11).
6. **Contract shape:** "overflow is cut" becomes "+N more" (U17). Locks leave the default domains
   (U8).

## Open decisions for the product owner

1. **Locks, alarm and garage:** hidden unless pinned, and then status only (tap opens
   more-info). *Recommended: yes.*
2. **Hallway/entrance panels:** one option, "Role: Room | Entrance", where Entrance adds the
   house-wide status and leave-home actions (P2-2). *Recommended: yes, default Room.*
3. **House-wide scenes:** scenes with *no* area (Good night, Away) on every Scenes page after
   the room's own. Area-less scripts stay excluded, because many are technical helpers.
   *Recommended: yes for scenes, no for scripts.*
