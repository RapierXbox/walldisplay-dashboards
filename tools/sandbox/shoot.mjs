// Screenshots + layout assertions for every profile and view, plus behaviour checks
// for walldisplay.js (kiosk, scroll lock, idle -> home, viewport report, admin pages, tall
// tiles scaled up).
//
//   node shoot.mjs [--only shelly_xl] [--no-behaviour] [--no-variants]
//
// Variants: <profile>@entrance (display "Entrance", role entrance) and <profile>@de
// (server + user language German, restored afterwards).
//
// Writes out/<profile>__<view>.png and out/report.json. Exit code 1 if a check fails.
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";
import { BASE, DEEP_QUERY_SRC, OUT, PROFILES, USERS, connectWs, login, rest, seedTokens, sleep, warmUp } from "./lib.mjs";

const args = process.argv.slice(2);
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const VIEWS = ["home", "climate", "media", "scenes"];
const MAIN_TITLE = "Kitchen";
const log = (...a) => console.log("[shoot]", ...a);

// Record websocket messages the page sends (to see report_viewport).
const WS_SPY = `
  window.__wsSent = [];
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) { try { window.__wsSent.push(String(data)); } catch {} return send.call(this, data); };
`;

const MEASURE = `
  (() => {
    const r = (e) => { const b = e.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }; };
    // An empty footer (Home is the only page) renders with a zero-size box: treat as none,
    // and keep the 24 px bottom margin as the limit.
    const footerEl = __deepAll("hui-view-footer")[0];
    const footer = footerEl && footerEl.getBoundingClientRect().height > 0 ? footerEl : null;
    const footerTop = footer ? footer.getBoundingClientRect().top : innerHeight - 12;
    const view = __deepAll("hui-sections-view")[0];
    const cards = view ? [...view.shadowRoot.querySelectorAll(".section")].flatMap((s) => __deepAll("hui-card", s))
      .filter((c) => !c.parentElement?.closest?.("hui-card"))
      .map((c) => {
        // Content cut off inside the card: ha-card taller inside than its box.
        const ha = c.firstElementChild?.shadowRoot?.querySelector("ha-card");
        const clipped = !!ha && ha.scrollHeight > ha.clientHeight + 2 && getComputedStyle(ha).overflow !== "visible";
        return { type: c.config?.type, entity: c.config?.entity, rect: r(c), clipped };
      }).filter((c) => c.rect.h > 0) : [];
    const sections = view ? [...view.shadowRoot.querySelectorAll(".section")].map(r) : [];
    const overFooter = cards.filter((c) => c.rect.y + c.rect.h > footerTop + 0.5);
    const offRight = cards.filter((c) => c.rect.x + c.rect.w > innerWidth + 0.5);
    // Truncation: any element with text-overflow: ellipsis whose content is wider than its box.
    const all = view ? __deepAll("*", view.shadowRoot) : [];
    const ownText = (e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    const visible = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && b.bottom > 0 && b.top < innerHeight; };
    const truncated = all
      .filter((e) => e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).textOverflow === "ellipsis" && (e.textContent || "").trim())
      .map((e) => ({ text: e.textContent.trim().slice(0, 60), scrollWidth: e.scrollWidth, clientWidth: e.clientWidth }));
    // Text under 14 px in tiles and the pill (AM/PM of the clock excepted).
    const scopes = [...__deepAll("hui-tile-card", view?.shadowRoot || document), ...__deepAll("wall-display-nav", view?.shadowRoot || document)];
    const smallText = scopes.flatMap((sc) => __deepAll("*", sc.shadowRoot || sc))
      .filter((e) => ownText(e) && visible(e) && parseFloat(getComputedStyle(e).fontSize) < 13.9 && !/^(AM|PM)$/i.test(e.textContent.trim()))
      .map((e) => ({ text: e.textContent.trim().slice(0, 40), size: getComputedStyle(e).fontSize }));
    // Tall top-level tiles without features (e.g. XL/tablet Scenes): walldisplay.js scales the
    // icon up. Cards nested in a grid card (the info column) keep HA's size.
    const bigTiles = view ? __deepAll("hui-grid-section", view.shadowRoot)
      .flatMap((g) => [...(g.shadowRoot?.querySelectorAll("hui-card") || [])])
      .map((hc) => hc.firstElementChild).filter((c) => c?.localName === "hui-tile-card").map((c) => {
      const hc = c.parentElement;
      const icon = c.shadowRoot?.querySelector("ha-tile-icon");
      return { entity: hc?.config?.entity, rect: r(c), features: !!hc?.config?.features?.length,
        icon: icon ? parseFloat(getComputedStyle(icon).getPropertyValue("--tile-icon-size")) || null : null };
    }).filter((t) => t.rect.h >= 176 && t.rect.w >= 180 && !t.features) : [];
    const haEl = document.querySelector("home-assistant");
    const dark = !!haEl?.hass?.themes?.darkMode;
    const header = __deepAll("hui-root")[0]?.shadowRoot?.querySelector(".header");
    const shell = __deepAll(".sidebar-shell")[0];
    const pill = __deepAll("wall-display-nav")[0]?.shadowRoot?.querySelector(".pill");
    const nav = pill ? {
      rect: r(pill),
      active: [...pill.querySelectorAll("button.active")].map((b) => b.dataset.path),
      buttons: [...pill.querySelectorAll("button")].map((b) => ({ path: b.dataset.path, rect: r(b) })),
    } : null;
    return {
      innerWidth, innerHeight,
      scrollHeight: document.scrollingElement.scrollHeight,
      scrolls: document.scrollingElement.scrollHeight > innerHeight,
      footer: footer ? r(footer) : null,
      sections, cards, overFooter, offRight, truncated, smallText, dark, bigTiles,
      rowHeight: parseFloat(getComputedStyle(__deepAll("hui-root")[0]?.shadowRoot?.querySelector("#view") || document.body).getPropertyValue("--wd-row-height")) || null,
      headerVisible: !!header && header.getBoundingClientRect().height > 0,
      sidebarVisible: !!shell && shell.getBoundingClientRect().width > 0,
      lock: !!document.getElementById("walldisplay-lock"),
      kioskStyles: __deepAll("#walldisplay-kiosk").length,
      nav,
      errorCard: __deepAll("hui-markdown-card").some((m) => /unavailable|Error loading/i.test(m.shadowRoot?.textContent || m.textContent || "")),
    };
  })()
`;

