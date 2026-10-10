// Performance traces of the wall dashboards under CPU throttling (see PERF.md).
//
//   node perf.mjs [--rate 6] [--idle 60] [--only <case>] [--tag before]
//
// Cases (all as the panel user):
//   wall480      /wall-kitchen at 480x480
//   wall960      the shelly_x2_landscape test display at 960x480
//   km480        /wall-kitchen?disable_km (kiosk, layout and auto dark skipped)
//   plain480     a plain HA sections dashboard with the same cards (no pill), walldisplay.js loaded
//   bare480      the same plain dashboard with walldisplay.js switched off (HA alone)
// Scenarios per case: load (first load, 20 s), switch (pill to Climate and back), tap (3 light
// toggles), idle (N s on Home while fake states change and unrelated registry entries are
// renamed). Each scenario is traced (devtools.timeline + V8 CPU samples); samples are
// attributed by script URL (walldisplay.js vs the HA frontend).
//
// Writes out/perf/<tag>.json (+ one .trace.json per scenario, open them in DevTools) and
// prints a summary table. `--analyse <trace.json>` re-reads a saved trace.
// The sandbox is shared: a container restart during a run invalidates it (the script logs
// the container's start time at the beginning and the end).
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";
import { BASE, CONTAINER, OUT, USERS, connectWs, docker, login, rest, seedTokens, sleep, warmUp } from "./lib.mjs";

const args = process.argv.slice(2);
const opt = (name, dflt) => (args.includes(name) ? args[args.indexOf(name) + 1] : dflt);
const RATE = Number(opt("--rate", 6));
const IDLE = Number(opt("--idle", 60));
const ONLY = opt("--only", null)?.split(",");
const TAG = opt("--tag", `rate${RATE}`);
const SCEN = opt("--scenarios", "load,switch,tap,idle").split(",");
const DIR = path.join(OUT, "perf");
fs.mkdirSync(DIR, { recursive: true });
const log = (...a) => console.log("[perf]", ...a);

const CATEGORIES = [
  "devtools.timeline", "disabled-by-default-devtools.timeline", "disabled-by-default-devtools.timeline.stack",
  "v8.execute", "disabled-by-default-v8.cpu_profiler", "toplevel", "blink.user_timing",
];

// Cheap fixed-path lookups (no deep walks: they would cost more than what we measure).
const PROBE = `
  window.__view = () => {
    const main = document.querySelector("home-assistant")?.shadowRoot?.querySelector("home-assistant-main");
    const panel = main?.shadowRoot?.querySelector("partial-panel-resolver")?.querySelector("ha-panel-lovelace");
    const root = panel?.shadowRoot?.querySelector("hui-root")?.shadowRoot;
    return root?.querySelector("#view hui-sections-view") || null;
  };
  window.__cards = (tag) => {
    const v = window.__view();
    if (!v?.shadowRoot) return [];
    return [...v.shadowRoot.querySelectorAll("hui-section")].flatMap((s) =>
      [...(s.querySelector("hui-grid-section")?.shadowRoot?.querySelectorAll("hui-card") || [])])
      .map((hc) => hc.firstElementChild).filter((c) => c && (!tag || c.localName === tag));
  };
  window.__navButton = (p) => {
    const v = window.__view();
    const nav = v?.shadowRoot?.querySelector("hui-view-footer")?.shadowRoot?.querySelector("hui-card")?.firstElementChild
      || v?.shadowRoot?.querySelector("hui-view-footer wall-display-nav");
    return nav?.shadowRoot?.querySelector('button[data-path="' + p + '"]') || null;
  };
  window.__firstTiles = null;
  (function watch() {
    const t = setInterval(() => {
      const tile = window.__cards && window.__cards("hui-tile-card")[0];
      if (tile && tile.getBoundingClientRect().height > 0) { window.__firstTiles = performance.now(); clearInterval(t); }
    }, 100);
  })();
`;

