# Spacing pass (round 3: "the spacing is still a bit big in some cases")

Evidence: `tools/sandbox/out/spacing/compare.html` (before/after, DPR 2), raw rects in
`tools/sandbox/out/spacing/measure.json`. The pairs come from the sample house rendered in the
HA 2026.10 sandbox. "Before" is the current generator. "After" is the same generator with the
constants and rules below patched in (`tools/sandbox/spacing/gen.py`), plus the CSS below
injected (`tools/sandbox/spacing/spacing.mjs`). Every "after" view was measured: no scroll, last
card 16 px above the pill.

## Problems found (CSS px)

| # | Where | Measured | Why it reads as loose |
|---|---|---|---|
| 1 | Every page, H = 480 / 800 | last card 336, pill 392: **56 px** dead band (48 px left over by rounding + 8 px footer padding) | `R·64 + 112` fits 432 of 480, so a full row's worth of space is lost |
| 2 | Same band elsewhere | 24 px at H 960/1280, **8 px** at 752 | the card-to-pill gap varies from 8 to 56 px |
| 3 | Frame | top 24, sides 32 above 600 px wide, pill bottom 32, against an 8 px card gap | the margins are 3–4× the gutter; 960×480 loses 64 px of width to the sides |
| 4 | Scenes, all profiles | tiles capped at 2 rows and top-aligned: **120** (480), **600** (480×960), **392** (XL), **920** (800×1280) px empty above the pill | half-empty screen |
| 5 | 960×480 Home | 4 tiles at 2×2 rows end at y 272, the info column at 336 | an empty row to the right of the info column; uneven bottoms |
| 6 | Portrait Home | spare rows go to the status area: clock 184 px (date cut to "Saturday 10 Octob" at 228 px wide), weather tile 184 px, forecast 248 px; tiles stay 120 px | big, nearly empty status cards |
| 7 | Tall tiles | 312 px (5 rows, tablet portrait), 248 px (XL); the content is about 110 px | icon and label float in an empty card |
| 8 | Info column XL/tablet | the grid card shares extra height equally: clock 227, weather tile **168** (one line of text), room 222 | hollow weather tile |
| 9 | 960×480 Heat | side column uses 3 of 5 rows (mode 2 + humidity 1) | empty corner |
| 10 | Entrance (no footer) 480 | last card 400: **80 px** empty at the bottom | a whole row lost |

Fine as is: Media (media-control absorbs the rows), the thermostat dial, and the info-column-to-grid
gap (8 px, same as the card gutter). Forecast card: the sandbox weather has no forecast data,
so the card falls back to current conditions and looks hollow at 3+ rows. With real data it
shows a strip. Not verified; see open point 2.

## Decisions

- **D1 Frame = 12 px.** Top 12. Sides 12 above 600 px wide; at ≤ 600 px they stay HA's
  narrow 8 px, because width is scarce at 480. The card gutter stays 8. Pill: 16 px below
  the grid, 20 px from the bottom edge. Without a footer: 12 at the bottom.
- **D2 Rows fill the height.** The row height is stretched so that R rows end exactly 16 px above the
  pill: `row = (H − 96) / R − 8` (no footer: `(H − 16) / R − 8`), clamped 48…72. Shipped
  profiles get 56…58.5 px, so tap targets are never below 56 px. The pill does not grow.
- **D3 New budget** (below). It gains one row at 480 (5 → 6), 800 (10 → 11) and 480 without a
  footer (6 → 7).
- **D4 Spare rows go to controls first, then to content that scales, never into hollow cards.**
  Rules G1–G6 below.

## Row budget

```
R = floor((H − 96) / 64)      with the pill footer   (12 top + 92 footer band − 8)
R = floor((H − 16) / 64)      without footer         (12 top + 12 bottom − 8)
row_px = (H − 96) / R − 8     (no footer: (H − 16) / R − 8), clamp [48, 72], 8 px gap
```

