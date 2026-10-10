// Layout spike: measure the real sections-view grid on HA 2026.10.
// Creates a plain storage dashboard /spike-grid and measures it at several
// viewports, with HA's own chrome ("plain") and with header + sidebar hidden
// the way walldisplay.js does it ("kiosk"). Output: out/spike.json + screenshots.
//
//   node spike.mjs
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";
import { BASE, DEEP_QUERY_SRC, OUT, USERS, connectWs, login, seedTokens, sleep, warmUp } from "./lib.mjs";

const URL_PATH = "spike-grid";
const VIEWPORTS = [[480, 480], [960, 480], [1280, 752]];

const tile = (entity, columns, rows) => ({ type: "tile", entity, grid_options: { columns, ...(rows ? { rows } : {}) } });
const footer = {
  card: {
    type: "grid", columns: 4, square: false,
    cards: ["Home", "Heat", "Media", "Scenes"].map((label, i) => ({
      type: "shortcut", label, icon: "mdi:home",
      tap_action: { action: "navigate", navigation_path: ["span2", "span3", "stacked", "rows5"][i] },
    })),
  },
};
const navFooter = (w) => ({
  max_width: w,
  card: { type: "custom:wall-display-nav", items: [
    { path: "home", label: "Home", icon: "mdi:home" }, { path: "climate", label: "Heat", icon: "mdi:thermostat", entity: "climate.kitchen" },
    { path: "media", label: "Media", icon: "mdi:speaker", entity: "media_player.kitchen_speaker" }, { path: "nav", label: "Scenes", icon: "mdi:palette" },
  ] },
});
const view = (pathName, sections, f = footer) => ({ type: "sections", path: pathName, title: pathName, max_columns: 3, top_margin: false, footer: f, sections });

const CONFIG = {
  title: "Spike",
  views: [
    view("span2", [{ type: "grid", column_span: 2, cards: [
      tile("light.kitchen_ceiling", 6), tile("light.kitchen_counter", 12),
      tile("light.kitchen_island", 18), tile("cover.kitchen_blind", 24),
    ] }]),
    view("span3", [{ type: "grid", column_span: 3, cards: [
      tile("light.kitchen_ceiling", 6), tile("light.kitchen_counter", 12),
      tile("light.kitchen_island", 18), tile("cover.kitchen_blind", 24), tile("switch.coffee_machine", 36),
    ] }]),
    view("stacked", [
      { type: "grid", column_span: 3, cards: [tile("light.kitchen_ceiling", 12)] },
      { type: "grid", column_span: 3, cards: [tile("light.kitchen_counter", 12)] },
    ]),
    view("rows5", [{ type: "grid", column_span: 3, cards: [
      { type: "vertical-stack", grid_options: { columns: 6, rows: 5 }, cards: [
        { type: "tile", entity: "light.kitchen_ceiling" }, { type: "tile", entity: "light.kitchen_counter" },
      ] },
      { type: "grid", columns: 1, square: false, grid_options: { columns: 6, rows: 5 }, cards: [
        { type: "tile", entity: "light.kitchen_island" }, { type: "tile", entity: "cover.kitchen_blind" },
      ] },
      tile("switch.coffee_machine", 6, 5),
    ] }]),
    // Pill nav footer (custom card from walldisplay.js); "Scenes" points here so it shows as active.
    view("nav", [{ type: "grid", column_span: 3, cards: [tile("light.kitchen_ceiling", 12)] }], navFooter(1280)),
  ],
};

// Same chrome removal as walldisplay.js (builtin kiosk).
const KIOSK_SRC = `
  (() => {
    const add = (root, id, css) => { if (!root || root.getElementById(id)) return; const s = document.createElement("style"); s.id = id; s.textContent = css; root.appendChild(s); };
    const ha = document.querySelector("home-assistant");
    const main = ha?.shadowRoot?.querySelector("home-assistant-main");
    const mainRoot = main?.shadowRoot;
    add(mainRoot, "k", ":host{--ha-sidebar-width:0px!important;--ha-top-app-bar-width:100%!important} ha-drawer>ha-sidebar{display:none!important}");
    add(mainRoot?.querySelector("ha-drawer")?.shadowRoot, "k", ".sidebar-shell,wa-drawer{display:none!important} .app-content{padding-inline-start:0!important}");
    const lovelace = mainRoot?.querySelector("partial-panel-resolver ha-panel-lovelace");
    const huiRoot = lovelace?.shadowRoot?.querySelector("hui-root");
    add(huiRoot?.shadowRoot, "k", ".header{display:none!important} #view{padding-top:calc(var(--safe-area-inset-top,0px) + var(--view-container-padding-top,0px))!important;min-height:100vh!important}");
  })();
`;

