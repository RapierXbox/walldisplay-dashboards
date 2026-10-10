# Performance on weak wall panels

Measured in the sandbox (HA 2026.10.0 in Docker, 9 displays) with `node perf.mjs`. The real
targets (Shelly Wall Display / X2, ShellyElevate WebView, Android 8.1, SC7731E, 1 GB) are
much slower than a desktop, so Chrome runs with `Emulation.setCPUThrottlingRate` 6x (and
10x for the main cases). Absolute times on a panel will be higher; the ratios hold.

## Method

`perf.mjs` logs in as the non-admin panel user (fresh browser profile, service worker warmed
up) and traces each scenario (`devtools.timeline` + V8 CPU samples, saved under
`out/perf/*.trace.json`, open them in DevTools):

| scenario | what happens |
|---|---|
| load | first load of the dashboard, 20 s; `firstTiles` = first tile rendered |
| switch | pill tap Home -> Climate -> Home -> Climate -> Home; latency = tap until the target card has a size |
| tap | three light tile taps (toggle); latency = tap until the new state is in `hass` |
| idle | 60 s on Home; meanwhile a kitchen sensor changes every 5 s, a bedroom light toggles every 7 s, and an entity in a room without a display (climate.bedroom / cover.bedroom_blind) is renamed every 15 s (4 renames) |

Cases: `wall480` (/wall-kitchen, 480x480), `wall960` (X2 landscape test display, 960x480),
`km480` (/wall-kitchen?disable_km: kiosk, layout and auto dark off), `plain480` (a plain HA
sections dashboard with the same cards, no pill, walldisplay.js loaded), `bare480` (the
same plain dashboard with walldisplay.js switched off: HA alone).

Columns: busy = main-thread task time; long = tasks > 50 ms; TBT = sum of (task - 50 ms);
wd JS / HA JS = CPU samples whose nearest script frame is walldisplay.js / the HA frontend;
regen = `walldisplay_dashboards/generate` calls, i.e. full dashboard rebuilds and re-renders.
The sandbox is shared: runs during which the container restarted were thrown away (the
script logs the container start time).

## Causes found (before)

1. **Every registry change anywhere re-rendered every open wall dashboard twice.**
   - Our strategy had no `shouldRegenerate`, so HA's default regenerated the dashboard
     whenever `hass.entities/devices/areas/floors` changed (any entity rename, a device
     firmware update, a new entity in another room).
   - About 2 s later the backend fired `lovelace_updated` for all 9 dashboards (it didn't
     check whether anything changed), so the panel regenerated a second time.
   - Each rebuild is a full card re-render: a 170-400 ms long task at 6x, plus follow-up work.
   - With 4 unrelated renames per minute: 7 rebuilds, 54 `lovelace_updated` events, 27
     `/list` calls (one per event, on every HA page, admins included) and 7 long tasks.
   - Idle main-thread time was 3.4 s/min on a wall dashboard vs 1.2 s/min for HA alone.
2. **The 400 ms polling tick:** 150 ticks/min on wall dashboards, each walking the shadow
   roots (`kioskRoots` 3x per tick), `querySelectorAll` over every section and
   `getBoundingClientRect` reads. That was 270 ms of JS per minute at 6x (4.5 ms/s, as much
   as all of HA's idle JS). Off wall dashboards it was still 75 ms/min.
3. **`/list` built all 9 dashboards** on every call (17-19 ms server time per call, x27 per
   minute per open browser).
4. Tall-tile sizing interleaved layout reads and style writes per card (minor, it only
   happens on view changes).

Not causes: `generate` takes 2-3 ms server-side; there are no live-template markdown cards;
the clock re-renders once a minute; the pill is a single shadowed element.
`settheme` is only sent on sun transitions; the viewport is reported once per load.

## Fixes

- `walldisplay.js` strategy: `static shouldRegenerate() { return false; }`. The integration
  is the only trigger (`lovelace_updated`), and it fires only for real changes.
- Backend (`__init__.py`, `websocket.py`):
  - registry and language changes are debounced 5 s (was 2 s), and floor registry
    changes are now included (floor names are dropped from tile names);
  - every loaded display is rebuilt in Python and its digest (blake2b of the sorted JSON)
    compared with the one the panels were last told about; `lovelace_updated` fires only
    for displays whose dashboard changed;
  - a failed build fires once, not on every update;
  - the digest is seeded at setup or reload;
  - `list` reuses the dashboard built last (by `generate`, `list` or a refresh) for 60 s
    while the entry's data and options are unchanged;
  - `generate` always builds fresh: at 2-3 ms, caching it would only risk a stale layout
    after a state-only change.
- `walldisplay.js` panel behaviour:
  - ticks are event-driven and run in `requestAnimationFrame`, at most one per frame:
    navigation, resize, `visibilitychange`, a new config (the strategy kicks after
    `generate`), a MutationObserver on the view's light DOM and the sections-view shadow
    root, and a `subscribe_entities` subscription to `sun.sun` only;
  - a watchdog re-checks every 400 ms for ~3 s after any trigger or change, then every
    3 s. It runs on wall dashboards only and is paused while the page is hidden;
  - shadow roots are looked up once per tick (was 3x);
  - `?disable_km`/`?edit` parsing is cached per `location.search`;
  - tall tiles: a ResizeObserver on each card's grid cell (`hui-card` is `display: inline`,
    which a ResizeObserver reports as 0x0), with all reads before writes, and styles written
    only when the computed sizes change;
  - `/list` after `lovelace_updated` is debounced (1 s);
  - a first `/list` that fails while HA starts is retried every 10 s;
  - auto dark waits until the display list is known (before, a slow start could "restore" the
    theme too early).

