/*
 * Wall Display Dashboards: frontend module (plain ES module, no build step).
 * Loaded on every Home Assistant page through frontend.add_extra_js_url.
 *
 * 1. Dashboard strategy "custom:wall-display" (element ll-strategy-dashboard-wall-display).
 *    generate() asks the backend (websocket walldisplay_dashboards/generate) for the full
 *    dashboard config. On error it returns a one-view dashboard that explains the problem.
 * 2. Panel behaviour, only on dashboards returned by walldisplay_dashboards/list
 *    (matched by the first path segment). A "tick" (re)applies it in an animation frame,
 *    driven by events: navigation, resize, a regenerated config, DOM changes of the view
 *    (MutationObserver) and tile sizes (ResizeObserver). A watchdog re-checks every 400 ms
 *    while the page settles and every 3 s once nothing changed (wall dashboards only,
 *    paused while the page is hidden). On every other page a tick is a few string
 *    compares: nothing is injected or observed there, and whatever was added is removed:
 *    - scroll lock: <style id="walldisplay-lock"> in <head> while on such a dashboard
 *      (lifted while the dashboard is being edited);
 *    - idle -> home after idle_seconds without pointer/touch/key/wheel input (0 = off);
 *      an open more-info dialog is closed first;
 *    - kiosk "builtin": header and sidebar are hidden by styles injected into the shadow
 *      roots of home-assistant-main, ha-drawer and hui-root. Skipped for the rest of the
 *      page load once ?disable_km (anyone) or ?edit=1 (admins) was seen.
 *      "kiosk_mode" and "off" leave the chrome alone;
 *    - layout (docs/design-spacing.md): 12 px view gaps and rows stretched so the grid ends
 *      16 px above the nav pill, a fixed type scale, and bigger icon/name on tall tiles
 *      (ResizeObserver); same skip rules as the kiosk, whatever the kiosk mode;
 *    - auto dark for panel users: dark below the horizon (sun.sun), previous theme restored on leave;
 *    - viewport report: walldisplay_dashboards/report_viewport once per page load and display,
 *      only for non-admin users or inside the ShellyElevate app;
 *    - ShellyElevate (Android app) bridge: the screen-on event navigates home.
 *    The display list is re-read on lovelace_updated (debounced) and every 5 minutes.
 * 3. Card "custom:wall-display-nav": the floating pill nav used as the sections-view footer.
 *    {type: "custom:wall-display-nav", items: [{path, label, icon, entity?}]}. The item whose path is
 *    the current view (last URL segment, dashboard root = "home") is highlighted; tapping
 *    navigates to /<dashboard>/<path> inside the frontend. With `entity`, a climate item shows
 *    the current temperature as its label and a media player item is marked while playing.
 *    With `temperature_entity` (a sensor chosen in the options), the label is that sensor's value.
 */

const DOMAIN = "walldisplay_dashboards";
const inShellyElevate = () => typeof window.ShellyElevate !== "undefined";
// Set by the panel behaviour: re-check the page soon (a new config is being rendered).
let kickPanel = () => {};

// Client-side navigation the way HA's own navigate() does it.
function navigate(path) {
  if (location.pathname === path) return;
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true, detail: { replace: false } }));
}
const LOCK_ID = "walldisplay-lock";
const KIOSK_ID = "walldisplay-kiosk";
const ACTIVITY_EVENTS = ["pointerdown", "touchstart", "keydown", "wheel"];
const LOCK_CSS = `html, body { overflow: hidden !important; overscroll-behavior: none !important; -webkit-user-select: none; user-select: none; }
* { -webkit-tap-highlight-color: transparent; }`;
const KIOSK_CSS = {
  main: `:host { --ha-sidebar-width: 0px !important; --ha-top-app-bar-width: 100% !important; }
ha-drawer > ha-sidebar { display: none !important; }`,
  drawer: `.sidebar-shell, wa-drawer { display: none !important; }
.app-content { padding-inline-start: 0 !important; }`,
  root: `.header { display: none !important; }
#view { min-height: 100vh !important; padding-top: calc(var(--safe-area-inset-top, 0px) + var(--view-container-padding-top, 0px)) !important; }`,
};
// Layout styles for every wall dashboard (docs/design-spacing.md, design-review.md #1).
// `root` goes into hui-root's shadow root: spacing and a fixed type scale on #view (HA's font
// tokens resolve on <html>, so they are redeclared here, not just scaled);
// `view` goes into hui-sections-view's shadow root, so only the section grid stretches its
// rows (to --wd-row-height) and the footer pill keeps 56 px.
const LAYOUT_ID = "walldisplay-layout";
const LAYOUT_CSS = {
  root: `#view {
  --ha-view-sections-row-gap: 12px;
  --ha-view-sections-column-gap: 12px;
  font-size: 16px;
  --ha-font-size-scale: 1.15;
  --ha-font-size-xs: 12px; --ha-font-size-s: 14px; --ha-font-size-m: 16px; --ha-font-size-l: 18px;
  --ha-font-size-xl: 22px; --ha-font-size-2xl: 26px; --ha-font-size-3xl: 32px;
  --ha-font-size-4xl: 36px; --ha-font-size-5xl: 46px;
  --ha-clock-card-digital-font-size-small: 40px;
}
@media (min-width: 900px) { #view { --ha-tile-info-primary-font-size: 18px; } }
@media (min-width: 1200px) { #view { --ha-tile-info-primary-font-size: 20px;
  --ha-tile-info-secondary-font-size: 16px; --ha-clock-card-digital-font-size-large: 88px; } }`,
  view: `.container { --ha-section-grid-row-height: var(--wd-row-height, 56px); }`,
};

