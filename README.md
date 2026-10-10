# Wall Display Dashboards
auto generated ha dashboards for wall displays. made it bc building a dashboard for a 4" shelly display by hand is pain and doing it for every room is even worse.

you tell it which display hangs in which room and it builds a dashboard that fits that exact screen. no scrolling, nothing cut off, and it updates itself when you add/move devices. works great with [ShellyElevate](https://github.com/RapierXbox/ShellyElevate) but any android panel / tablet works too.

needs home assistant 2026.10+. no warranty, use at your own risk.

| shelly wall display 480x480 | shelly x2 landscape 960x480 |
|---|---|
| ![480](docs/images/home-480x480.png) | ![960](docs/images/home-960x480.png) |

![xl 1280x752](docs/images/home-1280x752.png)

### what it does
- tiles come from the area the display is in, new devices just show up
- pill nav at the bottom: home, climate (full screen thermostat), media, scenes. pages only show if the room has stuff for them
- every entity only shows up once (thermostat is on climate, not also on home etc)
- locks, alarms, garage doors etc are status only, tap opens the details. no accidental garage opening
- kiosk mode, scroll lock, goes back to home after 60s idle, dark mode after sunset
- entrance role for the panel at the front door: whos home, lights on, open doors/windows, all off / away
- pushes the dashboard url to shellyelevate automatically
- measures the real screen size and tells you if the model you picked is off
- english + german

### displays
shelly wall display, x1i, x2/x2i (landscape + portrait), xl/xli, nspanel pro, tablets, or custom size. sizes are css px not physical px. the shelly ones are guesses until the display measured itself once, see below.

### install
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RapierXbox&repository=walldisplay-dashboards&category=integration)

click that, download, restart ha. or by hand in hacs: menu (⋮) → custom repositories → add `https://github.com/RapierXbox/walldisplay-dashboards` as integration

manual: copy `custom_components/walldisplay_dashboards` to `/config/custom_components/`, restart ha

### setup
1. make a non admin user for the panels (settings → people → add person, allow login on, admin off). one user for all panels is fine. admins dont get auto dark and size measuring (except in shellyelevate, that always counts as panel)
2. [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=walldisplay_dashboards) or settings → devices & services → add integration → wall display dashboards. one entry per display:
   - name: `Kitchen` → dashboard is `/wall-kitchen`. cant change it later
   - display device (optional): your shelly / shellyelevate device. area gets taken from it, its temp/humidity sensors get used, url gets pushed to it
   - area: the room. can be empty if the device has one
   - display model + role (room or entrance)
   - display host (optional): ip of a shellyelevate display thats not in ha, url gets pushed via http api
   - weather (optional), otherwise first weather entity
3. get the display to open it:
   - shellyelevate with the [ha integration](https://github.com/RapierXbox/shellyelevateintegration) or display host set: nothing to do
   - everything else: you get a notification with the url. stock shelly firmware → settings → network → home assistant, fully kiosk → start url, companion app → just open it as the panel user
   - url comes from settings → system → network (local url), check that if the display cant connect
4. let it load once as the panel user. if the **Measured viewport** sensor differs from your model you get a repair, submit it and it uses the real size

### options
configure on the entry: favourite scenes (first on the scenes page), role, which extra pages, return home time (0 = off), kiosk mode (builtin / kiosk-mode plugin / off), pinned + hidden entities, show in sidebar.

reconfigure for area, model, device, host, weather.

### editing by hand
the dashboard gets generated every time it opens so you cant edit it in the editor. dashboard menu → edit → **take control** and its a normal dashboard, integration leaves it alone after that. removing the entry wont delete a dashboard you took control of. want the generated one back? delete the dashboard and reload the entry.

### problems
- **"Wall display dashboard unavailable"**: generator failed, check the ha log
- **layout wrong size**: check the measured viewport sensor + repairs. only measures as non admin or in shellyelevate
- **dark mode on other devices**: auto dark uses ha's theme setting which is saved on the user. if all panels share one user and someone changes the theme by hand it changes on all of them till next sunrise/sunset. use separate users if that bugs you
- **need header/sidebar on a panel**: add `?disable_km` to the url (admins can also use `?edit=1`)
- **kiosk-mode plugin option does nothing**: yeah you need to install and configure [kiosk-mode](https://github.com/NemesisRE/kiosk-mode) yourself then
- **device missing**: put it in the area or pin it, check its not hidden
- **display didnt get the url**: its in the notifications, enter it by hand or set display host

### dev
```bash
pip install pytest-homeassistant-custom-component==0.13.371
pytest -q tests
```
ha test stuff doesnt run on windows, use wsl or docker:
```bash
docker run --rm -v "$PWD:/repo" -w /repo python:3.14 sh -c "pip install -q pytest-homeassistant-custom-component==0.13.371 && pytest -q tests"
```
`tools/sandbox` = docker ha for screenshots / e2e checks, `tools/preview` = html preview of the generated dashboards.

release: bump version in `manifest.json`, `git tag v0.1.0 && git push origin v0.1.0`, workflow does the rest.

### license
MIT