## Before / after (6x unless noted; 480x480 /wall-kitchen)

60 s idle on Home, with 4 unrelated renames and the state changes described above:

| | before | after | HA alone (bare480) |
|---|---|---|---|
| main-thread busy, 6x | 3378 ms | **963 ms** | 1091-1229 ms |
| long tasks / max / TBT, 6x | 7 / 401 ms / 1247 ms | **0 / - / 0** | 0-2 / 76 ms / 29 ms |
| main-thread busy, 10x | 6150 ms | **1616 ms** | 1761-2375 ms |
| long tasks / TBT, 10x | 15 / 2600 ms | **1 / 42 ms** | 1-9 / 32-222 ms |
| dashboard rebuilds (generate) | 7 | **0** | - |
| `lovelace_updated` received / `/list` sent | 54 / 27 | **0 / 0** | - |
| walldisplay.js JS per minute, 6x | 270 ms (4.5 ms/s) | **37 ms (0.6 ms/s)** | - |
| walldisplay.js JS per minute, 10x | 494 ms | **56 ms** | - |
| timer fires per minute | 274 | **112** | 120 |
| walldisplay.js JS, plain HA dashboard | 75 ms/min | **2 ms/min** | - |

Interactions (latency medians are dominated by HA; ours is the JS share):

| | before | after |
|---|---|---|
| pill switch latency (first visit / cached), 6x | 364 / 270 ms | 384 / 280 ms (unchanged, HA) |
| walldisplay.js JS during the switch run | 104 ms | 146 ms (more ticks while settling, all in rAF) |
| tile tap -> state, 6x | 20-74 ms | 45-92 ms (network round trip, noise) |
| walldisplay.js JS during 3 taps, 6x | 45 ms | **8 ms** |
| first load to first tile, 6x / 10x | 5.1 s / 21.6 s | 5.4 s / 9.1 s (HA alone: 4.5-5.6 s / 9.5-13.8 s; noise) |

Backend, per call, 9 displays:

| | before | after |
|---|---|---|
| `generate` | 1.9-2.6 ms | 2.6-3.2 ms (always built fresh) |
| `list` | 16.6-19.5 ms | **0.8-1.0 ms** (cached) |
| `lovelace_updated` fired per display, 9 min 6x run (20 unrelated renames) | 19 | **0** |

960x480 (X2 test display), idle 6x: busy 3356 -> **901 ms**, TBT 1301 -> **10 ms**, rebuilds 7 -> 0.

## Next opportunities (not done), by expected gain on the panel

1. **No page reload on options save.** A reload of the entry calls `async_refresh_display`,
   which reloads the ShellyElevate WebView: 10-20 s of CPU at 10x for a full HA boot. The
   `lovelace_updated` rebuild already shows the new layout. Reload only when the URL, kiosk
   mode or idle timer changed.
2. **Fewer, flatter cards per view (generator).** The first visit of a view costs ~300-550 ms
   at 6x and is rebuilt after every config change. Home's info column and the Scenes/Climate
   fills use `grid` wrapper cards (an extra hui-card + grid per wrapper). Flattening them into
   section cards and dropping cards that don't fit saves elements and lit updates on every
   state change.
3. **Optional "reduce motion" CSS on wall dashboards** (`transition`/`animation: none` inside
   the view): a tap causes ~40 style recalcs, mostly ripple and tile transitions. This is a
   design decision (it removes HA's feedback animations).
4. **Inline tile features on the 4" panel** (brightness and cover sliders) are the heaviest
   tiles to update; a design call whether square panels keep them.
5. **Auto dark** restyles the whole page at sunrise and sunset; a theme with fewer variables
   (or the default theme) makes that cheaper. Low frequency, low gain.


## What is left: Home Assistant's own cost (we can't fix it here)

- **First load** is HA booting: one 4-5 s task (10x) evaluating and rendering app.js,
  then lit render passes. Wall, km, plain and bare cases all land within noise of each
  other (5-6 s to the first tile at 6x, 10-14 s at 10x). A panel should never reload.
- **First visit of a view** builds all its cards (~300-550 ms at 6x, thermostat views
  slower). Revisits are cached by hui-root (10-15 ms). HA clears that cache on every config
  change, which is why avoiding rebuilds matters so much.
- **Every state change** pushes a new `hass` to every card of the view (lit update). A tap
  costs ~40-100 ms at 6x end to end; the light's ripple and the tile animation cause
  ~40 style recalcs per tap.
- **Theme switch** (auto dark at sunrise/sunset) restyles the whole page once.

## Tips for the owner (ShellyElevate)

- Turn off any periodic page refresh in ShellyElevate. A reload costs 10-20 s of CPU on these
  SoCs; the dashboard updates itself.
- Enable hardware acceleration in the WebView settings if your ShellyElevate build exposes it.
- Android developer options: set the window/transition/animator scales to "off" (fewer
  system animations; recent Android System WebView versions also report
  `prefers-reduced-motion`, which some HA components honour). Keep the Android System WebView
  app updated: old WebView builds are much slower at shadow DOM and CSS custom properties.
- Use the built-in kiosk mode (default). The kiosk-mode plugin adds its own polling on top.
- Keep the Home page small: every tile is re-rendered on every state change in the room.
  `max_home_tiles` helps on the 4" panel.
- Don't leave an admin browser open on a wall dashboard on the same weak device; one
  WebView per panel.
- Avoid heavy custom themes (backdrop-filter blur, big box-shadows, animated backgrounds):
  they cost paint time on every update.