// ---------- trace analysis ----------
function analyse(trace, wdName = "walldisplay") {
  const ev = trace.traceEvents;
  const threads = new Map();
  for (const e of ev) if (e.ph === "M" && e.name === "thread_name" && e.args?.name === "CrRendererMain") threads.set(`${e.pid}:${e.tid}`, 0);
  for (const e of ev) {
    const k = `${e.pid}:${e.tid}`;
    if (e.name === "RunTask" && e.ph === "X" && threads.has(k)) threads.set(k, threads.get(k) + (e.dur || 0));
  }
  const main = [...threads.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const [pid, tid] = (main || "0:0").split(":").map(Number);
  const onMain = ev.filter((e) => e.pid === pid && e.tid === tid);
  // Starting the sampling profiler interrupts whatever runs at that moment for a few hundred
  // ms (V8.InvokeApiInterruptCallbacks): tracing overhead, not page work. Cut it out.
  const interrupts = onMain.filter((e) => e.name === "V8.InvokeApiInterruptCallbacks" && e.ph === "X");
  const tasks = onMain.filter((e) => e.name === "RunTask" && e.ph === "X").map((e) => {
    const cut = interrupts.filter((i) => i.ts >= e.ts && i.ts < e.ts + e.dur).reduce((s, i) => s + i.dur, 0);
    return cut ? { ...e, dur: e.dur - cut } : e;
  });
  const ts = tasks.map((e) => e.ts);
  const t0 = Math.min(...ts), t1 = Math.max(...tasks.map((e) => e.ts + e.dur));
  const long = tasks.filter((e) => e.dur > 50000);
  const fromWd = (e) => {
    const st = e.args?.beginData?.stackTrace || e.args?.data?.stackTrace;
    return Array.isArray(st) && st.some((f) => (f.url || "").includes(wdName));
  };
  const count = (name) => {
    const l = onMain.filter((e) => e.name === name && e.ph === "X");
    return { n: l.length, ms: +(l.reduce((s, e) => s + e.dur, 0) / 1000).toFixed(1), wd: l.filter(fromWd).length };
  };

  // V8 samples (Profile/ProfileChunk on the main thread).
  const nodes = new Map();
  const cats = { wd: 0, wdIncl: 0, ha: 0, harness: 0, other: 0, gc: 0, program: 0, idle: 0 };
  const wdFns = {};
  const samples = [];
  // One profile per thread (workers have their own): only the main thread's, by profile id.
  const ids = new Set(ev.filter((e) => e.name === "Profile" && e.pid === pid && e.tid === tid).map((e) => e.id));
  const clock = {};
  for (const e of ev) {
    if (e.pid !== pid || !ids.has(e.id)) continue;
    if (e.name === "Profile" && e.args?.data?.startTime != null) clock[e.id] = e.args.data.startTime;
    if (e.name !== "ProfileChunk") continue;
    const cp = e.args?.data?.cpuProfile || {};
    for (const n of cp.nodes || []) nodes.set(`${e.id}:${n.id}`, { ...n, parent: n.parent == null ? null : `${e.id}:${n.parent}` });
    const deltas = e.args?.data?.timeDeltas || [];
    (cp.samples || []).forEach((id, i) => { clock[e.id] = (clock[e.id] || 0) + (deltas[i] || 0); samples.push([clock[e.id], `${e.id}:${id}`]); });
  }
  samples.sort((a, b) => a[0] - b[0]);
  const classify = (url) => {
    if (!url) return null;
    if (url.includes(wdName)) return "wd";
    if (url.includes("__puppeteer") || url.startsWith("pptr:")) return "harness";
    if (url.startsWith(BASE) || url.includes("/frontend_")) return "ha";
    return "other";
  };
  for (let i = 0; i < samples.length - 1; i++) {
    const [t, id] = samples[i];
    const w = Math.min(samples[i + 1][0] - t, 5000); // gaps (profiler pauses) capped
    let n = nodes.get(id);
    const top = n?.callFrame?.functionName;
    if (top === "(idle)") { cats.idle += w; continue; }
    if (top === "(garbage collector)") { cats.gc += w; continue; }
    if (top === "(program)" || top === "(root)") { cats.program += w; continue; }
    let cls = null, wdFn = null, anyWd = false;
    for (let m = n; m; m = nodes.get(m.parent)) {
      const c = classify(m.callFrame?.url);
      if (!cls && c) { cls = c; if (c === "wd") wdFn = m.callFrame.functionName || "(anon)"; }
      if (c === "wd") { anyWd = true; if (!wdFn) wdFn = m.callFrame.functionName || "(anon)"; }
    }
    cats[cls || "other"] += w;
    if (anyWd) cats.wdIncl += w;
    if (cls === "wd") wdFns[wdFn] = (wdFns[wdFn] || 0) + w;
  }
  const ms = (us) => +(us / 1000).toFixed(1);
  return {
    windowMs: ms(t1 - t0),
    busyMs: ms(tasks.reduce((s, e) => s + e.dur, 0)),
    tasks: tasks.length,
    long: { n: long.length, maxMs: ms(Math.max(0, ...long.map((e) => e.dur))), tbtMs: ms(long.reduce((s, e) => s + e.dur - 50000, 0)) },
    recalc: count("UpdateLayoutTree"),
    layout: count("Layout"),
    paint: count("Paint").n,
    timers: onMain.filter((e) => e.name === "TimerFire").length,
    js: Object.fromEntries(Object.entries(cats).map(([k, v]) => [k, ms(v)])),
    wdFns: Object.fromEntries(Object.entries(wdFns).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => [k, ms(v)])),
  };
}

