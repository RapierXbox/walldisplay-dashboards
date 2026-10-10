// Build and start the Home Assistant sandbox, then seed users, areas, states and
// (if present) a walldisplay_dashboards config entry.
//
//   node setup.mjs [--fresh] [--extra-js] [--no-integration] [--seed-only] [--idle 10]
//
// --fresh           wipe the config dir first
// --extra-js        also load frontend/walldisplay.js via frontend.extra_module_url
//                   (only needed while the backend does not register it itself)
// --no-integration  skip the config flow
// --seed-only       do not touch the container, only seed the running instance
// --idle N          idle_seconds option for the created display (default 10)
import fs from "node:fs";
import path from "node:path";
import {
  BASE, CONTAINER, HACFG, HERE, IMAGE, PORT, PROFILES, REPO, USERS,
  connectWs, docker, login, rest, sleep, waitRunning,
} from "./lib.mjs";

const args = process.argv.slice(2);
const flag = (f) => args.includes(f);
const opt = (f, d) => (args.includes(f) ? args[args.indexOf(f) + 1] : d);
const log = (...a) => console.log("[setup]", ...a);

const COMPONENT = path.join(REPO, "custom_components", "walldisplay_dashboards");
const AREAS = ["Kitchen", "Living room", "Bedroom", "Bathroom", "Hallway", "Busy kitchen"];
const PERSONS = ["Alex", "Sam"];

function writeConfig() {
  if (flag("--fresh")) {
    docker(["rm", "-f", CONTAINER], { check: false });
    fs.rmSync(HACFG, { recursive: true, force: true });
  }
  fs.mkdirSync(path.join(HACFG, ".storage"), { recursive: true });
  fs.mkdirSync(path.join(HACFG, "custom_components"), { recursive: true });
  const extra = flag("--extra-js")
    ? "  extra_module_url:\n    - /local/walldisplay/walldisplay.js\n"
    : "";
  fs.writeFileSync(path.join(HACFG, "configuration.yaml"), `homeassistant:
  name: Sandbox
  latitude: 52.52
  longitude: 13.40
  elevation: 34
  unit_system: metric
  time_zone: Europe/Berlin
  currency: EUR
  country: DE
default_config:
frontend:
${extra}fake_devices:
logger:
  default: warning
  logs:
    custom_components.walldisplay_dashboards: debug
    custom_components.fake_devices: debug
`);
  fs.copyFileSync(path.join(HERE, "fake_devices.json"), path.join(HACFG, "fake_devices.json"));
  const onboarding = path.join(HACFG, ".storage", "onboarding");
  fs.writeFileSync(onboarding, JSON.stringify({
    version: 4, minor_version: 1, key: "onboarding",
    data: { done: ["user", "core_config", "analytics", "integration"] },
  }));
}

function createUsers() {
  const base = ["run", "--rm", "--entrypoint", "python", "-v", `${HACFG}:/config`, IMAGE,
    "-m", "homeassistant", "--script", "auth", "-c", "/config"];
  const existing = docker([...base, "list"], { check: false }).stdout || "";
  for (const u of Object.values(USERS)) {
    if (existing.split(/\r?\n/).some((l) => l.trim() === u.username)) continue;
    log("adding user", u.username);
    docker([...base, "add", u.username, u.password]);
  }
}

function startContainer() {
  docker(["rm", "-f", CONTAINER], { check: false });
  const mounts = [
    "-v", `${HACFG}:/config`,
    "-v", `${path.join(HERE, "fake_devices")}:/config/custom_components/fake_devices:ro`,
    "-v", `${path.join(COMPONENT, "frontend")}:/config/www/walldisplay:ro`,
  ];
  if (fs.existsSync(path.join(COMPONENT, "manifest.json"))) {
    mounts.push("-v", `${COMPONENT}:/config/custom_components/walldisplay_dashboards:ro`);
  } else {
    log("custom_components/walldisplay_dashboards has no manifest.json yet; not mounting it");
  }
  docker(["run", "-d", "--name", CONTAINER, "-p", `${PORT}:8123`, "-e", "TZ=Europe/Berlin", ...mounts, IMAGE]);
  log("container started:", CONTAINER, BASE);
}