async function openPage(browser, tokens, w, h, dsf = 1) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf });
  await page.setExtraHTTPHeaders({ "accept-language": "en-US,en" });
  await page.evaluateOnNewDocument(WS_SPY);
  await seedTokens(page, tokens);
  return page;
}

async function go(page, url, wait = 3500) {
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2" });
  await page.evaluate(DEEP_QUERY_SRC);
  // Wait until a view (or any other panel) has rendered, then let cards settle.
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    const ready = await page.evaluate(() => __deepAll("hui-sections-view, hui-masonry-view, ha-config-dashboard, ha-panel-history").length > 0).catch(() => false);
    if (ready) break;
    await sleep(500);
  }
  await sleep(wait);
  await page.evaluate(DEEP_QUERY_SRC);
}

// Client-side navigation, the way HA navigates.
const spaNavigate = (page, url) => page.evaluate((u) => {
  history.pushState(null, "", u);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}, url);

async function displays(adminToken, panelToken) {
  const entries = await rest(adminToken, "GET", "/api/config/config_entries/entry?domain=walldisplay_dashboards");
  const ws = await connectWs(panelToken);
  const list = (await ws.call({ type: "walldisplay_dashboards/list" })).displays;
  ws.close();
  return list.map((d) => ({ ...d, title: entries.find((e) => e.entry_id === d.entry_id)?.title }));
}