// ---------- helpers ----------
async function traced(page, name, fn) {
  const file = path.join(DIR, `${TAG}__${name}.trace.json`);
  await page.tracing.start({ path: file, categories: CATEGORIES });
  const extra = await fn();
  const buf = await page.tracing.stop();
  const res = analyse(JSON.parse(Buffer.from(buf).toString("utf8")));
  return { ...res, ...extra };
}

function wsCounter(client) {
  const c = { generate: 0, list: 0, lovelace_updated: 0, sent: 0 };
  const each = (raw, f) => { try { const m = JSON.parse(raw); (Array.isArray(m) ? m : [m]).forEach(f); } catch {} };
  client.on("Network.webSocketFrameSent", ({ response }) => each(response.payloadData, (m) => {
    c.sent++;
    if (m.type === "walldisplay_dashboards/generate") c.generate++;
    if (m.type === "walldisplay_dashboards/list") c.list++;
  }));
  client.on("Network.webSocketFrameReceived", ({ response }) => each(response.payloadData, (m) => {
    if (m.type === "event" && m.event?.event_type === "lovelace_updated") c.lovelace_updated++;
  }));
  return { snap: () => ({ ...c }), diff: (a) => Object.fromEntries(Object.keys(c).map((k) => [k, c[k] - a[k]])) };
}

async function openPage(browser, tokens, w, h, block) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument(PROBE);
  // The service worker serves walldisplay.js, so request interception can't block it; its
  // own load guard turns it off instead (nothing defined, nothing running).
  if (block) await page.evaluateOnNewDocument(() => { window.__walldisplayLoaded = true; });
  await seedTokens(page, tokens);
  const client = await page.target().createCDPSession();
  await client.send("Network.enable");
  await client.send("Emulation.setCPUThrottlingRate", { rate: RATE });
  return { page, client, ws: wsCounter(client) };
}

async function waitFor(page, fn, arg, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await page.evaluate(fn, arg).catch(() => false)) return true;
    await sleep(250);
  }
  return false;
}

async function clickEl(page, handleFn, arg) {
  const box = await page.evaluate((src, a) => {
    const el = eval(src)(a);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }, handleFn.toString(), arg);
  if (!box) throw new Error(`nothing to click for ${arg}`);
  await page.mouse.click(box.x, box.y);
}

// ---------- background activity: state changes + unrelated registry updates ----------
function startNoise(adminToken, ws, counts) {
  let n = 0;
  const timers = [
    setInterval(() => {
      n++;
      rest(adminToken, "POST", "/api/states/sensor.kitchen_temperature", {
        state: (20 + (n % 10) / 10).toFixed(1),
        attributes: { device_class: "temperature", unit_of_measurement: "°C", friendly_name: "Kitchen temperature", state_class: "measurement" },
      }).catch(() => {});
    }, 5000),
    setInterval(() => rest(adminToken, "POST", "/api/services/light/toggle", { entity_id: "light.bedroom_ceiling" }).catch(() => {}), 7000),
    setInterval(() => {
      counts.registry++;
      const which = counts.registry % 2 ? "climate.bedroom" : "cover.bedroom_blind";
      ws.call({ type: "config/entity_registry/update", entity_id: which, name: `${which.split(".")[1]} ${counts.registry}` }).catch(() => {});
    }, 15000),
  ];
  return () => timers.forEach(clearInterval);
}