async function seedHa() {
  const admin = await login(USERS.admin);
  await login(USERS.panel); // first login creates the user (as admin)
  const ws = await connectWs(admin.access_token);

  const users = await ws.call({ type: "config/auth/list" });
  const panel = users.find((u) => u.username === USERS.panel.username);
  if (panel && !panel.group_ids.includes("system-users")) {
    await ws.call({ type: "config/auth/update", user_id: panel.id, group_ids: ["system-users"] });
    log("panel user moved to system-users");
  }

  const areas = await ws.call({ type: "config/area_registry/list" });
  for (const name of AREAS) {
    if (!areas.some((a) => a.name === name)) {
      await ws.call({ type: "config/area_registry/create", name });
      log("area created:", name);
    }
  }

  const persons = await ws.call({ type: "person/list" }).catch(() => ({ storage: [] }));
  for (const name of PERSONS) {
    if (!(persons.storage || []).some((p) => p.name === name)) {
      await ws.call({ type: "person/create", name });
      log("person created:", name);
    }
  }

  // Optional fixture states. These have no registry entry, so no area.
  const fixture = path.join(REPO, "tests", "fixtures", "expected", "states.json");
  if (fs.existsSync(fixture)) {
    const raw = JSON.parse(fs.readFileSync(fixture, "utf8"));
    // Accepts a list of states, {states: [...]}, or {entity_id: {state, attributes}}.
    const states = Array.isArray(raw) ? raw : raw.states
      || Object.entries(raw).map(([entity_id, v]) => ({ entity_id, ...v }));
    const have = new Set((await rest(admin.access_token, "GET", "/api/states")).map((s) => s.entity_id));
    let n = 0;
    for (const s of states) {
      if (have.has(s.entity_id)) continue;
      await rest(admin.access_token, "POST", `/api/states/${s.entity_id}`, { state: String(s.state), attributes: s.attributes || {} });
      n++;
    }
    log(`posted ${n} fixture states (no areas: POSTed states have no registry entry)`);
  }

  if (!flag("--no-integration") && fs.existsSync(path.join(COMPONENT, "manifest.json"))) {
    await addIntegration(admin.access_token, ws);
  }
  ws.close();
}

// Walk a data-entry flow, answering each form from `answers[step_id]` plus schema defaults.
async function walkFlow(token, base, startBody, answers) {
  let step = await rest(token, "POST", base, startBody);
  for (let i = 0; i < 10 && step.type === "form"; i++) {
    const data = {};
    for (const field of step.data_schema || []) {
      if (field.default !== undefined) data[field.name] = field.default;
      else if (field.description?.suggested_value !== undefined) data[field.name] = field.description.suggested_value;
    }
    Object.assign(data, answers[step.step_id] || {});
    log(`flow step ${step.step_id}:`, JSON.stringify(data));
    step = await rest(token, "POST", `${base}/${step.flow_id}`, data);
    if (step.errors && Object.keys(step.errors).length) throw new Error(`flow errors: ${JSON.stringify(step.errors)}`);
  }
  return step;
}

// One display per profile: "Kitchen" (480x480, short idle for the idle test), "Entrance"
// (Hallway, role entrance) plus
// "Test <profile>" for every other profile in lib.mjs, all built from the same flow.
async function addIntegration(token, ws) {
  const entries = await rest(token, "GET", "/api/config/config_entries/entry?domain=walldisplay_dashboards");
  const titles = new Set(entries.map((e) => e.title));
  const areas = await ws.call({ type: "config/area_registry/list" });
  const areaId = (name) => areas.find((a) => a.name === name)?.area_id;
  const wanted = [
    { name: "Kitchen", area_id: areaId("Kitchen"), profile: "shelly_wall_display", options: { idle_seconds: Number(opt("--idle", 10)) } },
    { name: "Entrance", area_id: areaId("Hallway"), profile: "shelly_wall_display", options: { role: "entrance" } },
    // Variants: a crowded room, and a weather entity without forecast support.
    { name: "Busy", area_id: areaId("Busy kitchen"), profile: "shelly_wall_display" },
    { name: "No forecast", area_id: areaId("Living room"), profile: "shelly_xl", weather: "weather.basic" },
    ...Object.keys(PROFILES).filter((p) => p !== "shelly_wall_display")
      .map((p) => ({ name: `Test ${p}`, area_id: areaId("Living room"), profile: p })),
  ];
  for (const d of wanted) {
    if (titles.has(d.name)) continue;
    const res = await walkFlow(token, "/api/config/config_entries/flow",
      { handler: "walldisplay_dashboards", show_advanced_options: false },
      { user: { name: d.name, area_id: d.area_id, profile: d.profile, weather_entity: d.weather || "weather.home" } });
    log(`config flow ${d.name}:`, res.type, res.reason || "");
    if (res.type !== "create_entry" || !d.options) continue;
    try {
      const o = await walkFlow(token, "/api/config/config_entries/options/flow", { handler: res.result.entry_id },
        { init: d.options });
      log("options flow:", o.type);
    } catch (err) {
      log("options flow failed (idle_seconds stays default):", err.message.split(/\r?\n/)[0]);
    }
  }
}

if (!flag("--seed-only")) {
  writeConfig();
  createUsers();
  startContainer();
}
log("waiting for Home Assistant ...");
await waitRunning();
await sleep(3000);
await seedHa();
log("done. Admin: admin/adminpass, panel: panel/panelpass at", BASE);