// Tall tiles (>= ~3 rows, e.g. XL/tablet Scenes) get a bigger icon and name. The name uses
// the tile's public --ha-tile-info-primary-* properties, set on the card element. The icon
// size is pinned on ha-tile-icon's own :host, so a rule in the card's shadow root (the
// parent tree, which wins over :host) maps it to --wd-tile-icon-*. Tiles with features
// keep HA's sizes: their controls need the room.
const TALL_TILE_CSS = `ha-tile-icon {
  --tile-icon-size: var(--wd-tile-icon-size, 36px);
  --mdc-icon-size: var(--wd-tile-icon-glyph, 24px);
}`;
const TALL_TILE_TAGS = ["hui-tile-card", "hui-shortcut-card"];
const TALL_TILE_PROPS = ["--wd-tile-icon-size", "--wd-tile-icon-glyph",
  "--ha-tile-info-primary-font-size", "--ha-tile-info-primary-line-height"];

// Icon 56..72 px and name 22..26 px, growing from 176 px tall / 180 px wide to 320 / 320.
function tallTileSizes(width, height) {
  if (height < 176 || width < 180) return null;
  const t = Math.min(1, (height - 176) / 144, (width - 180) / 140);
  const icon = Math.round(56 + 16 * t);
  return { icon, glyph: Math.round(icon * 0.6), name: Math.round(22 + 4 * t) };
}

const errorDashboard = (message) => ({
  title: "Wall display",
  views: [{
    title: "Error",
    path: "home",
    cards: [{
      type: "markdown",
      content: `## Wall display dashboard unavailable\n\n${message}\n\nCheck the *Wall Display Dashboards* integration under Settings → Devices & services and the Home Assistant log.`,
    }],
  }],
});

class WallDisplayStrategy extends HTMLElement {
  // The layout is owned by the integration; "edit" offers "take control" directly.
  static noEditor = true;

  // HA's default regenerates (and re-renders every card) whenever hass.entities, devices,
  // areas or floors change anywhere in the house. The integration rebuilds in Python and
  // fires lovelace_updated for this dashboard only when its config really changed.
  static shouldRegenerate() {
    return false;
  }