const MEASURE_SRC = `
  (() => {
    const r = (e) => { const b = e.getBoundingClientRect(); return { x: Math.round(b.x * 10) / 10, y: Math.round(b.y * 10) / 10, w: Math.round(b.width * 10) / 10, h: Math.round(b.height * 10) / 10 }; };
    const view = __deepAll("hui-sections-view")[0];
    const vr = view?.shadowRoot;
    const wrapper = vr?.querySelector(".wrapper");
    const wcs = wrapper && getComputedStyle(wrapper);
    const content = vr?.querySelector(".content");
    const sections = [...(vr?.querySelectorAll(".section") || [])].map((s) => {
      const hs = s.querySelector("hui-section");
      const grid = hs?.shadowRoot?.querySelector("hui-grid-section") || __deepAll("hui-grid-section", s)[0];
      const container = grid?.shadowRoot?.querySelector(".container");
      const cols = container ? getComputedStyle(container).gridTemplateColumns.split(" ").filter(Boolean) : [];
      const cards = [...(container?.querySelectorAll(".card") || [])].map((c) => {
        const hc = c.querySelector("hui-card");
        const inner = hc?.firstElementChild;
        return { type: hc?.config?.type, grid_options: hc?.config?.grid_options, rect: r(c), inner: inner ? r(inner) : null };
      });
      return { columnSpanVar: s.style.getPropertyValue("--column-span"), rect: r(s), gridColumns: cols.length, colWidth: cols[0], rowGap: container && getComputedStyle(container).rowGap, columnGap: container && getComputedStyle(container).columnGap, cards };
    });
    const footer = __deepAll("hui-view-footer")[0];
    const fcard = footer?.shadowRoot?.querySelector(".card");
    const header = __deepAll("hui-root")[0]?.shadowRoot?.querySelector(".header");
    return {
      inner: [innerWidth, innerHeight],
      scrollHeight: document.scrollingElement.scrollHeight,
      header: header ? r(header) : null,
      viewRect: view ? r(view) : null,
      wrapperPadding: wcs && [wcs.paddingLeft, wcs.paddingRight],
      columnCountVar: wcs && wcs.getPropertyValue("--column-count"),
      contentColumns: content ? getComputedStyle(content).gridTemplateColumns : null,
      sections,
      footer: footer ? r(footer) : null,
      footerCard: fcard ? r(fcard) : null,
    };
  })()
`;

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await login(USERS.admin);
  const ws = await connectWs(admin.access_token);
  const dashboards = await ws.call({ type: "lovelace/dashboards/list" });
  if (!dashboards.some((d) => d.url_path === URL_PATH)) {
    await ws.call({ type: "lovelace/dashboards/create", url_path: URL_PATH, title: "Spike", mode: "storage", show_in_sidebar: true, require_admin: false });
  }
  await ws.call({ type: "lovelace/config/save", url_path: URL_PATH, config: CONFIG });
  ws.close();

  const panel = await login(USERS.panel);
  const browser = await puppeteer.launch({ headless: true });
  await warmUp(browser, panel, `/${URL_PATH}/span2`);
  const results = [];
  try {
    for (const [w, h] of VIEWPORTS) {
      for (const mode of ["plain", "kiosk"]) {
        const page = await browser.newPage();
        await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
        await seedTokens(page, panel);
        for (const v of CONFIG.views) {
          await page.goto(`${BASE}/${URL_PATH}/${v.path}`, { waitUntil: "networkidle2" });
          await sleep(2500);
          await page.evaluate(DEEP_QUERY_SRC);
          if (mode === "kiosk") { await page.evaluate(KIOSK_SRC); await sleep(800); }
          const m = await page.evaluate(MEASURE_SRC);
          results.push({ viewport: `${w}x${h}`, mode, view: v.path, ...m });
          await page.screenshot({ path: path.join(OUT, `spike__${w}x${h}__${mode}__${v.path}.png`) });
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(OUT, "spike.json"), JSON.stringify(results, null, 1));
  for (const r of results) {
    const s = r.sections.map((s) => `span=${s.columnSpanVar} w=${s.rect.w} y=${s.rect.y} h=${s.rect.h} cols=${s.gridColumns} col=${s.colWidth} cards=[${s.cards.map((c) => `${c.grid_options?.columns ?? "-"}/${c.grid_options?.rows ?? "-"}:${c.rect.w}x${c.rect.h}@${c.rect.y}${c.inner ? ` inner ${c.inner.h}` : ""}`).join(" ")}]`).join(" | ");
    console.log(`${r.viewport} ${r.mode.padEnd(5)} ${r.view.padEnd(7)} scroll=${r.scrollHeight} view=${r.viewRect?.x},${r.viewRect?.w} hdr=${r.header?.h} footer=${r.footerCard?.y}+${r.footerCard?.h} :: ${s}`);
  }
}

await main();