// sun.sun drives the auto dark mode. The sun integration is disabled for the run (it would
// rewrite the state within minutes), so a POSTed sun.sun stays put; re-enabled at the end.
let sunPin = null;
let adminToken = null;
let sunEntries = [];
async function pinSun(state = sunPin) {
  if (!state || !adminToken) return;
  sunPin = state;
  const cur = await rest(adminToken, "GET", "/api/states/sun.sun").catch(() => null);
  if (cur?.state !== state) await rest(adminToken, "POST", "/api/states/sun.sun", { state, attributes: cur?.attributes || { friendly_name: "Sun" } });
}
async function sunIntegration(enable) {
  const ws = await connectWs(adminToken);
  try {
    if (!enable) sunEntries = (await rest(adminToken, "GET", "/api/config/config_entries/entry?domain=sun")).filter((e) => !e.disabled_by);
    // Drop the POSTed state first, or the re-enabled integration can't register sun.sun.
    else await rest(adminToken, "DELETE", "/api/states/sun.sun").catch(() => {});
    for (const e of sunEntries) await ws.call({ type: "config_entries/disable", entry_id: e.entry_id, disabled_by: enable ? null : "user" });
  } finally {
    ws.close();
  }
}

// View paths as generated for this display (pages exist only when the room has entities).
async function viewPaths(token, d) {
  const ws = await connectWs(token);
  try {
    const cfg = await ws.call({ type: "walldisplay_dashboards/generate", entry_id: d.entry_id });
    return (cfg.views || []).map((v, i) => v.path || String(i));
  } catch {
    return VIEWS;
  } finally {
    ws.close();
  }
}