| H | 480 | 752 | 800 | 960 | 1280 | 480, no footer |
|---|---|---|---|---|---|---|
| R before → after | 5 → **6** | 10 → 10 | 10 → **11** | 13 → 13 | 18 → 18 | 6 → **7** |
| row px after | 56 | 57.6 | 56 | 58.46 | 57.78 | 58.29 |

Section columns with the 12 px view gap: `C = clamp(floor((W − 12) / 332), 1, 3)` above 600 px
(≤ 600: `floor((W − 8) / 328)` → 1). 800/960 → 2 and 1280 → 3 are unchanged; custom widths
676–735 now get 2 columns and 1008–1087 get 3. Section width = `min(W − 2g, C·500 + (C−1)·g)`:
960 → 936, 1280 → 1256, 800 → 776.

## Changes per module

### const.py / layout.py (generator; const.py needs the lead's agreement)
- `GRID_TOP_PX` 24 → **12**, `FOOTER_BAND_PX` 96 → **92** (12 sticky offset + 72 footer box + 8 air),
  `layout.BOTTOM_MARGIN_PX` 24 → **12**, `layout.VIEW_GAP_PX` 32 → **12**. `VIEW_GAP_NARROW_PX`
  stays 8. `GRID_ROW_PX` 56 stays the minimum row used for widths and aspect checks.
- `GROWN_TILE_MAX_ROWS` 5 → **4** (fixes 7).
- New `row_px(height, rows, footer) -> float` implementing D2, for tests and the preview.
- Update the module docstring (24 px → 12 px, the formulas above).

### generator/*
- **G1 scenes.py** (fixes 4): `fill = fill_tiles(n, card_columns, R, column_px, max_per_row=3,
  max_rows=3)`; tiles `vertical` when `fill.rows >= 2`; keep `overflow_slot`. Drop `MAX_ROWS = 2`
  and the "top-aligned" note. Result: it fills at 480 and 960×480; big screens keep some room under
  short lists (accepted: 184 px tiles are big enough).
- **G2 home.py portrait** (fixes 6): clock/weather 2 rows. Spare rows go first to `grow_tiles`
  (tiles 2 → 3–4 rows), then the forecast (≤ 4 rows), then the clock (≤ 3 rows), and any rest
  to the forecast.
- **G3 home.py `_clock_for`**: `large` only when the clock card is ≥ 320 px wide, else `medium`
  with the long date (fixes the cut date at 228 px; also hit after D3 at 960×480).
- **G4 home.py `info_column`** (fixes 8): `[clock, {type: grid, columns: 1, square: false,
  cards: [weather, room, forecast?]}]`, so the background-less clock takes half the extra height.
  Weather tile `vertical: true` when `grid.rows >= 8`.
- **G5 climate.py landscape side column** (fixes 9): share all R rows among the side tiles,
  each ≤ 3 rows, `vertical: true` at ≥ 2 rows.
- 960×480 Home (5) and the entrance (10) are fixed by D3 alone: 2 lines × 3 rows = 6 = R; 7 rows.

### websocket.py (backend)
`walldisplay_dashboards/list` adds two fields per display: `rows` (int, the Home grid's R from
`compute_grid`) and `footer` (bool, whether there is more than one page). walldisplay.js needs
them for D2.

### frontend/walldisplay.js
Inject on every wall dashboard (same gating as the kiosk styles: not with `?disable_km`, and not
in admin edit mode), whatever the kiosk mode. Removed on leave, like the other styles.
`hui-sections-view` lives in hui-root's shadow root (`#view > hui-view > hui-sections-view`).