// ---------- scenarios ----------
async function runCase(browser, panel, admin, adminWs, c) {
  const out = { case: c.name, rate: RATE, size: `${c.w}x${c.h}` };
  const { page, client, ws } = await openPage(browser, panel, c.w, c.h, c.block);
  const url = `${BASE}${c.url}`;
  try {
    if (SCEN.includes("load")) {
      let s = ws.snap();
      out.load = await traced(page, `${c.name}__load`, async () => {
        const t = Date.now();
        await page.goto(url, { waitUntil: "domcontentloaded" });
        await waitFor(page, () => window.__firstTiles != null, null, 60000);
        const firstTiles = await page.evaluate(() => window.__firstTiles);
        const rest = 20000 - (Date.now() - t);
        if (rest > 0) await sleep(rest);
        return { firstTilesMs: Math.round(firstTiles || -1) };
      });
      out.load.ws = ws.diff(s);
    } else {
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await waitFor(page, () => window.__firstTiles != null, null, 60000);
      await sleep(8000);
    }
    if (SCEN.includes("switch") && c.pill) {
      await sleep(3000);
      out.switch = await traced(page, `${c.name}__switch`, async () => {
        const lat = [];
        for (const target of ["climate", "home", "climate", "home"]) {
          const card = target === "climate" ? "hui-thermostat-card" : "hui-tile-card";
          await clickEl(page, (p) => window.__navButton(p), target);
          const t = Date.now();
          await waitFor(page, (tag) => { const c = window.__cards(tag)[0]; return !!c && c.getBoundingClientRect().height > 0; }, card, 20000);
          lat.push(Date.now() - t);
          await sleep(2500);
        }
        return { latencyMs: lat };
      });
    }
    if (SCEN.includes("tap")) {
      await sleep(3000);
      const ent = c.tap || "light.kitchen_ceiling";
      out.tap = await traced(page, `${c.name}__tap`, async () => {
        const lat = [];
        for (let i = 0; i < 3; i++) {
          const before = await page.evaluate((e) => document.querySelector("home-assistant").hass.states[e].state, ent);
          await clickEl(page, (e) => window.__cards("hui-tile-card").find((t) => t.parentElement?.config?.entity === e), ent);
          const t = Date.now();
          await waitFor(page, ([e, b]) => document.querySelector("home-assistant").hass.states[e].state !== b, [ent, before], 10000);
          lat.push(Date.now() - t);
          await sleep(2500);
        }
        return { latencyMs: lat };
      });
    }
    if (SCEN.includes("idle")) {
      await sleep(3000);
      const counts = { registry: 0 };
      let s = ws.snap();
      const stop = startNoise(admin.access_token, adminWs, counts);
      out.idle = await traced(page, `${c.name}__idle`, async () => { await sleep(IDLE * 1000); return {}; });
      stop();
      out.idle.ws = ws.diff(s);
      out.idle.registryUpdates = counts.registry;
      out.idle.wdPerSecMs = +(out.idle.js.wd / IDLE).toFixed(2);
    }
  } finally {
    await page.close();
  }
  return out;
}

async function plainDashboard(admin, kitchenEntry) {
  const ws = await connectWs(admin.access_token);
  const dash = await ws.call({ type: "walldisplay_dashboards/generate", entry_id: kitchenEntry });
  dash.views.forEach((v) => delete v.footer);
  const list = await ws.call({ type: "lovelace/dashboards/list" });
  if (!list.some((d) => d.url_path === "perf-plain")) {
    await ws.call({ type: "lovelace/dashboards/create", url_path: "perf-plain", title: "Perf plain", mode: "storage", require_admin: false, show_in_sidebar: false });
  }
  await ws.call({ type: "lovelace/config/save", url_path: "perf-plain", config: dash });
  ws.close();
}

