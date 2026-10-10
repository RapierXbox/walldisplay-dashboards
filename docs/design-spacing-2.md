# Layout pass 2 (after the spacing spec and the design review went live)

Scope: layout, density, filling. Evidence: `tools/sandbox/out/spacing2/compare.html` (13 pairs),
raw rects in `tools/sandbox/out/spacing2/measure.json`. "Live" pairs are today's sandbox
displays; their "after" applies the rules below by hand. The other pairs use the sample house
with a weather entity that has **no forecast** (like the sandbox's `weather.home`), run through the
real generator with the rules patched in (`tools/sandbox/spacing2/gen2.py`). All pairs use the
live walldisplay.js styling: `/list` is extended in the page (`shoot2.mjs`). "Empty" = grid
area covered by no card, with the background-less clock counted as covered.

## Problems (CSS px)

| # | Where | Measured | Cause |
|---|---|---|---|
| 1 | Portrait Home, no forecast | X2: clock 258 px, weather tile **324** px, hole under the clock (66 × 228). Tablet: clock 255, weather **518**, hole 263 × 384 | `clock_rows += spare` asks for 5 and 8 rows; HA's digital clock has `max_rows: 4` and gets clamped, while the weather tile does not |
| 2 | XL / tablet landscape Home, no forecast | 2 rows (132 px) empty under the tiles; 13 % / 18 % of the grid empty | the forecast slot is gone, and `grow_tiles` stops at 4 rows |
| 3 | Media ≤ 960 px, one player | 480: a 464×376 tile, text at the left edge, ~200 px empty above and below the controls. X2 portrait 464×856, tablet portrait 776×1176 | one horizontal tile is given every row |
| 4 | Scenes | gap to the pill: X2 portrait **282**, XL **278**, tablet landscape **336**, tablet portrait **214**; 16–55 % of the grid empty | `MAX_ROWS = 3` |
| 5 | Heat, landscape, one side card | X2 (live): mode tile 184 of 376 px; XL: humidity 3 of 10 rows (23 % empty) | `share_rows` cap of 3 |
| 6 | Entrance (live) | 8 slots at 3 per row: last line has 2 of 3 cells, a 149×249 hole (9 % empty); home-summary cards horizontal among vertical tiles | partial last line not widened; home-summary has no `vertical` |
| 7 | More (busy kitchen, 14 extra lamps) | 1-row tiles: 80 px (480) / 144 px (960) empty, 24 % / 42 % of the grid | `_more_cards` uses `max_rows=1` |

Checked and fine with the bigger type: every report check passes with nothing truncated. The 480
German Home fits ("Geöffnet · 100 %", "Teilweise bewölkt"). The entrance tiles at 149 px fit
"Front door lock". The Heat dial at 480 and 960 is not clipped. Tile heights are the same across each
row, except for the clock/weather pair in #1 and the summary cards in #6. Scenes (3 rows) being
taller than Home tiles (2 rows) at 480 is fine: they are buttons.

## Decisions

- **L1 Clock ≤ 4 rows** (`CLOCK_MAX_ROWS = 4`, HA `hui-clock-card` digital `max_rows`). The weather
  tile next to it always gets the same rows. Portrait clock/weather: 3 rows, 4 only per L2.
- **L2 Spare rows, no forecast.** Portrait: tiles to `GROWN_TILE_MAX_ROWS` (4), then
  clock/weather to 3, then tiles to `TILE_ABSORB_MAX_ROWS` (5), then clock/weather to 4, then the room
  card to `ROOM_MAX_ROWS` (3). Whatever is left stays as bottom margin; that is one row
  on the tablet portrait at most. Landscape: tiles absorb up to 5 rows.
  With a forecast, the existing order stays.
- **L3 Tile growth aspect:** a tile may be up to 1.25× taller than wide
  (`rows_px(r) * TILE_ASPECT_MIN <= width`, `TILE_ASPECT_MIN = 0.8`; was `rows_px(r) <= width`).
- **M1 Media ≤ 960 px:** `player_card` gets `vertical: true`. That centres the icon, name and
  title/artist above the playback and volume rows. Other players stay below.
- **S1 Scenes:** `fill_tiles(..., max_per_row=3, max_rows=6)`, then lower the rows while
  `rows_px(rows) * 0.8 > tile width`. Leftover rows (≤ 2) go to the last line. With U6
  below, that line is full width.
- **C1 Heat, landscape:** exactly one side card → thermostat across the full width at R − 1 rows, and
  the card as a 1-row full-width strip (`features_position: inline`, not vertical). Two or more:
  `share_rows(..., cap=max(SIDE_MAX_ROWS, ceil(R / n)))` so the column always fills.
- **U6 Partial last line:** when the last line of a tile block (Home tiles, Scenes, More) is
  partial and its cards are the same size, they share the block's full width (`width // n`, only
  when it divides). Entrance: `home-summary` gets `vertical: true` when its slot is ≥ 2 rows
  (HA supports it: `rows++`, `min_columns: 3`), like the tiles beside it.