// Screenshot + checks for every view of one display at one size.
async function shootDisplay(browser, tokens, label, d, w, h, report, fail, onlyViews = null) {
  await pinSun();
  const views = (await viewPaths(tokens.access_token, d)).filter((v) => !onlyViews || onlyViews.includes(v));
  const page = await openPage(browser, tokens, w, h, 2);
  report.profiles[label] = { url_path: d.url_path, size: [w, h], views: {} };
  for (const v of views) {
    await go(page, `/${d.url_path}/${v}`);
    const m = await page.evaluate(MEASURE);
    report.profiles[label].views[v] = m;
    await page.screenshot({ path: path.join(OUT, `${label}__${v}.png`) });
    const tag = `${label}/${v}`;
    if (m.errorCard) fail(`${tag}: error card shown`);
    if (m.scrollHeight > h) fail(`${tag}: page scrolls (${m.scrollHeight} > ${h})`);
    if (m.overFooter.length) fail(`${tag}: ${m.overFooter.length} card(s) reach into the footer`);
    const clipped = m.cards.filter((c) => c.clipped);
    if (clipped.length) fail(`${tag}: clipped content in ${clipped.map((c) => c.entity || c.type).join(", ")}`);
    if (m.offRight.length) fail(`${tag}: ${m.offRight.length} card(s) off the right edge`);
    if (m.truncated.length) fail(`${tag}: truncated text ${m.truncated.map((t) => JSON.stringify(t.text)).join(", ")}`);
    if (m.smallText.length) fail(`${tag}: text under 14 px ${m.smallText.map((t) => `${JSON.stringify(t.text)} ${t.size}`).join(", ")}`);
    if (sunPin && m.dark !== (sunPin === "below_horizon")) fail(`${tag}: dark mode ${m.dark} with sun ${sunPin}`);
    const unscaled = m.bigTiles.filter((t) => !(t.icon >= 56));
    if (unscaled.length) fail(`${tag}: ${unscaled.length} tall tile(s) not scaled (icon ${unscaled.map((t) => `${t.icon}px in ${t.rect.w}x${t.rect.h}`).join(", ")}, expected >= 56)`);
    if (d.kiosk === "builtin" && (m.headerVisible || m.sidebarVisible)) fail(`${tag}: kiosk chrome visible`);
    if (!m.lock) fail(`${tag}: scroll lock style missing`);
    if (m.nav && m.nav.rect.w > w - 16) fail(`${tag}: nav pill ${m.nav.rect.w}px wider than screen - 16`);
    // Spacing (docs/design-spacing.md): 12 px frame, grid ends 16 px above the pill, pill 20 px
    // from the bottom; without a footer the grid ends 12 px above the bottom. Rows are floored
    // to 0.01 px, so allow 1 px plus R hundredths.
    if (m.cards.length) {
      const top = Math.min(...m.cards.map((c) => c.rect.y));
      const bottom = Math.max(...m.cards.map((c) => c.rect.y + c.rect.h));
      const rows = d.rows || 10;
      const tol = Math.max(2, 1 + rows * 0.01 + 0.5); // 16 ± 2 px (rows floored to 0.01 px, rects rounded)
      // Documented exception: tablet Home may keep one spare row (layout pass 2).
      const profile = label.split("@")[0];
      const spare = v === "home" && (profile === "tablet_portrait" || profile === "tablet_landscape") ? (m.rowHeight || 56) + 8 : 0;
      const g = w <= 600 ? 8 : 12;
      const left = Math.min(...m.sections.map((x) => x.x));
      const right = w - Math.max(...m.sections.map((x) => x.x + x.w));
      m.spacing = { top, bottom, left, right, rowHeight: m.rowHeight };
      if (Math.abs(top - 12) > 1) fail(`${tag}: first card at y ${top}, expected 12`);
      if (left < g - 1 || Math.abs(left - right) > 1) fail(`${tag}: side frame ${left}/${right}, expected >= ${g} and centred`);
      if (m.nav) {
        const gap = m.nav.rect.y - bottom;
        const pillBottom = h - (m.nav.rect.y + m.nav.rect.h);
        Object.assign(m.spacing, { gapToPill: gap, pillBottom });
        if (spare && gap > 16 + tol && gap <= 16 + spare + tol) m.spacing.spareRow = true;
        else if (Math.abs(gap - 16) > tol) fail(`${tag}: gap to pill ${gap}px, expected 16 ± ${tol.toFixed(1)}`);
        if (Math.abs(pillBottom - 20) > 1) fail(`${tag}: pill ${pillBottom}px from the bottom, expected 20`);
      } else if (!m.footer && Math.abs(h - 12 - bottom) > tol && !(spare && h - 12 - bottom <= spare + tol)) {
        fail(`${tag}: grid ends ${h - bottom}px above the bottom, expected 12`);
      }
    }
    // Pages outside the nav (e.g. "more") highlight nothing.
    const expected = m.nav?.buttons.some((x) => x.path === v) ? v : "";
    if (m.nav && m.nav.active.join() !== expected) fail(`${tag}: nav active item "${m.nav.active.join()}" != "${expected}"`);
    log(`${tag}: ${m.cards.length} cards, scroll ${m.scrollHeight}/${h}, row ${m.rowHeight}px, gap to pill ${m.spacing?.gapToPill ?? "-"}${m.bigTiles.length ? `, ${m.bigTiles.length} tall tiles (icon ${m.bigTiles[0].icon}px)` : ""}`);
  }
  await page.close();
}

const LOCALE = (language) => ({ language, number_format: "language", time_format: "language", date_format: "language", first_weekday: "language", time_zone: "local" });

