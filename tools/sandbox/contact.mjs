// Build out/contact.html: every out/<profile>__<view>.png embedded as a data URI,
// grouped by profile (variants like shelly_wall_display@de get their own group).
//
//   node contact.mjs
import fs from "node:fs";
import path from "node:path";
import { OUT, PROFILES } from "./lib.mjs";

const VIEW_ORDER = ["home", "climate", "media", "scenes", "more"];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const shots = fs.readdirSync(OUT)
  .filter((f) => /^[a-z0-9_]+(@[a-z]+)?__[a-z0-9_-]+\.png$/.test(f) && !f.startsWith("spike__") && !f.startsWith("admin__"))
  .map((f) => {
    const [group, view] = f.slice(0, -4).split("__");
    return { file: f, group, view, profile: group.split("@")[0], variant: group.split("@")[1] || "" };
  });

const profileOrder = Object.keys(PROFILES);
const groups = [...new Set(shots.map((s) => s.group))].sort((a, b) => {
  const [pa, va = ""] = a.split("@");
  const [pb, vb = ""] = b.split("@");
  return (profileOrder.indexOf(pa) - profileOrder.indexOf(pb)) || va.localeCompare(vb);
});
const viewRank = (v) => (VIEW_ORDER.includes(v) ? VIEW_ORDER.indexOf(v) : 99);

let report = {};
try { report = JSON.parse(fs.readFileSync(path.join(OUT, "report.json"), "utf8")); } catch {}
const failures = report.failures || [];

const sections = groups.map((g) => {
  const items = shots.filter((s) => s.group === g).sort((a, b) => viewRank(a.view) - viewRank(b.view) || a.view.localeCompare(b.view));
  const [profile, variant] = g.split("@");
  const [w, h] = PROFILES[profile] || [0, 0];
  const figs = items.map((s) => {
    const data = fs.readFileSync(path.join(OUT, s.file)).toString("base64");
    const bad = failures.filter((f) => f.startsWith(`${g}/${s.view}:`));
    return `<figure class="shot" style="--w:${w}">
  <img src="data:image/png;base64,${data}" alt="${esc(`${g} ${s.view}`)}" width="${w}" height="${h}" loading="lazy">
  <figcaption><span class="view">${esc(s.view)}</span>${bad.length ? `<span class="bad" title="${esc(bad.join("\n"))}">${bad.length} issue${bad.length > 1 ? "s" : ""}</span>` : ""}</figcaption>
</figure>`;
  }).join("\n");
  return `<section class="group">
  <h2>${esc(profile)}${variant ? ` <span class="variant">@${esc(variant)}</span>` : ""} <span class="size">${w}×${h}</span></h2>
  <div class="grid">${figs}</div>
</section>`;
}).join("\n");

const html = `<title>Wall Display Screenshots</title>
<style>
:root {
  color-scheme: light;
  --bg: #f4f4f2; --fg: #1d1d1f; --muted: #66666b; --line: #d8d8db; --surface: #ffffff;
  --bad: #b3261e; --bad-bg: #fdecea; --ok: #1e7a3c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #161618; --fg: #e6e6e8; --muted: #9a9aa0; --line: #34343a; --surface: #202024;
    --bad: #ff8a80; --bad-bg: #3a1a18; --ok: #7bd88f;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #161618; --fg: #e6e6e8; --muted: #9a9aa0; --line: #34343a; --surface: #202024;
  --bad: #ff8a80; --bad-bg: #3a1a18; --ok: #7bd88f;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; overflow-x: hidden; }
header { padding: 16px; border-bottom: 1px solid var(--line); }
h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
.meta { margin: 0; color: var(--muted); font-size: 13px; }
.meta .ok { color: var(--ok); }
.meta .bad { color: var(--bad); }
main { padding: 0 16px 32px; }
.group { margin-top: 24px; }
h2 { font-size: 15px; font-weight: 600; margin: 0 0 12px; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.variant { color: var(--muted); font-weight: 500; }
.size { color: var(--muted); font-weight: 400; font-size: 13px; }
.grid { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.shot { margin: 0; width: min(calc(var(--w) * 1px), 100%); max-width: 100%; }
.shot img { display: block; width: 100%; height: auto; border-radius: 10px; border: 1px solid var(--line); background: #111; }
figcaption { display: flex; gap: 8px; align-items: center; padding-top: 6px; font-size: 13px; color: var(--muted); }
.view { color: var(--fg); font-weight: 500; }
figcaption .bad { color: var(--bad); background: var(--bad-bg); border-radius: 999px; padding: 0 8px; font-size: 12px; }
</style>
<header>
  <h1>Wall Display Screenshots</h1>
  <p class="meta">Home Assistant 2026.10.0 sandbox, panel user, kiosk on, captured ${esc(report.generated || "")}. Shown at the display's CSS size (captured at DPR 2).
  ${failures.length ? `<span class="bad">${failures.length} failed check(s).</span>` : `<span class="ok">All checks passed.</span>`}</p>
</header>
<main>
${sections}
</main>
`;
fs.writeFileSync(path.join(OUT, "contact.html"), html);
console.log(`[contact] ${shots.length} screenshots in ${groups.length} groups -> out/contact.html (${(html.length / 1048576).toFixed(1)} MB)`);