- **R1 More = Home tile rules:** `fill_tiles(n, card_columns, R, column_px,
  max_columns=tile_max_columns(p), max_rows=tile_max_rows(p))`, then `grow_tiles`, then
  `entity_card(e, rows)` (vertical at ≥ 2 rows), then U6.

Result in the prototypes (40 view pairs): every view ends 16 px above the pill and 0 % is empty,
except tablet portrait Home (one spare row: 82 px gap, 5 % empty) and tablet landscape Home (one
row next to the info column, 6 %). Tap targets do not change (rows ≥ 56 px).

## Changes per module

### layout.py
- `TILE_ASPECT_MIN = 0.8`, `TILE_ABSORB_MAX_ROWS = 5`.
- `grow_tiles(fill, spare, column_px, cap=GROWN_TILE_MAX_ROWS)` with the L3 aspect test.
- New `widen_last_line(spans, card_columns, first) -> list[(columns, rows)]`. It uses `pack()` on
  the block's spans (`first` = index of the first tile card) and widens the equal-size cards of the
  last packed row to `(card_columns − start_column) // n`.

### generator/home.py
- `CLOCK_MAX_ROWS = 4`, `ROOM_MAX_ROWS = 3`. `_clock_weather` clamps its rows to `CLOCK_MAX_ROWS`.
- Portrait branch when `_forecast(data) is None`: the L2 order. Never `clock_rows += spare`.
  The room card is sized with its grown rows.
- Landscape branch when `_forecast(data) is None`: after `grow_tiles`, call it again with
  `cap=TILE_ABSORB_MAX_ROWS`.
- Apply `widen_last_line` to the tile slots (the "+N more" shortcut counts as a slot).

### generator/cards.py
- `count_cards` / home-summary: take `rows` and set `vertical: True` when `rows >= 2`
  (the caller knows `tile_rows`).

### generator/scenes.py
- `MAX_ROWS = 6`, the aspect reduction, remainder rows to the last line, `widen_last_line`.

### generator/climate.py
- Landscape: the C1 strip for a single side card; `share_rows` cap as in C1.

### generator/media.py
- `player_card(...)` adds `"vertical": True`; `PLAYER_TILE_ROWS` 3 → **4** (HA's tile
  `getGridOptions`: 1 + 2 feature rows + 1 for vertical; measured at 4 rows/248 px at 480).

### generator/__init__.py
- `_more_cards`: R1.

### walldisplay.js, preview
- walldisplay.js: no change.
- Preview: draw `home-summary` with `vertical` like a vertical tile, and regenerate the goldens.
  Add a sample variant without forecast (`weather_features=0`) and a busy room (≥ 14 lamps) to the
  goldens; #1, #2 and #7 only show up there.

### Tests (generator)
- No card's rows exceed its HA maximum (clock ≤ 4) on any profile or variant.
- Per view: rows used ≥ R − 1. The only exception is the documented spare row of L2.
- The last line of every tile block reaches the right edge of its area.
- The sandbox shoot gets an "empty grid area ≤ 6 %" check; it is the metric used above.

## Open points
1. **Media on tall screens** (X2 portrait, tablet portrait, one player): the vertical tile is
   calm but still hollow (464×856). A layout option for the visual agent: media-control
   (artwork) above the player tile when R ≥ 10, at 2/3 of the rows. The design review moved
   away from media-control at ≤ 960 px because it fills with the accent colour when there is
   no artwork, so this is a style decision.
2. **Big scene tiles** (up to 6 rows on tablets) and the 5-row Home tiles: the content stays
   tile-sized (36 px icon). Scaling the icon and label on tall tiles is the visual agent's call.
   It would make the filling read as intentional.