// German variant: server language (labels written by the generator) and the panel user's
// frontend language are switched to "de" for the shots, then restored.
async function shootGerman(admin, panel, list, main, report, fail) {
  const aws = await connectWs(admin.access_token);
  const pws = await connectWs(panel.access_token);
  const before = (await aws.call({ type: "get_config" })).language || "en";
  try {
    await aws.call({ type: "config/core/update", language: "de" });
    await pws.call({ type: "frontend/set_user_data", key: "language", value: LOCALE("de") });
    const browser = await puppeteer.launch({ headless: true, args: ["--lang=de-DE"] });
    try {
      await warmUp(browser, panel, `/${main.url_path}/home`);
      for (const profile of ["shelly_wall_display", "shelly_x2_landscape"]) {
        const d = profile === "shelly_wall_display" ? main : list.find((x) => x.title === `Test ${profile}`);
        if (d) await shootDisplay(browser, panel, `${profile}@de`, d, ...PROFILES[profile], report, fail);
      }
    } finally {
      await browser.close();
    }
  } finally {
    await aws.call({ type: "config/core/update", language: before }).catch(() => {});
    await pws.call({ type: "frontend/set_user_data", key: "language", value: LOCALE("en") }).catch(() => {});
    aws.close();
    pws.close();
  }
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await login(USERS.admin);
  const panel = await login(USERS.panel);
  const list = await displays(admin.access_token, panel.access_token);
  const main = list.find((d) => d.title === MAIN_TITLE) || list[0];
  if (!main) throw new Error("no wall displays configured; run setup.mjs first");
  const byProfile = (p) => (p === "shelly_wall_display" ? main : list.find((d) => d.title === `Test ${p}`));

  adminToken = admin.access_token;
  await sunIntegration(false);
  await sleep(2000);
  await pinSun("above_horizon"); // day run: light theme
  const browser = await puppeteer.launch({ headless: true, args: ["--lang=en-US"] });
  await warmUp(browser, panel, `/${main.url_path}/home`);
  const report = { base: BASE, generated: new Date().toISOString(), profiles: {}, behaviour: {}, failures: [] };
  const fail = (msg) => { report.failures.push(msg); log("FAIL", msg); };
  try {
    for (const [profile, [w, h]] of Object.entries(PROFILES)) {
      if (only && profile !== only) continue;
      const d = byProfile(profile);
      if (!d) { log(`no display for ${profile}, skipped`); continue; }
      await shootDisplay(browser, panel, profile, d, w, h, report, fail);
    }
    if (!args.includes("--no-variants")) {
      const entrance = list.find((d) => d.title === "Entrance");
      if (entrance) await shootDisplay(browser, panel, "shelly_wall_display@entrance", entrance, 480, 480, report, fail);
      else log("no Entrance display, @entrance skipped");
      // Crowded room (14 extra lamps) and a weather entity without forecast support.
      const busy = list.find((d) => d.title === "Busy");
      if (busy) await shootDisplay(browser, panel, "shelly_wall_display@busy", busy, 480, 480, report, fail);
      const noForecast = list.find((d) => d.title === "No forecast");
      if (noForecast) await shootDisplay(browser, panel, "shelly_xl@noforecast", noForecast, ...PROFILES.shelly_xl, report, fail);
    }
    if (!args.includes("--no-behaviour")) await behaviour(browser, admin, panel, main, report, fail);
    if (!args.includes("--no-variants")) await night(browser, panel, list, main, report, fail);
  } finally {
    await browser.close();
  }
  try {
    if (!args.includes("--no-variants")) await shootGerman(admin, panel, list, main, report, fail);
  } finally {
    await sunIntegration(true).catch((err) => log("could not re-enable sun:", err.message));
    fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 1));
  }
  log(report.failures.length ? `${report.failures.length} failure(s)` : "all checks passed");
  process.exitCode = report.failures.length ? 1 : 0;
}

