# Sandbox: Home Assistant 2026.10.0 in Docker

Reproducible instance for end-to-end checks of `walldisplay_dashboards` and its frontend module.

Requirements: Docker, Node 22 (global `fetch` and `WebSocket`). Run `npm install` here once
(installs puppeteer and its Chrome).

| script | what it does |
|---|---|
| `node setup.mjs --fresh` | writes the config dir, skips onboarding, creates users `admin/adminpass` and `panel/panelpass` (auth script, before the first start), starts container `wdd-sandbox` on http://localhost:18123, moves `panel` to `system-users`, creates the areas Kitchen / Living room / Bedroom / Bathroom, creates persons Alex and Sam, and adds displays through the config flow: `Kitchen` (480×480, idle 10 s), `Entrance` (Hallway, role `entrance`) and `Test <profile>` for every other profile. `--seed-only` re-seeds a running instance, `--no-integration` skips the flow, `--idle N` sets idle_seconds for Kitchen, `--extra-js` also loads the JS via `frontend.extra_module_url`. |
| `node spike.mjs` | creates `/spike-grid` and measures the sections grid at 480×480, 960×480 and 1280×752 (findings in `SPIKE.md`, raw data in `out/spike.json`). |
| `node shoot.mjs` | as the panel user, screenshots every profile × view (`out/<profile>__<view>.png`, DPR 2) and checks: no page scroll, no card reaching into the footer or off screen, no truncated nav label, kiosk chrome hidden, scroll lock present, nav pill width/active item, tall tiles without features scaled up (icon >= 56 px). Behaviour: wheel does not scroll at 480×300, one `report_viewport` per load, pill tap navigates, leaving the dashboard removes lock and kiosk styles, idle → home closes an open more-info, admin `/config` untouched, `?edit=1` (admin) and `?disable_km` keep HA's chrome. Admins send no viewport report. Variants: `shelly_wall_display@entrance` and `<profile>@de` (server + user language switched to German, then restored). Writes `out/report.json`; exit code 1 on failure. `--only <profile>`, `--no-behaviour`, `--no-variants`. |
| `node perf.mjs` | traces as the panel user under CPU throttling (`--rate 6`, default) at 480x480 and 960x480: first load, pill switch, tile tap, 60 s idle with state changes and unrelated registry renames; compares with `?disable_km`, a plain HA dashboard with the same cards, and HA without walldisplay.js. Writes `out/perf/`. Method and numbers in `PERF.md`. |
| `node contact.mjs` | builds `out/contact.html`, all screenshots embedded as data URIs, grouped by profile/variant, failed checks flagged. |

Mounts: the config dir lives outside OneDrive (`HACFG`, default: `<os temp dir>/walldisplay-sandbox/hacfg`);
`custom_components/walldisplay_dashboards` and `fake_devices/` are
mounted read-only. After changing Python code run `docker restart wdd-sandbox`. JS changes are
picked up by every new browser (puppeteer starts with a fresh profile).

Environment overrides: `HACFG`, `HA_IMAGE`, `HA_CONTAINER`, `HA_PORT`.

## Fake devices

States POSTed to `/api/states` have no entity registry entry, so they cannot be put in an
area. `fake_devices/` is a test-only custom integration (`fake_devices:` in
configuration.yaml) that creates real registry entities (light, cover, climate, media_player,
switch, scene, sensor, weather) from `fake_devices.json` and assigns each to its `area`
(created if missing). If `tests/fixtures/expected/states.json` exists, its states are POSTed
as well (they show up, but without an area).

## Notes

- A fresh browser profile reloads the page once when HA's service worker takes control
  (about 7 s after the first load). The scripts do a warm-up visit first (`warmUp` in `lib.mjs`).
- Login recipe: `localStorage.hassTokens = {...tokens, hassUrl, clientId, expires}` on the
  origin, then open the dashboard.