  static async generate(config, hass) {
    if (!config || !config.entry_id) {
      return errorDashboard("This dashboard has no `entry_id`. Wall display dashboards are created by the integration; add a display there instead.");
    }
    try {
      const res = await hass.callWS({ type: `${DOMAIN}/generate`, entry_id: config.entry_id });
      kickPanel();
      // HA's lovelace code assumes a views list; never hand it anything else.
      return Array.isArray(res?.views) ? res : errorDashboard("The integration returned no views.");
    } catch (err) {
      const msg = err && (err.message || err.code) ? `${err.code ? `\`${err.code}\`: ` : ""}${err.message || ""}` : String(err);
      return errorDashboard(`The integration could not build it: ${msg}`);
    }
  }
}

const NAV_CSS = `
:host { display: block; height: 100%; }
.pill { box-sizing: border-box; display: flex; height: 56px; max-width: 100%; margin: 0 auto; padding: 4px;
  border-radius: 28px; background: var(--ha-card-background, var(--card-background-color, #fff));
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2), 0 6px 20px rgba(0, 0, 0, 0.18); border: 1px solid rgba(127, 127, 127, 0.25); }
button { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; padding: 0 4px; border: 0; border-radius: 24px; background: none; font: inherit; cursor: pointer;
  color: var(--secondary-text-color); -webkit-tap-highlight-color: transparent; outline: none; }
button:focus-visible { box-shadow: 0 0 0 2px var(--primary-color) inset; }
ha-icon { --mdc-icon-size: 24px; color: var(--secondary-text-color); }
.icon { display: flex; }
.label { max-width: 100%; font-size: 14px; line-height: 16px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
button.active { background: color-mix(in srgb, var(--primary-color) 20%, transparent); color: var(--primary-color); }
button.active .label { font-weight: 700; }
button.active ha-icon { color: var(--primary-color); }
.live ha-icon { color: var(--state-media_player-active-color, #03a9f4); }
.heat ha-icon { color: var(--state-climate-heat-color, #ff5722); }
.cool ha-icon { color: var(--state-climate-cool-color, #2196f3); }
button.active.live ha-icon, button.active.heat ha-icon, button.active.cool ha-icon { color: var(--primary-color); }`;

// Number formatting that follows the user's HA number-format setting.
function formatNumber(value, hass) {
  const fmt = hass?.locale?.number_format;
  const lang = hass?.locale?.language || hass?.language || navigator.language;
  const locale = { comma_decimal: "en-US", decimal_comma: "de", space_comma: "fr", system: undefined }[fmt] ?? lang;
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 1, useGrouping: fmt !== "none" }).format(value);
  } catch {
    return String(value);
  }
}

class WallDisplayNav extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._onLocation = () => setTimeout(() => this._markActive(), 0);
  }

  setConfig(config) {
    if (!config || !Array.isArray(config.items)) throw new Error("wall-display-nav: `items` must be a list");
    this._config = config;
    this._render();
  }

  // Re-render only when an entity shown in the pill changes.
  set hass(hass) {
    this._hass = hass;
    const sig = (this._config?.items || []).map((i) => {
      const st = i.entity && hass?.states?.[i.entity];
      const a = st?.attributes || {};
      const room = i.temperature_entity && hass?.states?.[i.temperature_entity];
      const live = st ? `${st.state}|${a.current_temperature}|${a.temperature}|${a.hvac_action}` : "";
      return room ? `${live}|${room.state}` : live;
    }).join(";");
    if (sig !== this._sig) {
      this._sig = sig;
      this._updateLive();
    }
  }

  getCardSize() { return 1; }
  getGridOptions() { return { columns: "full", rows: 1, min_rows: 1 }; }

  connectedCallback() {
    window.addEventListener("location-changed", this._onLocation);
    window.addEventListener("popstate", this._onLocation);
    this._markActive();
  }

  disconnectedCallback() {
    window.removeEventListener("location-changed", this._onLocation);
    window.removeEventListener("popstate", this._onLocation);
  }

  _render() {
    const items = this._config.items;
    const pill = document.createElement("nav");
    pill.className = "pill";
    pill.style.width = `${items.length * 76 + 8}px`; // 76 px per item + 2 × 4 px padding (contracts.md)
    for (const item of items) {
      const btn = document.createElement("button");
      btn.dataset.path = String(item.path || "");
      btn.setAttribute("aria-label", item.label || item.path || "");
      btn._item = item;
      const wrap = document.createElement("span");
      wrap.className = "icon";
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", item.icon || "mdi:circle-medium");
      wrap.append(icon);
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = item.label || "";
      btn.append(wrap, label);
      btn.addEventListener("click", () => {
        navigate(`/${location.pathname.split("/")[1]}/${btn.dataset.path}`);
        this._markActive();
      });
      pill.append(btn);
    }
    const style = document.createElement("style");
    style.textContent = NAV_CSS;
    this.shadowRoot.replaceChildren(style, pill);
    this._markActive();
    this._updateLive();
  }

  // Climate items show the current temperature as label; media players glow while playing.
  _updateLive() {
    const hass = this._hass;
    this.shadowRoot.querySelectorAll("button").forEach((b) => {
      const item = b._item || {};
      const st = item.entity && hass?.states?.[item.entity];
      const domain = (item.entity || "").split(".")[0];
      let text = item.label || "";
      const room = item.temperature_entity && hass?.states?.[item.temperature_entity];
      if (room) {
        const t = Number(room.state);
        if (room.state !== "" && Number.isFinite(t)) text = `${formatNumber(t, hass)}°`;
      } else if (st && domain === "climate") {
        const t = Number(st.attributes.current_temperature);
        if (st.attributes.current_temperature != null && Number.isFinite(t)) text = `${formatNumber(t, hass)}°`;
      }
      b.querySelector(".label").textContent = text;
      // Playing: speaker-play icon in the media colour (not colour-only). Climate: heat/cool tint.
      const playing = !!st && domain === "media_player" && st.state === "playing";
      b.classList.toggle("live", playing);
      b.querySelector("ha-icon").setAttribute("icon", playing ? "mdi:speaker-play" : item.icon || "mdi:circle-medium");
      let mode = "";
      if (st && domain === "climate") {
        const { hvac_action: action, current_temperature: cur, temperature: target } = st.attributes;
        if (action === "heating" || (!action && st.state === "heat" && cur < target)) mode = "heat";
        else if (action === "cooling" || (!action && st.state === "cool" && cur > target)) mode = "cool";
      }
      b.classList.toggle("heat", mode === "heat");
      b.classList.toggle("cool", mode === "cool");
    });
  }

  _markActive() {
    const parts = location.pathname.split("/").filter(Boolean);
    const current = parts.length > 1 ? parts[parts.length - 1] : "home";
    this.shadowRoot.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.path === current;
      b.classList.toggle("active", on);
      b.setAttribute("aria-current", on ? "page" : "false");
    });
  }
}

// The frontend swaps window.customElements for a scoped-registry polyfill when app.js
// starts. Extra modules can run before that (e.g. when served from cache), and an element
// defined on the native registry then is invisible to the strategy loader. So define the
// elements only once <home-assistant> exists, always on the current window.customElements.
function defineElements() {
  const reg = window.customElements;
  if (!reg.get("ll-strategy-dashboard-wall-display")) reg.define("ll-strategy-dashboard-wall-display", WallDisplayStrategy);
  if (!reg.get("wall-display-nav")) reg.define("wall-display-nav", WallDisplayNav);
}

if (!window.__walldisplayLoaded) {
  window.__walldisplayLoaded = true;
  if (window.customElements.get("home-assistant")) defineElements();
  else window.customElements.whenDefined("home-assistant").then(defineElements);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "wall-display-nav")) {
    window.customCards.push({
      type: "wall-display-nav",
      name: "Wall display nav",
      description: "Floating pill navigation between the views of a wall display dashboard.",
      preview: false,
    });
  }
  window.customStrategies = window.customStrategies || [];
  if (!window.customStrategies.some((s) => s.type === "wall-display" && s.strategyType === "dashboard")) {
    window.customStrategies.push({
      type: "wall-display",
      strategyType: "dashboard",
      name: "Wall display",
      description: "Dashboard for a wall-mounted panel, generated by the Wall Display Dashboards integration. Add displays under Settings → Devices & services.",
    });
  }
  startPanelBehaviour();
}

function startPanelBehaviour() {
  let displays = [];
  let current = null;
  let lastHref = "";
  let lastActivity = Date.now();
  const reported = new Set();
  const injected = new Set();
  const layoutStyles = new Set();
  const layoutHosts = new Set();
  const tallTiles = new Set();
  const sizedCard = new WeakMap(); // hui-card -> the card element last sized (hui-card builds it late)
  const tileBox = new WeakMap(); // hui-card -> its last size, from the ResizeObserver
  const tileApplied = new WeakMap(); // card element -> the tall-tile sizes set on it ("" = none)
  const tileCell = new WeakMap(); // observed box -> its hui-card
  // hui-card and the card element are display: inline, which a ResizeObserver always reports
  // as 0 x 0 and never again: observe the grid cell around the card instead. All sizes are
  // read first, then the styles written, so the callback costs one layout pass at most.
  const tileObserver = new ResizeObserver((entries) => safe(() => {
    const cards = entries.map((e) => {
      const hc = tileCell.get(e.target) || e.target;
      const b = e.borderBoxSize?.[0];
      let box = b ? { width: b.inlineSize, height: b.blockSize } : { width: e.contentRect.width, height: e.contentRect.height };
      if (!box.width || !box.height) {
        const r = hc.getBoundingClientRect();
        box = { width: r.width, height: r.height };
      }
      tileBox.set(hc, box);
      return hc;
    });
    cards.forEach((hc) => safe(() => sizeTile(hc)));
  }));
  // New views, sections and re-rendered dashboards: re-check in the next frame.
  const viewObserver = new MutationObserver(() => schedule(true));
  let observed = [];
  const first = new URLSearchParams(location.search);
  const seen = { disable: first.has("disable_km"), edit: first.get("edit") === "1" };

  const getHass = () => document.querySelector("home-assistant")?.hass;
  const safe = (fn) => { try { return fn(); } catch (err) { console.debug("walldisplay:", err); } };

  // ---- scheduling: at most one tick per animation frame; its layout reads happen there ----
  let frame = 0;
  let settle = 0; // fast watchdog checks left (reset by every trigger and every change)
  let watchdog = 0;
  let watchdogMs = 0;
  const FAST_MS = 400;
  const SLOW_MS = 3000;
  const SETTLE_TICKS = 8; // ~3 s of fast checks after the last trigger or change

  function schedule(busy = false) {
    if (busy) settle = SETTLE_TICKS;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      safe(tick);
    });
  }
  // A new view renders a moment after the URL changes: check again shortly after.
  function soon() {
    settle = SETTLE_TICKS;
    schedule();
    [100, 300, 1000].forEach((ms) => setTimeout(() => schedule(), ms));
    setWatchdog();
  }
  kickPanel = soon;

  function setWatchdog() {
    const ms = !current || document.hidden ? 0 : settle > 0 ? FAST_MS : SLOW_MS;
    if (ms === watchdogMs) return;
    clearInterval(watchdog);
    watchdogMs = ms;
    watchdog = ms ? setInterval(() => {
      if (settle > 0) settle--;
      schedule();
    }, ms) : 0;
  }

  let listLoaded = false; // the display list arrived at least once this page load
  let listRetries = 0;
  async function fetchList() {
    const hass = getHass();
    if (!hass?.connection) return;
    try {
      const res = await hass.callWS({ type: `${DOMAIN}/list` });
      displays = Array.isArray(res?.displays) ? res.displays : [];
      listLoaded = true;
    } catch (err) {
      // Integration not loaded: no displays. Any other failure (e.g. reconnecting after a
      // restart) keeps the last list, so a panel doesn't drop kiosk and theme for 5 minutes.
      if (err?.code === "unknown_command") displays = [];
      // Loaded while Home Assistant was still starting: try again soon, not in 5 minutes.
      if (!listLoaded && listRetries++ < 12) setTimeout(fetchList, 10000);
    }
    lastHref = "";
    soon();
  }
  // lovelace_updated comes once per changed dashboard: one /list for a burst.
  let listTimer = 0;
  const fetchListSoon = () => {
    clearTimeout(listTimer);
    listTimer = setTimeout(fetchList, 1000);
  };

  function setLock(on) {
    const el = document.getElementById(LOCK_ID);
    if (on && !el) {
      const style = document.createElement("style");
      style.id = LOCK_ID;
      style.textContent = LOCK_CSS;
      document.head.appendChild(style);
      return true;
    }
    if (!on && el) {
      el.remove();
      return true;
    }
    return false;
  }

  // Adds <style id> to a (shadow) root once and tracks it in `set` for removal on leave. A
  // style found already in place is tracked again (a cached view can come back).
  // Returns true if a style was added.
  function inject(root, css, id = KIOSK_ID, set = injected) {
    if (!root) return false;
    const existing = root.getElementById?.(id) || root.querySelector?.(`#${id}`);
    if (existing) {
      set.add(existing);
      return false;
    }
    const style = document.createElement("style");
    style.id = id;
    style.textContent = css;
    root.appendChild(style);
    set.add(style);
    return true;
  }

  // Row height so that R rows end 16 px above the pill (or 12 px above the bottom without
  // a footer): (H - band) / R - 8, clamped 48..72. R comes from /list, else from the height.
  function rowHeight(d, viewTop, hasFooter) {
    const h = window.innerHeight - viewTop - (hasFooter ? 96 : 16);
    const rows = d.rows > 0 ? d.rows : Math.max(1, Math.floor(h / 64));
    return Math.min(72, Math.max(48, Math.floor((h / rows - 8) * 100) / 100));
  }

  // Panels stay on the dashboard for weeks while views and cards re-render: forget styles
  // whose root left the DOM, or they keep the old card trees alive.
  function prune(set) {
    set.forEach((el) => { if (!el.isConnected) set.delete(el); });
  }

  function setLayout(d, r) {
    if (!d) {
      if (!layoutStyles.size && !layoutHosts.size && !tallTiles.size) return false;
      layoutStyles.forEach((el) => el.remove());
      layoutStyles.clear();
      layoutHosts.forEach((el) => el.style.removeProperty("--wd-row-height"));
      layoutHosts.clear();
      untrackTiles();
      return true;
    }
    prune(layoutStyles);
    prune(layoutHosts);
    const viewEl = r.rootRoot?.querySelector("#view");
    let changed = inject(r.rootRoot, LAYOUT_CSS.root, LAYOUT_ID, layoutStyles);
    const sections = viewEl?.querySelector("hui-sections-view");
    changed = inject(sections?.shadowRoot, LAYOUT_CSS.view, LAYOUT_ID, layoutStyles) || changed;
    observe([viewEl, sections?.shadowRoot]);
    if (viewEl && sections) {
      // Budget for this view from /list (views[path], then the display), else from the page.
      const parts = location.pathname.split("/").filter(Boolean);
      const v = { ...d, ...(d.views?.[parts[1] || d.home || "home"] || {}) };
      // Layout reads are fine here: this runs in an animation frame, before the frame's own
      // style and layout, so they cost no extra pass.
      let hasFooter = v.footer;
      if (typeof hasFooter !== "boolean") {
        const footer = sections.shadowRoot?.querySelector("hui-view-footer");
        hasFooter = !!footer && footer.getBoundingClientRect().height > 0;
      }
      const px = `${rowHeight(v, sections.getBoundingClientRect().top, hasFooter)}px`;
      if (viewEl.style.getPropertyValue("--wd-row-height") !== px) {
        viewEl.style.setProperty("--wd-row-height", px);
        changed = true;
      }
      layoutHosts.add(viewEl);
      changed = trackTiles(sections) || changed;
    }
    return changed;
  }

  // Re-check when the view's light DOM or the sections view's shadow tree changes.
  function observe(targets) {
    const list = targets.filter(Boolean);
    if (list.length === observed.length && list.every((t, i) => t === observed[i])) return;
    viewObserver.disconnect();
    list.forEach((t) => viewObserver.observe(t, { childList: true, subtree: true }));
    observed = list;
  }

  // Top-level cards of the current view: hui-section > hui-grid-section (shadow) > hui-card.
  function viewCards(sections) {
    return [...(sections?.shadowRoot?.querySelectorAll("hui-section") || [])]
      .flatMap((sec) => [...(sec.querySelector("hui-grid-section")?.shadowRoot?.querySelectorAll("hui-card") || [])]);
  }

  // Sizes come from the ResizeObserver; styles are written only when they change.
  function sizeTile(hc) {
    const card = hc.firstElementChild;
    if (!card || !TALL_TILE_TAGS.includes(card.localName)) return;
    sizedCard.set(hc, card);
    const box = tileBox.get(hc);
    if (!box) return; // the observer reports it shortly
    const sizes = hc.config?.features?.length ? null : tallTileSizes(box.width, box.height);
    const key = sizes ? `${sizes.icon}/${sizes.glyph}/${sizes.name}` : "";
    if (tileApplied.get(card) === key) return;
    tileApplied.set(card, key);
    if (!sizes) {
      TALL_TILE_PROPS.forEach((prop) => card.style.removeProperty(prop));
      return;
    }
    inject(card.shadowRoot, TALL_TILE_CSS, LAYOUT_ID, layoutStyles);
    card.style.setProperty("--wd-tile-icon-size", `${sizes.icon}px`);
    card.style.setProperty("--wd-tile-icon-glyph", `${sizes.glyph}px`);
    card.style.setProperty("--ha-tile-info-primary-font-size", `${sizes.name}px`);
    card.style.setProperty("--ha-tile-info-primary-line-height", "1.25");
  }

  // Watch the view's tile cards; forget cards that left the DOM (view changes re-render).
  function trackTiles(sections) {
    let changed = false;
    for (const hc of tallTiles) {
      if (!hc.isConnected) {
        tileObserver.unobserve(hc.__wdCell || hc);
        tallTiles.delete(hc);
      }
    }
    for (const hc of viewCards(sections)) {
      if (!tallTiles.has(hc)) {
        tallTiles.add(hc);
        // The card's own grid cell (one card per cell), else the card itself.
        const parent = hc.parentElement;
        const cell = parent && parent.childElementCount === 1 ? parent : hc;
        hc.__wdCell = cell;
        tileCell.set(cell, hc);
        tileObserver.observe(cell);
        changed = true;
      } else if (hc.firstElementChild && sizedCard.get(hc) !== hc.firstElementChild) {
        // hui-card built (or rebuilt) its card element; remember it for every card type, or
        // a clock or grid card would count as a change on every tick.
        sizedCard.set(hc, hc.firstElementChild);
        sizeTile(hc);
        changed = true;
      }
    }
    return changed;
  }

  function untrackTiles() {
    tileObserver.disconnect();
    tallTiles.forEach((hc) => {
      const card = hc.firstElementChild;
      if (card) {
        TALL_TILE_PROPS.forEach((prop) => card.style.removeProperty(prop));
        tileApplied.delete(card);
      }
    });
    tallTiles.clear();
  }

  function kioskRoots() {
    const main = document.querySelector("home-assistant")?.shadowRoot?.querySelector("home-assistant-main");
    const mainRoot = main?.shadowRoot;
    const drawerRoot = mainRoot?.querySelector("ha-drawer")?.shadowRoot;
    const panel = mainRoot?.querySelector("partial-panel-resolver")?.querySelector("ha-panel-lovelace");
    const rootRoot = panel?.shadowRoot?.querySelector("hui-root")?.shadowRoot;
    return { main, mainRoot, drawerRoot, panel, rootRoot };
  }

  function setKiosk(on, r) {
    if (!on) {
      if (!injected.size) return false;
      injected.forEach((el) => el.remove());
      injected.clear();
      return true;
    }
    prune(injected);
    let changed = inject(r.mainRoot, KIOSK_CSS.main);
    changed = inject(r.drawerRoot, KIOSK_CSS.drawer) || changed;
    changed = inject(r.rootRoot, KIOSK_CSS.root) || changed;
    if (r.main && !r.main.__walldisplayMenuBlock) {
      r.main.__walldisplayMenuBlock = true;
      r.main.addEventListener("hass-toggle-menu", (ev) => {
        if (injected.size) ev.stopImmediatePropagation();
      }, true);
    }
    return changed;
  }

  // Sticky for the page load: HA drops ?edit=1 from the URL once edit mode opens.
  let lastSearch = null;
  function kioskSkipped() {
    if (location.search !== lastSearch) {
      lastSearch = location.search;
      const p = new URLSearchParams(lastSearch);
      if (p.has("disable_km")) seen.disable = true;
      if (p.get("edit") === "1") seen.edit = true;
    }
    return seen.disable || (seen.edit && !!getHass()?.user?.is_admin);
  }

  function editing(r = kioskRoots()) {
    return !!r.panel?.lovelace?.editMode || seen.edit;
  }

  function goHome(display) {
    const d = display || current;
    if (!d) return;
    const target = `/${d.url_path}/${d.home || "home"}`;
    // An open HA dialog is its own history entry ({dialog}; the entry below carries
    // {opensDialog}), so back() pops exactly that entry and HA closes the dialog.
    if (!history.state?.dialog) {
      navigate(target);
      return;
    }
    let done = false;
    const go = () => {
      if (done) return;
      done = true;
      window.removeEventListener("popstate", go);
      setTimeout(() => safe(() => navigate(target)), 0);
    };
    window.addEventListener("popstate", go, { once: true });
    history.back(); // closes the more-info dialog
    setTimeout(go, 500); // fallback if no popstate arrives
  }

  // Only the panel itself reports: a non-admin user, or the ShellyElevate app. A desktop
  // admin browsing the dashboard would otherwise raise a false viewport-mismatch repair.
  async function report(d) {
    reported.add(d.entry_id);
    const hass = getHass();
    if (!hass) return;
    if (hass.user?.is_admin && !inShellyElevate()) return;
    const msg = {
      type: `${DOMAIN}/report_viewport`,
      entry_id: d.entry_id,
      width: Math.round(window.innerWidth),
      height: Math.round(window.innerHeight),
      dpr: window.devicePixelRatio || 1,
      user_agent: navigator.userAgent,
    };
    const device = safe(() => window.ShellyElevate?.getDevice?.());
    if (device) msg.device = String(device);
    try { await hass.callWS(msg); } catch (err) { console.debug("walldisplay: report_viewport failed", err); }
  }

  function tick() {
    const seg = location.pathname.split("/")[1];
    const d = displays.find((x) => x?.url_path === seg) || null;
    let changed = false;
    if (location.href !== lastHref || d !== current) {
      lastHref = location.href;
      if (d && !current) lastActivity = Date.now();
      current = d;
      changed = true;
      if (d && !reported.has(d.entry_id)) report(d);
    }
    // The shadow roots are looked up once per tick, not kept: the lovelace panel
    // re-renders and new ones appear.
    const r = d ? kioskRoots() : null;
    // The editor (after "take control") must scroll, so edit mode lifts the lock.
    changed = setLock(!!d && !editing(r)) || changed;
    const skipped = kioskSkipped();
    changed = setKiosk(!!d && d.kiosk === "builtin" && !skipped, r) || changed;
    changed = setLayout(d && !skipped ? d : null, r) || changed;
    if (!d || skipped) observe([]);
    autoDark(d && !skipped ? d : null, getHass());
    if (changed) settle = SETTLE_TICKS;
    setWatchdog();
  }

  // Auto dark (panel users only: a non-admin or the ShellyElevate app). Follows sun.sun with
  // HA's own `settheme` event ({dark}); the theme selected before is kept in localStorage (so
  // it survives reloads) and restored on leaving, or on the next page load if the page was
  // closed meanwhile (not on unload: a reload would flash the light theme). If the user
  // changes the theme on the dashboard, nothing is re-applied until the next sun transition,
  // and it is not restored. The stored entry names its user, so an admin who later uses the
  // same browser never gets the panel user's theme.
  const THEME_KEY = "walldisplay-prev-theme";
  // active: auto dark ran since the last restore (null = not evaluated yet this page load).
  const theme = { sun: null, applied: undefined, override: false, active: null };
  const started = Date.now();
  let themeWait = 0;
  const store = (fn) => { try { return fn(window.localStorage); } catch { return null; } };
  const setTheme = (detail) => document.querySelector("home-assistant")?.dispatchEvent(
    new CustomEvent("settheme", { detail, bubbles: true, composed: true }));

  function restoreTheme(hass) {
    const raw = store((ls) => ls.getItem(THEME_KEY));
    if (raw === null) return;
    const prev = safe(() => JSON.parse(raw)) || {};
    if (prev.user && prev.user !== hass.user?.id) return; // another user's entry
    if (!theme.override) setTheme({ dark: prev.dark ?? undefined });
    store((ls) => ls.removeItem(THEME_KEY));
  }

  function autoDark(d, hass) {
    // Before the display list is known, "not a wall dashboard" would restore the theme.
    if (!hass || !listLoaded) return;
    // Give the synced theme preferences a moment to load after start-up.
    const wait = 3000 - (Date.now() - started);
    if (wait > 0) {
      if (!themeWait) themeWait = setTimeout(() => schedule(), wait + 50);
      return;
    }
    const panelUser = !hass.user?.is_admin || inShellyElevate();
    const sun = d && panelUser ? hass.states?.["sun.sun"]?.state : undefined;
    if (!sun) {
      if (theme.active === false) return; // nothing to undo: no storage access per tick
      restoreTheme(hass);
      Object.assign(theme, { sun: null, applied: undefined, override: false, active: false });
      return;
    }
    theme.active = true;
    const dark = hass.selectedTheme?.dark;
    if (sun !== theme.sun) Object.assign(theme, { sun, override: false }); // a sun transition
    else if (theme.applied !== undefined && dark !== theme.applied) theme.override = true;
    const want = sun === "below_horizon";
    if (theme.override) return;
    if (dark === want) {
      // Already right (e.g. applied before a reload): a later change is the user's choice.
      theme.applied = want;
      return;
    }
    if (store((ls) => ls.getItem(THEME_KEY)) === null) {
      store((ls) => ls.setItem(THEME_KEY, JSON.stringify({ dark: dark ?? null, user: hass.user?.id })));
    }
    theme.applied = want;
    setTheme({ dark: want });
  }

  function idleCheck() {
    const d = current;
    if (!d || !(d.idle_seconds > 0) || editing()) return;
    if (Date.now() - lastActivity < d.idle_seconds * 1000) return;
    lastActivity = Date.now();
    const atHome = location.pathname === `/${d.url_path}/${d.home || "home"}`;
    if (!atHome || history.state?.dialog) goHome(d);
  }

  for (const type of ACTIVITY_EVENTS) {
    window.addEventListener(type, () => { lastActivity = Date.now(); }, { capture: true, passive: true });
  }
  window.addEventListener("location-changed", soon);
  window.addEventListener("resize", soon);
  window.addEventListener("popstate", soon);
  document.addEventListener("visibilitychange", () => (document.hidden ? setWatchdog() : soon()));
  setInterval(() => safe(idleCheck), 5000);

  if (inShellyElevate()) {
    window.walldisplayScreenOn = () => safe(() => { lastActivity = Date.now(); goHome(); });
    safe(() => window.ShellyElevate.bind("onScreenOn", "walldisplayScreenOn"));
  }

  // Wait for the frontend's hass object, then load the display list and keep it fresh.
  const boot = setInterval(() => {
    const hass = getHass();
    if (!hass?.connection || !hass.user) return;
    clearInterval(boot);
    fetchList();
    safe(() => hass.connection.subscribeEvents(fetchListSoon, "lovelace_updated"))?.catch?.(() => {});
    // Auto dark follows sun.sun the moment it changes (one entity, filtered server-side).
    safe(() => hass.connection.subscribeMessage(() => schedule(),
      { type: "subscribe_entities", entity_ids: ["sun.sun"] }))?.catch?.(() => {});
    setInterval(fetchList, 5 * 60 * 1000);
  }, 250);
}