// Night: sun below the horizon -> dark Home at 480 and 960; then the theme rules:
// restored on leaving, and a theme chosen by the user on the dashboard is left alone.
async function night(browser, panel, list, main, report, fail) {
  await pinSun("below_horizon");
  const x2 = list.find((x) => x.title === "Test shelly_x2_landscape");
  await shootDisplay(browser, panel, "shelly_wall_display@night", main, 480, 480, report, fail, ["home"]);
  if (x2) await shootDisplay(browser, panel, "shelly_x2_landscape@night", x2, 960, 480, report, fail, ["home"]);
  const b = report.behaviour;
  const themeState = (page) => page.evaluate(() => {
    const hass = document.querySelector("home-assistant").hass;
    let stored = null;
    try { stored = localStorage.getItem("walldisplay-prev-theme"); } catch {}
    return { darkMode: !!hass.themes?.darkMode, selectedDark: hass.selectedTheme?.dark ?? null, stored };
  });
  let page = await openPage(browser, panel, 480, 480);
  await go(page, `/${main.url_path}/home`, 5000);
  const atNight = await themeState(page);
  await spaNavigate(page, "/history");
  await sleep(2000);
  const afterLeave = await themeState(page);
  b.autoDark = { atNight, afterLeave };
  if (!atNight.darkMode || atNight.stored === null) fail(`auto dark: not applied ${JSON.stringify(atNight)}`);
  if (afterLeave.stored !== null || afterLeave.selectedDark === true) fail(`auto dark: not restored on leave ${JSON.stringify(afterLeave)}`);
  await page.close();

  page = await openPage(browser, panel, 480, 480);
  await go(page, `/${main.url_path}/home`, 5000);
  await page.evaluate(() => document.querySelector("home-assistant").dispatchEvent(new CustomEvent("settheme", { detail: { dark: false } })));
  await sleep(3000);
  const overridden = await themeState(page);
  b.autoDark.userOverride = overridden;
  if (overridden.darkMode) fail(`auto dark: re-applied over the user's choice ${JSON.stringify(overridden)}`);
  await spaNavigate(page, "/history");
  await sleep(1500);
  await page.close();
  await pinSun("above_horizon");
}

