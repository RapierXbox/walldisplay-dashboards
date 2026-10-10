# Layout spike: sections view on HA 2026.10.0 (frontend 20260930.x)

Measured with `node spike.mjs` (raw numbers in `out/spike.json`, screenshots in
`out/spike__*.png`). Dashboard: plain storage dashboard `/spike-grid`, `type: sections`,
`max_columns: 3`, `top_margin: false`, footer = grid card with 4 shortcut cards.
Logged in as the non-admin panel user. "kiosk" means the header and sidebar are hidden
exactly as `walldisplay.js` does it (builtin kiosk). "plain" means HA's own chrome.

## Headline numbers (kiosk)

| viewport | section columns | wrapper padding | section width (span = all) | card col / gap | row / step | 1st row y | footer card |
|---|---|---|---|---|---|---|---|
| 480×480 | **1** | 8 px | 464 (12 cols) | 31.33 / 8 | 56 / 64 | 24 | y 392–448, w 464 |
| 960×480 | **2** (not 3) | 32 px | 896 (24 cols) | 29.66 / 8 | 56 / 64 | 24 | y 392–448, w 600 |
| 1280×752 | **3** | 32 px | 1216 (36 cols) | 26.00 / 8 | 56 / 64 | 24 | y 664–720, w 600 |

Card widths (grid_options.columns → px):

| viewport, section | 6 | 12 | 18 | 24 | 36 |
|---|---|---|---|---|---|
| 480, span 2 or 3 (clamped to 1) | 228 | 464 | 464 (clamped) | 464 (clamped) | 464 (clamped) |
| 960, span 2 or 3 (clamped to 2) | 218 | 444 | 670 | 896 | 896 (clamped) |
| 1280, span 3 | 196 | 400 | 604 | 808 | 1216 |
| 1280, span 2, only section in view | 252 | 512 | 772 | 1032 | – |

## Rules derived from the frontend source and confirmed by the measurements

1. **Section columns** (`hui-sections-view.ts`):
   `N = max(1, floor((W − 2p + g) / (320 + g)))`, with `p = g = 8` when the viewport is
   ≤ 600 px wide, else `p = g = 32`. Then
   `C = min(max_columns, N, sum of column_span of visible sections)`.
   480 → 1, 800 → 2, 960 → 2, 1280 → 3. Two columns need W ≥ 736, three need W ≥ 1088.
   **`contracts.md` says `clamp(floor(W/320), 1, 3)`; that is wrong for 960 (gives 3, real 2)
   and for 640–735 (gives 2, real 1).**
2. **column_span is clamped** to C. A `column_span: 3` section at 960 gets 24 card columns,
   at 480 it gets 12. A card wider than the section's grid is clamped to full width (it takes its
   own row).
3. **Card columns per section** = `12 × effective span`, column gap 8, row height 56, row gap 8
   (step 64). A card of n columns is `n·colW + (n−1)·8` wide.
4. **Wrapper width** = `min(W − 2p, C·500 + (C−1)·32)`, centred. Each section column is at most
   500 px. Because C also counts only the spans actually used, a view whose sections add up
   to span 2 at 1280 is 1032 px wide and centred (x = 124), not 1216.
5. **Vertical budget (kiosk, top_margin false):** first row at y = 24; stacked sections are
   24 px apart (two 1-row sections: y = 24 and y = 104). The footer element spans
   H−96 … H−24 (8 px padding + 56 px card + 8 px), sticky 24 px above the bottom; the card
   itself is H−88 … H−32. Page height = `24 + content + 24 + 72`, so with one section of R rows
   there is no scroll iff `R·64 + 112 ≤ H` → **R = floor((H − 112)/64)** (480 → 5, 752 → 10):
   confirmed, 5 rows at 480 give scrollHeight 480, 6 rows would scroll.
   Each additional stacked section costs 16 px more (24 gap instead of the 8 row gap), so
   status (1 row) + tiles (4 rows) at 480 → 24+56+24+248+24+72 = 448 ≤ 480: fits.
6. **Footer card** is centred, `max-width` 600 px (`footer.max_width` overrides), and capped at
   25 vh height. At 480 it is 464 wide: 4 shortcuts of ~110 px each.
7. **grid_options.rows: 5**
   - `vertical-stack`: the slot is 5 rows (312 px) but the stack does **not** stretch; its two
     tiles stay 56 px each and the rest stays empty.
   - `grid` card (`columns: 1, square: false`): **fills** the 312 px; two tiles become 152 px each.
   - a single `tile` with rows 5 stretches to 312 px.
   Use a `grid` card when a column of cards must fill N rows.

## Without kiosk ("plain"): why the builtin kiosk matters

- Header adds 56 px: first row at y = 80, so R = floor((H − 168)/64) (480 → 4). A 5-row layout at
  480 scrolls by 8 px (scrollHeight 488).
- Above 870 px viewport width the sidebar is docked (256 px expanded, the default for a new
  user; 56 px collapsed). At 960 the content is 704 px → **1** section column; at 1280 it is
  1024 px → **2** columns (960 px section).
- So the landscape layouts only hold when the header and sidebar are hidden (kiosk `builtin`, or
  the kiosk-mode plugin configured with `kiosk: true`). For `kiosk: off` the generator should
  budget with the header and the sidebar.

## Pill nav footer (`custom:wall-display-nav`, view `/spike-grid/nav`)

With 4 items the pill is 4·76 + 8 = 312 px wide and 56 px tall, centred in the footer, card at
H−88 … H−32 like any 1-row footer card. Labels up to "Scenes" fit at 12 px (no truncation at
480). `footer.max_width` only caps the footer wrapper; the pill sizes itself.