```js
const SPACING_ROOT = `#view { --ha-view-sections-row-gap: 12px; --ha-view-sections-column-gap: 12px; }`;
// in hui-sections-view's shadow root: only the section grid stretches; the footer keeps 56 px
const SPACING_VIEW = `.container { --ha-section-grid-row-height: var(--wd-row-height, 56px); }`;
function rowHeight(d, viewEl) {             // d = display from /list
  const band = d.footer ? 96 : 16;
  const h = window.innerHeight - viewEl.getBoundingClientRect().top - band;
  const rows = d.rows || Math.floor(h / 64);
  return Math.min(72, Math.max(48, Math.floor((h / rows - 8) * 100) / 100));
}
// tick(): inject(rootRoot, SPACING_ROOT); inject(rootRoot.querySelector("hui-sections-view")
//   ?.shadowRoot, SPACING_VIEW); rootRoot.querySelector("#view").style.setProperty(
//   "--wd-row-height", `${rowHeight(d, view)}px`); also re-run it on window resize.
```

HA source (frontend 20260930.2): `hui-sections-view` `--row-gap: var(--ha-view-sections-row-gap,
24px)` is the container's top and bottom padding, the gap between stacked sections and the footer's
`position: sticky; bottom`. `--column-gap: var(--ha-view-sections-column-gap, 32px)` is the side
padding and the column gap, and it feeds the column-count calculation. `hui-grid-section` and
`hui-view-footer` both read `--ha-section-grid-row-height` (56), `-row-gap` and `-column-gap` (8).
The footer box is `.wrapper` padding 8 + card + 8. Without the scoped `.container` rule, the pill
card would grow with the rows.

Fallback: if the CSS is missing, HA's 24 px gaps return; the page grows by up to 16 px (480: 496) and the last row slides under the
pill. That is the same dependency the builtin kiosk already has.

### tools/preview (template.html, then rebuild preview.html)
`TOP = 12`; `SECTION_GAP = 12`; footer box drawn at `H − 84`, 72 high (`FOOTER_TOP = 84`,
`FOOTER_BOTTOM = 12`); budget line at `H − 92` (`BUDGET_BOTTOM = 92`; 12 without footer);
`colGap = W <= 600 ? 8 : 12`; row height per view from D2 (`rowsPx` uses it); overlay text
"footer band y = H−92 … H−12" / "no footer: bottom margin 12 px".

### tools/sandbox/shoot.mjs
No-footer limit `innerHeight − 12`. New checks: first card y = 12; gap between the last card and
the pill 16 ± 1 px (within R px when rows are floored); pill bottom 20.

## Proposed contracts.md text ("Layout budget", replaces the section)

> **Layout budget (HA 2026.10, with the walldisplay.js spacing CSS).** The view's row gap is
> 12 px (top padding, bottom padding, the footer's sticky offset), the side padding is 12 px
> above 600 px wide and 8 px at or below, and the card gutter is 8 px. With the pill footer, the
> first row is at y = 12, the footer box spans H−84 … H−12, and the grid ends 16 px above the pill.
> Rows: `R = floor((H − 96) / 64)` with a footer, `floor((H − 16) / 64)` without
> (480 → 6, 752 → 10, 800 → 11, 960 → 13, 1280 → 18; 480 without a footer → 7). The row height is
> stretched by walldisplay.js to `(H − 96)/R − 8` (no footer `(H − 16)/R − 8`), clamped 48–72
> px, so generators reason in rows, never in pixels of height. Section columns:
> `C = clamp(floor((W − g) / (320 + g)), 1, 3)` with g = 8 at ≤ 600 px wide, else 12.
> `walldisplay_dashboards/list` returns `rows` and `footer` per display.

Also in contracts.md: v3 "Nav pill v3" sentence "still keep 24 px bottom margin" → "12 px".
docs/ux.md: U5 cap "× 2 rows … giant tiles" now reads "tiles grow to at most 4 rows"; the
scenes line "tiles at most 2 rows high" → "fill_tiles, at most 3 rows".

## Open points
1. Shelly/NSPanel viewports are still profile guesses. D2 stretches to the real `innerHeight`,
   so a device a few px shorter shrinks rows instead of scrolling (≥ 48 px).
2. Forecast at ≥ 3 rows: try `forecast_type: daily` + `show_current: true` with a weather
   entity that has real forecasts before choosing. Not testable in the sandbox.