async function behaviour(browser, admin, panel, d, report, fail) {
  const b = report.behaviour;
  const home = `/${d.url_path}/home`;

  // Scroll lock: at a small viewport the content is taller than the window, the wheel must not scroll.
  let page = await openPage(browser, panel, 480, 300);
  await go(page, home);
  await page.mouse.move(240, 150);
  await page.mouse.wheel({ deltaY: 600 });
  await sleep(600);
  b.scrollLock = await page.evaluate(() => ({
    scrollHeight: document.scrollingElement.scrollHeight, innerHeight, scrollY: window.scrollY,
    overflow: getComputedStyle(document.documentElement).overflow,
  }));
  if (b.scrollLock.scrollY !== 0) fail(`scroll lock: page scrolled to ${b.scrollLock.scrollY}`);

  // Viewport report: sent once for this load.
  const sent = await page.evaluate(() => window.__wsSent.filter((s) => s.includes("report_viewport")));
  b.viewportReports = sent.map((s) => JSON.parse(s));
  if (sent.length !== 1) fail(`viewport report: expected 1 message, saw ${sent.length}`);

  // Pill nav: tapping an item navigates inside the frontend and moves the highlight.
  const navNow = (await page.evaluate(MEASURE)).nav;
  const target = navNow?.buttons.find((x) => x.path !== "home");
  if (target) {
    await page.mouse.click(target.rect.x + target.rect.w / 2, target.rect.y + target.rect.h / 2);
    await sleep(1500);
    await page.evaluate(DEEP_QUERY_SRC);
    const after = await page.evaluate(MEASURE);
    b.navTap = { clicked: target.path, path: await page.evaluate(() => location.pathname), active: after.nav?.active };
    if (b.navTap.path !== `/${d.url_path}/${target.path}` || after.nav?.active.join() !== target.path) fail(`nav tap: ${JSON.stringify(b.navTap)}`);
  } else {
    b.navTap = "skipped (no wall-display-nav footer)";
  }

  // Leaving the dashboard (client-side) removes the lock and the kiosk styles.
  await spaNavigate(page, "/history");
  await sleep(2500);
  await page.evaluate(DEEP_QUERY_SRC);
  b.leave = await page.evaluate(() => ({
    lock: !!document.getElementById("walldisplay-lock"),
    kioskStyles: __deepAll("#walldisplay-kiosk").length,
  }));
  if (b.leave.lock || b.leave.kioskStyles) fail(`leaving: lock ${b.leave.lock}, kiosk styles ${b.leave.kioskStyles}`);
  await page.close();

  // Idle -> home, with a more-info dialog open on another view.
  const idle = d.idle_seconds || 0;
  b.idleSeconds = idle;
  if (idle > 0 && idle <= 120) {
    page = await openPage(browser, panel, 480, 480);
    await go(page, `/${d.url_path}/climate`);
    await page.evaluate(() => document.querySelector("home-assistant").dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: "climate.kitchen" }, bubbles: true, composed: true,
    })));
    await sleep(1500);
    const before = await page.evaluate(() => ({ path: location.pathname, dialog: history.state?.dialog || null }));
    await sleep(idle * 1000 + 7000);
    await page.evaluate(DEEP_QUERY_SRC);
    const after = await page.evaluate(() => ({
      path: location.pathname, dialog: history.state?.dialog || null,
      dialogOpen: __deepAll("ha-more-info-dialog").some((e) => e.shadowRoot?.querySelector("[open], ha-dialog, ha-adaptive-dialog") && e.getBoundingClientRect().height > 0),
    }));
    b.idle = { before, after };
    if (after.path !== home) fail(`idle: expected ${home}, got ${after.path}`);
    if (after.dialog) fail("idle: dialog still in history state");
    await page.close();
  } else {
    b.idle = "skipped (idle_seconds 0 or > 120)";
  }

  // Admin: /config untouched; wall dashboard with ?edit=1 keeps HA chrome.
  page = await openPage(browser, admin, 1280, 752);
  await go(page, home);
  b.adminViewportReports = await page.evaluate(() => window.__wsSent.filter((x) => x.includes("report_viewport")).length);
  if (b.adminViewportReports) fail(`admin: sent ${b.adminViewportReports} viewport report(s)`);
  await go(page, "/config/dashboard");
  b.adminConfig = await page.evaluate(() => ({ lock: !!document.getElementById("walldisplay-lock"), kioskStyles: __deepAll("#walldisplay-kiosk").length }));
  if (b.adminConfig.lock || b.adminConfig.kioskStyles) fail("admin /config: locked or kiosk styles present");
  await go(page, `${home}?edit=1`);
  b.adminEdit = await page.evaluate(MEASURE);
  // On a strategy dashboard ?edit=1 opens HA's raw config editor; kiosk must stay off.
  b.adminEdit = { kioskStyles: b.adminEdit.kioskStyles, sidebarVisible: b.adminEdit.sidebarVisible, lock: b.adminEdit.lock };
  if (b.adminEdit.kioskStyles || !b.adminEdit.sidebarVisible) fail(`admin ?edit=1: kiosk applied ${JSON.stringify(b.adminEdit)}`);
  await go(page, home);
  const adminKiosk = await page.evaluate(MEASURE);
  b.adminDashboard = { headerVisible: adminKiosk.headerVisible, sidebarVisible: adminKiosk.sidebarVisible };
  await page.screenshot({ path: path.join(OUT, "admin__home.png") });
  await page.close();

  // ?disable_km: any user gets HA's chrome back.
  page = await openPage(browser, panel, 1280, 752);
  await go(page, `${home}?disable_km`);
  const dk = await page.evaluate(MEASURE);
  b.disableKm = { kioskStyles: dk.kioskStyles, headerVisible: dk.headerVisible, sidebarVisible: dk.sidebarVisible };
  if (dk.kioskStyles || !dk.headerVisible) fail(`?disable_km: kiosk applied ${JSON.stringify(b.disableKm)}`);
  await page.close();
}

await main();