async function main() {
  const admin = await login(USERS.admin);
  const panel = await login(USERS.panel);
  const pws = await connectWs(panel.access_token);
  const displays = (await pws.call({ type: "walldisplay_dashboards/list" })).displays;
  pws.close();
  const entries = await rest(admin.access_token, "GET", "/api/config/config_entries/entry?domain=walldisplay_dashboards");
  const byTitle = (t) => entries.find((e) => e.title === t)?.entry_id;
  const urlOf = (id) => displays.find((d) => d.entry_id === id)?.url_path;
  const kitchen = urlOf(byTitle("Kitchen"));
  const x2 = urlOf(byTitle("Test shelly_x2_landscape"));
  await plainDashboard(admin, byTitle("Kitchen"));

  // Server side: round trip of generate (one display) and list (all displays).
  const tws = await connectWs(panel.access_token);
  const timeIt = async (payload, n) => {
    const t = [];
    for (let i = 0; i < n; i++) { const s = performance.now(); await tws.call(payload); t.push(performance.now() - s); }
    t.sort((a, b) => a - b);
    return { medianMs: +t[Math.floor(n / 2)].toFixed(1), maxMs: +t[n - 1].toFixed(1) };
  };
  const backend = {
    displays: displays.length,
    generate: await timeIt({ type: "walldisplay_dashboards/generate", entry_id: byTitle("Kitchen") }, 20),
    list: await timeIt({ type: "walldisplay_dashboards/list" }, 20),
  };
  tws.close();
  log("backend", JSON.stringify(backend));
  const startedAt = () => docker(["inspect", CONTAINER, "--format", "{{.State.StartedAt}}"], { check: false }).stdout.trim();
  const containerStart = startedAt();
  log("container started", containerStart);

  // Backend view: every lovelace_updated fired while this run lasts.
  const adminWs = await connectWs(admin.access_token);
  const fired = {};
  const evWs = new WebSocket(`${BASE.replace("http", "ws")}/api/websocket`);
  await new Promise((res) => {
    evWs.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.type === "auth_required") evWs.send(JSON.stringify({ type: "auth", access_token: admin.access_token }));
      else if (msg.type === "auth_ok") { evWs.send(JSON.stringify({ id: 1, type: "subscribe_events", event_type: "lovelace_updated" })); res(); }
      else if (msg.type === "event") { const u = msg.event.data.url_path; fired[u] = (fired[u] || 0) + 1; }
    };
  });

  const cases = [
    { name: "wall480", url: `/${kitchen}/home`, w: 480, h: 480, pill: true },
    { name: "wall960", url: `/${x2}/home`, w: 960, h: 480, pill: true, tap: "light.living_room_ceiling" },
    { name: "km480", url: `/${kitchen}/home?disable_km`, w: 480, h: 480, pill: true },
    { name: "plain480", url: "/perf-plain/home", w: 480, h: 480 },
    { name: "bare480", url: "/perf-plain/home", w: 480, h: 480, block: true },
  ].filter((c) => !ONLY || ONLY.includes(c.name));

  const browser = await puppeteer.launch({ headless: true, args: ["--lang=en-US"] });
  const results = [];
  const t0 = Date.now();
  try {
    await warmUp(browser, panel, `/${kitchen}/home`);
    for (const c of cases) {
      log(`case ${c.name} @${RATE}x`);
      results.push(await runCase(browser, panel, admin, adminWs, c));
      fs.writeFileSync(path.join(DIR, `${TAG}.json`), JSON.stringify({ results }, null, 1));
    }
  } finally {
    await browser.close();
    adminWs.close();
    evWs.close();
  }
  const minutes = (Date.now() - t0) / 60000;
  if (startedAt() !== containerStart) log("WARNING: the container restarted during the run, results are mixed");
  const summary = { tag: TAG, backend, rate: RATE, idleSeconds: IDLE, minutes: +minutes.toFixed(1), lovelaceUpdatedFired: fired, results };
  fs.writeFileSync(path.join(DIR, `${TAG}.json`), JSON.stringify(summary, null, 1));

  const row = (c, sc, r) => r && console.log([c, sc, r.windowMs, r.busyMs, r.long.n, r.long.maxMs, r.long.tbtMs, r.js.wd, r.js.wdIncl, r.js.ha,
    `${r.recalc.n}/${r.recalc.wd}`, `${r.layout.n}/${r.layout.wd}`, r.timers, r.ws ? `${r.ws.generate}/${r.ws.list}/${r.ws.lovelace_updated}` : "",
    r.firstTilesMs ?? (r.latencyMs ? r.latencyMs.join(",") : "")].join("\t"));
  console.log(["case", "scen", "winMs", "busyMs", "long", "maxLong", "TBT", "wdJs", "wdIncl", "haJs", "recalc/wd", "layout/wd", "timers", "gen/list/llu", "firstTiles|latency"].join("\t"));
  for (const r of results) for (const sc of ["load", "switch", "tap", "idle"]) row(r.case, sc, r[sc]);
  console.log("lovelace_updated fired (backend):", JSON.stringify(fired), `over ${minutes.toFixed(1)} min`);
}

if (args.includes("--analyse")) {
  // Re-analyse a saved trace: node perf.mjs --analyse out/perf/<file>.trace.json
  console.log(JSON.stringify(analyse(JSON.parse(fs.readFileSync(opt("--analyse"), "utf8"))), null, 1));
} else {
  main().catch((e) => { console.error(e); process.exit(1); });
}
