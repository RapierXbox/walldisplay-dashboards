// Shared helpers for the sandbox scripts: paths, docker, auth, REST and websocket.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(HERE, "..", "..");
export const OUT = path.join(HERE, "out");
export const IMAGE = process.env.HA_IMAGE || "ghcr.io/home-assistant/home-assistant:2026.10.0";
export const CONTAINER = process.env.HA_CONTAINER || "wdd-sandbox";
export const PORT = Number(process.env.HA_PORT || 18123);
export const BASE = `http://localhost:${PORT}`;
// Keep the config dir out of OneDrive: HA writes a lot of small files.
export const HACFG =
  process.env.HACFG || path.join(os.tmpdir(), "walldisplay-sandbox", "hacfg");

export const USERS = {
  admin: { username: "admin", password: "adminpass" },
  panel: { username: "panel", password: "panelpass" },
};

export const PROFILES = {
  shelly_wall_display: [480, 480],
  shelly_x2_landscape: [960, 480],
  shelly_x2_portrait: [480, 960],
  shelly_xl: [1280, 752],
  tablet_landscape: [1280, 800],
  tablet_portrait: [800, 1280],
};

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function docker(args, { check = true } = {}) {
  const r = spawnSync("docker", args, { encoding: "utf8", env: { ...process.env, MSYS_NO_PATHCONV: "1" } });
  if (check && r.status !== 0) throw new Error(`docker ${args.join(" ")} failed:\n${r.stderr}`);
  return r;
}

export async function waitRunning(timeoutMs = 240000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      // /api/config needs auth; /manifest.json answers once the frontend is up.
      const r = await fetch(`${BASE}/manifest.json`);
      if (r.ok) return;
    } catch {}
    await sleep(2000);
  }
  throw new Error("Home Assistant did not come up");
}

/** Log in through the auth flow; returns the token response. */
export async function login({ username, password }) {
  const clientId = `${BASE}/`;
  let r = await fetch(`${BASE}/auth/login_flow`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ client_id: clientId, handler: ["homeassistant", null], redirect_uri: `${BASE}/?auth_callback=1` }),
  });
  const flow = await r.json();
  r = await fetch(`${BASE}/auth/login_flow/${flow.flow_id}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password, client_id: clientId }),
  });
  const res = await r.json();
  if (res.type !== "create_entry") throw new Error(`login ${username} failed: ${JSON.stringify(res)}`);
  r = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    body: new URLSearchParams({ grant_type: "authorization_code", code: res.result, client_id: clientId }),
  });
  return r.json();
}

export async function rest(token, method, p, body) {
  const r = await fetch(`${BASE}${p}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) throw new Error(`${method} ${p} -> ${r.status}: ${text}`);
  return data;
}

/** Minimal websocket client: await ws.call({type, ...}) */
export async function connectWs(token) {
  const ws = new WebSocket(`${BASE.replace("http", "ws")}/api/websocket`);
  let id = 0;
  const pending = new Map();
  await new Promise((resolve, reject) => {
    ws.onerror = reject;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "auth_required") ws.send(JSON.stringify({ type: "auth", access_token: token }));
      else if (msg.type === "auth_ok") resolve();
      else if (msg.type === "auth_invalid") reject(new Error(msg.message));
      else if (msg.type === "result" && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        msg.success ? res(msg.result) : rej(Object.assign(new Error(msg.error?.message), { code: msg.error?.code }));
      }
    };
  });
  return {
    call(payload) {
      const msgId = ++id;
      ws.send(JSON.stringify({ ...payload, id: msgId }));
      return new Promise((res, rej) => pending.set(msgId, { res, rej }));
    },
    close: () => ws.close(),
  };
}

/** Puppeteer: log a page in by seeding localStorage.hassTokens. */
export async function seedTokens(page, tokens) {
  await page.goto(`${BASE}/auth/authorize`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.evaluate((t, base) => {
    localStorage.hassTokens = JSON.stringify({
      ...t, hassUrl: base, clientId: `${base}/`, expires: Date.now() + t.expires_in * 1000,
    });
  }, tokens, BASE);
}

/** Runs in the browser: collect elements matching a selector across all shadow roots. */
export const DEEP_QUERY_SRC = `
  window.__deepAll = (sel, root = document) => {
    const out = [];
    const walk = (node) => {
      if (node.querySelectorAll) node.querySelectorAll(sel).forEach((e) => out.push(e));
      const all = node.querySelectorAll ? node.querySelectorAll("*") : [];
      all.forEach((e) => { if (e.shadowRoot) walk(e.shadowRoot); });
    };
    walk(root);
    return [...new Set(out)];
  };
`;

/**
 * The frontend reloads the page once when its service worker takes control (first
 * visit with a fresh browser profile). Do that visit up front so measurements and
 * timers in later pages are not cut short. Service workers persist per browser.
 */
export async function warmUp(browser, tokens, url = "/") {
  const page = await browser.newPage();
  await seedTokens(page, tokens);
  let navs = 0;
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) navs++; });
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2" });
  const start = navs;
  const end = Date.now() + 15000;
  while (Date.now() < end && navs === start) await sleep(250);
  await sleep(1000);
  await page.close();
}
