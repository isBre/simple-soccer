// The Lab area of the web app (web/app.py): dashboard of the experiment pipeline (API: lab/dashboard.py). Polls the JSON API every 10 s.
// It also owns the router (web/lab/app.js): #/game/... routes go to the Game area (web/game.js).
// Routes: #/ now · #/live · #/runs · #/run/<name>[/<tab>] · #/compare?runs=a,b&kind=full · #/ranking · #/dataset[/<match>] · #/machine
// Charts are plain SVG (no libraries, no internet). Run colours are hashed from the run name, so they never change.
// This file: helpers and the SVG charts used by every page. The Lab is split into web/lab/*.js, plain scripts loaded in order by index.html
// (they share one global scope).
"use strict";

const POLL_MS = 10000;
const PALETTE = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6", "--c7", "--c8", "--c9", "--c10"];
const TERM_LABEL = {
  goals: "goals", time: "time", pass_prog: "progressive pass", pass_fail: "failed pass", pass_team: "pass (team)", coop: "cooperation",
  open: "open for pass", space: "spacing", kick: "kick discipline", xg: "xG for", xga: "xG against", result: "win / draw", tackle: "tackles",
  goalside: "goal-side", opp_half: "opp. in our half", wall: "at the wall", compact: "compactness", far: "far from ball", keeper: "keeper", jitter: "twitching", shaping: "shaping",
};
const BEHAVIOUR = [
  ["dir_changes_s", "Direction changes / s", "lower", 1], ["idle_pct", "Idle %", "lower", 0], ["spacing_px", "Teammate spacing px", "", 0],
  ["keeper_dist_px", "Slot-0 distance from goal px", "", 0], ["passes_match", "Passes / match", "higher", 1], ["key_passes_match", "Key passes / match", "higher", 2],
  ["shots_match", "Shots / match", "higher", 1], ["xa_match", "xA / match", "higher", 2],
];
const DECISIONS_PER_MATCH = 2700;       // 30 decisions/s x 90 s: reward per agent-decision -> per player and match
const state = { ov: null, detail: {}, health: null, lastOk: 0, firstFail: 0, sort: { key: "elo", dir: -1 }, filter: "", selected: new Set(), smooth: 0.8, hidden: {}, healthHours: 12, cmpCache: {}, evalPick: {}, estPick: {} };

// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
const sgn = (v, d = 2) => (v === null || v === undefined ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(d));
function hash(s) { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
const runColor = (name) => css(PALETTE[hash(name) % PALETTE.length]);
function dur(s) {
  if (s === null || s === undefined || Number.isNaN(s)) return "–";
  s = Math.max(0, Math.round(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m` : `${s}s`;
}
const parseT = (iso) => (iso && iso.includes("T") ? new Date(iso).getTime() / 1000 : null);
const ago = (iso) => { const t = typeof iso === "number" ? iso : parseT(iso); return t ? dur(Date.now() / 1000 - t) + " ago" : "–"; };
const hhmm = (t) => { const d = new Date(t * 1000); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
function badge(s) { const k = String(s || "unknown").replace(/\s+/g, ""); return `<span class="badge ${esc(k)}">${esc(s || "unknown")}</span>`; }
async function getJSON(url) { const r = await fetch(url, { cache: "no-store" }); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }
const runLink = (n) => `<a class="rl" href="#/run/${encodeURIComponent(n)}"><i class="dot" style="background:${runColor(n)}"></i>${esc(n)}</a>`;
function chips(row) {
  const out = [];
  if (row.stage) out.push(`<span class="chip net" title="a stage of the curriculum ${esc(row.curriculum || "")}: trains ${esc(row.stage)}">${esc(row.curriculum || "")} · ${esc(row.stage)}</span>`);
  if (row.net) out.push(`<span class="chip net" title="network: inputs-hidden-hidden-outputs">net ${esc(row.net)}</span>`);
  for (const [k, v] of Object.entries(row.rewards_changed_vs_minimal || {})) out.push(`<span class="chip rw">${esc(k)}=${esc(v)}</span>`);
  for (const [k, v] of Object.entries(row.args || {})) {
    const short = String(v).split(",").map((x) => x.split("/").pop().replace(/\.(pt|json)$/, "").replace(/^rl_5v5_arena_v/, "RL")).join(", ");
    out.push(`<span class="chip" title="${esc(k)}=${esc(v)}">${esc(k)}=${esc(short)}</span>`);
  }
  return out.join("") || '<span class="muted small">minimal</span>';
}
function throttle(hex) {
  if (!hex) return { text: "–", cls: "" };
  const v = parseInt(hex, 16);
  if (!v) return { text: "OK", cls: "pos", sub: "no throttling since boot" };
  const now = v & 0xf, past = v >> 16, names = ["under-voltage", "freq. capped", "throttled", "soft temp limit"];
  const list = (bits) => names.filter((_, i) => bits & (1 << i)).join(", ");
  return { text: now ? list(now) : "OK now", cls: now ? "neg" : "warn", sub: past ? "since boot: " + list(past) : "" };
}
// The health box describes whatever machine the pipeline runs on (lab/lab.py machine): the Pi reports throttle flags,
// a Mac its thermal pressure (macOS slows the CPU from "moderate" up), power source and battery charge.
function powerState(m) {
  if (m.kind !== "mac") return throttle(m.throttled);
  const lv = m.thermal, src = m.power ? (m.power === "AC" ? "on AC" : "on battery") + (m.battery_pct != null ? " · " + f(m.battery_pct, 0) + "%" : "") : "";
  if (lv == null) return { text: "–", cls: "", sub: src };
  return { text: lv === 0 ? "OK" : "thermal " + m.thermal_text, cls: lv === 0 ? "pos" : lv === 1 ? "warn" : "neg", sub: src };
}
function machineName(m) { return m?.name || "This machine"; }
function tempWarn(m) { return m?.temp_warn ?? 75; }
function ema(points, a) {
  if (!a) return points;
  let m = null;
  return points.map((p) => { if (p.y == null) return p; m = m === null ? p.y : a * m + (1 - a) * p.y; return { ...p, y: m }; });
}

// ---------- charts ----------
// series: [{name, color, points: [{x, y, err?, hollow?, label?}], dashed?, dots?, noLine?, faint?, noLegend?, width?}]
// opt: {height, width, yMin, yMax, xMin, zero, refs: [{y, label}], bands: [{y0, y1, label, color}], vlines: [{x, label}], time, fmt, xLabel, key, gap}
const chartData = {};
function lineChart(series, opt = {}) {
  const W = opt.width || 640, H = opt.height || 220, L = 44, R = 12, T = 10, B = 24;
  const key = opt.key || "", hidden = state.hidden[key] || new Set();
  const vis = series.filter((s) => !hidden.has(s.name));
  const valid = (p) => p.y != null && !Number.isNaN(p.y);
  if (!series.some((s) => s.points.some(valid))) return `<div class="empty">${esc(opt.emptyText || "No data yet")}</div>`;
  const pts = vis.flatMap((s) => s.points.filter(valid));
  const all = pts.length ? pts : series.flatMap((s) => s.points.filter(valid));
  let x0 = opt.xMin ?? Math.min(...all.map((p) => p.x)), x1 = opt.xMax ?? Math.max(...all.map((p) => p.x));
  if (x1 === x0) { x0 -= 1; x1 += 1; }
  const extra = [...(opt.refs || []).map((r) => r.y), ...(opt.bands || []).flatMap((b) => [b.y0, b.y1])];
  let y0 = opt.yMin ?? Math.min(...all.map((p) => p.y - (p.err || 0)), ...extra);
  let y1 = opt.yMax ?? Math.max(...all.map((p) => p.y + (p.err || 0)), ...extra);
  if (opt.zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  if (y1 === y0) { y0 -= 0.5; y1 += 0.5; }
  const pad = (y1 - y0) * 0.08; if (opt.yMin === undefined) y0 -= pad; if (opt.yMax === undefined) y1 += pad;
  const X = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - R), Y = (y) => T + ((y1 - y) / (y1 - y0)) * (H - T - B);
  const cy = (y) => Math.max(T, Math.min(H - B, Y(y)));
  let g = "";
  for (const b of opt.bands || []) g += `<rect x="${L}" width="${W - L - R}" y="${cy(Math.max(b.y0, b.y1))}" height="${Math.abs(cy(b.y0) - cy(b.y1))}" fill="${b.color || "var(--muted)"}" opacity=".14"/>${b.label ? `<text class="reft" x="${L + 4}" y="${cy(Math.max(b.y0, b.y1)) + 11}">${esc(b.label)}</text>` : ""}`;
  for (const t of niceTicks(y0, y1, 4)) g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${(opt.yTick || fmtTick)(t)}</text>`;
  const xt = opt.time ? timeTicks(x0, x1) : niceTicks(x0, x1, 6);
  for (const t of xt) if (t >= x0 && t <= x1) g += `<text class="ax" x="${X(t)}" y="${H - 6}" text-anchor="middle">${opt.time ? hhmm(t) : fmtTick(t)}</text>`;
  for (const r of opt.refs || []) g += `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(r.y)}" y2="${Y(r.y)}"/><text class="reft" x="${W - R}" y="${Y(r.y) - 4}" text-anchor="end">${esc(r.label)}</text>`;
  for (const v of opt.vlines || []) if (v.x >= x0 && v.x <= x1) g += `<line x1="${X(v.x)}" x2="${X(v.x)}" y1="${T}" y2="${H - B}" stroke="var(--bad)" stroke-dasharray="3 3"/><text class="reft" x="${X(v.x) + 3}" y="${T + 10}" style="fill:var(--bad)">${esc(v.label)}</text>`;
  for (const s of vis) {
    const p = s.points.filter(valid).sort((a, b) => a.x - b.x);
    if (!p.length) continue;
    if (p.length > 1 && !s.noLine) {
      const gap = opt.gap ?? medianGap(p) * 4;
      let d = "";
      p.forEach((q, i) => { d += (i === 0 || (gap && q.x - p[i - 1].x > gap) ? "M" : "L") + X(q.x).toFixed(1) + "," + Y(q.y).toFixed(1); });
      g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round" ${s.dashed ? 'stroke-dasharray="6 5"' : ""} ${s.faint ? 'opacity=".28"' : ""}/>`;
    }
    for (const q of p) {
      if (q.err) g += `<line x1="${X(q.x)}" x2="${X(q.x)}" y1="${cy(q.y - q.err)}" y2="${cy(q.y + q.err)}" stroke="${s.color}" stroke-width="2.2" opacity=".6"/>`;
      if (s.dots || p.length === 1) g += `<circle cx="${X(q.x)}" cy="${Y(q.y)}" r="4" fill="${q.hollow ? "var(--panel)" : s.color}" stroke="${s.color}" stroke-width="2"/>`;
    }
  }
  const id = "c" + Math.random().toString(36).slice(2);
  chartData[id] = { series: vis, X, Y, x0, x1, L, R, T, B, W, H, time: opt.time, xLabel: opt.xLabel || "update", fmt: opt.fmt || ((v) => f(v, 2)) };
  const named = series.filter((s) => s.points.length && !s.noLegend);
  const legend = named.length > 1 || opt.legend ? `<div class="legend">${named.map((s) => `<button class="lg ${hidden.has(s.name) ? "off" : ""}" data-key="${esc(key)}" data-series="${esc(s.name)}"><i class="${s.dashed ? "d" : ""}" style="background:${s.color};color:${s.color}"></i>${esc(s.name)}</button>`).join("")}</div>` : "";
  return `<div class="chart" data-chart="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.title || "chart")}">${g}<line class="hover-line" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/></svg>${legend}</div>`;
}
function medianGap(p) { if (p.length < 3) return 0; const d = p.slice(1).map((q, i) => q.x - p[i].x).sort((a, b) => a - b); return d[Math.floor(d.length / 2)]; }
function niceTicks(a, b, n) {
  const span = b - a, mag = Math.pow(10, Math.floor(Math.log10(span / n)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function timeTicks(a, b) {
  const span = b - a, steps = [300, 600, 1800, 3600, 7200, 10800, 21600, 43200, 86400];
  const step = steps.find((s) => span / s <= 6) || 86400, out = [], off = new Date().getTimezoneOffset() * 60;
  for (let v = Math.ceil((a - off) / step) * step + off; v <= b; v += step) out.push(v);
  return out;
}
function fmtTick(v) {
  const a = Math.abs(v);
  return a >= 1000 ? (v / 1000).toFixed(a >= 10000 ? 0 : 1) + "k" : a >= 10 || v === 0 ? String(Math.round(v)) : a >= 1 ? v.toFixed(1).replace(/\.0$/, "") : a >= 0.001 ? String(+v.toPrecision(2)) : v.toExponential(0);
}
function attachCharts(root) {
  for (const el of root.querySelectorAll("[data-chart]")) {
    const d = chartData[el.dataset.chart];
    if (!d) continue;
    const svg = $("svg", el), line = $(".hover-line", el), tip = $("#tip");
    const hide = () => { line.setAttribute("visibility", "hidden"); tip.hidden = true; };
    const show = (ev) => {
      const box = svg.getBoundingClientRect(), sx = ((ev.clientX - box.left) / box.width) * d.W;
      if (sx < d.L || sx > d.W - d.R) return hide();
      const xv = d.x0 + ((sx - d.L) / (d.W - d.L - d.R)) * (d.x1 - d.x0);
      let best = null;
      for (const s of d.series) for (const p of s.points) if (p.y != null && (best === null || Math.abs(p.x - xv) < Math.abs(best - xv))) best = p.x;
      if (best === null) return hide();
      line.setAttribute("x1", d.X(best)); line.setAttribute("x2", d.X(best)); line.setAttribute("visibility", "visible");
      let html = `<b>${d.time ? new Date(best * 1000).toLocaleString() : esc(d.xLabel) + " " + esc(fmtTick(best))}</b>`;
      for (const s of d.series) {
        const p = s.points.find((q) => q.x === best && q.y != null);
        if (p && !s.faint) html += `<br><span class="k" style="background:${s.color}"></span>${esc(s.name)}: <b>${d.fmt(p.y)}</b>${p.err ? ` ± ${d.fmt(p.err)}` : ""}${p.label ? ` <span style="opacity:.7">${esc(p.label)}</span>` : ""}`;
      }
      tip.innerHTML = html; tip.hidden = false;
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + "px";
      tip.style.top = Math.min(ev.clientY + 14, window.innerHeight - tip.offsetHeight - 8) + "px";
    };
    svg.addEventListener("pointermove", show);
    svg.addEventListener("pointerdown", show);                // touch: a tap shows the values
    svg.addEventListener("pointerleave", hide);
  }
}
function sparkline(pts, color, w = 110, h = 26, lo = 0, hi = 3) {
  if (!pts || pts.length < 2) return '<span class="muted">–</span>';
  const xs = pts.map((p) => p[0]), x0 = Math.min(...xs), x1 = Math.max(...xs);
  const Y = (v) => h - 2 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (h - 4);
  const P = pts.map((p) => `${(2 + ((p[0] - x0) / (x1 - x0 || 1)) * (w - 4)).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${P}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}
// forest plot: rows [{label, d, se, sig, sub}] -> differences with 95% intervals around zero
function forest(rows, unit = "pts") {
  const ok = rows.filter((r) => r.d != null && r.se != null);
  if (!ok.length) return '<div class="empty">Nothing to compare (needs evaluations of the same protocol)</div>';
  const m = Math.max(0.5, ...ok.map((r) => Math.abs(r.d) + 1.96 * r.se)) * 1.1, W = 640, rowH = 30, L = 170, R = 96, H = ok.length * rowH + 26;
  const X = (v) => L + ((v + m) / (2 * m)) * (W - L - R);
  let g = `<line x1="${X(0)}" x2="${X(0)}" y1="4" y2="${H - 20}" stroke="var(--muted)" stroke-dasharray="3 3"/>`;
  for (const t of niceTicks(-m, m, 6)) g += `<text class="ax" x="${X(t)}" y="${H - 4}" text-anchor="middle">${t > 0 ? "+" : ""}${fmtTick(t)}</text>`;
  ok.forEach((r, i) => {
    const y = 16 + i * rowH, c = r.sig === null ? "var(--muted)" : r.sig ? (r.d > 0 ? "var(--good)" : "var(--bad)") : "var(--slate)";
    g += `<text class="fl" x="${L - 10}" y="${y + 4}" text-anchor="end">${esc(r.label)}</text>`;
    g += `<line x1="${X(r.d - 1.96 * r.se)}" x2="${X(r.d + 1.96 * r.se)}" y1="${y}" y2="${y}" stroke="${c}" stroke-width="3" stroke-linecap="round" opacity=".55"/>`;
    g += `<circle cx="${X(r.d)}" cy="${y}" r="5.5" fill="${c}"/><text class="fv" x="${W - R + 8}" y="${y + 4}">${sgn(r.d)} ${esc(r.sub || "")}</text>`;
  });
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${g}</svg><div class="legend"><span>difference in ${esc(unit)}, bar = 95% interval · green / red = significant</span></div></div>`;
}
function heatmap(hm, title) {
  const w = hm.w, h = hm.h, c = 16, W = w * c, H = h * c, mx = Math.max(...hm.v, 1), base = css("--c3");
  let g = `<rect width="${W}" height="${H}" fill="var(--panel-2)"/>`;
  hm.v.forEach((v, i) => { if (v > 0) g += `<rect x="${(i % w) * c}" y="${Math.floor(i / w) * c}" width="${c}" height="${c}" fill="${base}" opacity="${(0.06 + 0.94 * Math.sqrt(v / mx)).toFixed(3)}"><title>${(v / 10).toFixed(1)}% of the time</title></rect>`; });
  g += `<rect x=".5" y=".5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--line)"/><line x1="${W / 2}" x2="${W / 2}" y1="0" y2="${H}" stroke="var(--line)"/><circle cx="${W / 2}" cy="${H / 2}" r="${c * 1.4}" fill="none" stroke="var(--line)"/>`;
  g += `<rect x="0" y="${H / 2 - c * 1.6}" width="4" height="${c * 3.2}" fill="var(--muted)"/><rect x="${W - 4}" y="${H / 2 - c * 1.6}" width="4" height="${c * 3.2}" fill="var(--bad)"/>`;
  return `<figure class="heat"><figcaption><span>${esc(title)}</span><span class="muted">${esc(hm.role !== "-" ? "slot " + hm.role : "")}</span></figcaption><svg viewBox="0 0 ${W} ${H}">${g}</svg></figure>`;
}
function kpi(label, value, sub = "", cls = "") { return `<div class="kpi"><div class="l">${label}</div><div class="v ${cls}">${value}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`; }
const smoothControl = () => `<label class="smooth">smoothing <input type="range" min="0" max="0.97" step="0.01" value="${state.smooth}" data-smooth> <b>${f(state.smooth, 2)}</b></label>`;

// the estimated Elo of the run's checkpoints (lab/ladder.py estimate) with 95% intervals; dashed reference lines: the start net's
// ladder rating and, once placed, the run's best checkpoint in the ladder
function estChart(d, height, key, width) {
  const es = d.estimates || [], se = d.start_elo, me = (state.ov?.runs || []).find((r) => r.name === d.run)?.elo;
  const refs = [];
  if (se && se.games && !se.estimate) refs.push({ y: se.elo, label: `start net ${se.name} ${f(se.elo, 0)}` });
  if (me && me.placed) refs.push({ y: me.elo, label: `ladder, best checkpoint ${f(me.elo, 0)}` });
  return lineChart([{ name: "estimated Elo", color: runColor(d.run), points: es.map((e) => ({ x: e.update, y: e.elo, err: 1.96 * e.se })), dots: true }],
    { height, width, refs, xMin: 0, key: "est-" + key, title: "estimated Elo", fmt: (v) => f(v, 0), yTick: (v) => String(Math.round(v)),
      emptyText: "no estimate yet: one comes with every check (every 50 updates)" });
}
function estGoalsChart(d, height, key, width) {
  const es = d.estimates || [];
  return lineChart([
    { name: "scored", color: css("--good"), points: es.map((e) => ({ x: e.update, y: e.gf, err: e.gf_se != null ? 1.96 * e.gf_se : 0 })), dots: true },
    { name: "conceded", color: css("--bad"), points: es.map((e) => ({ x: e.update, y: e.ga, err: e.ga_se != null ? 1.96 * e.ga_se : 0 })), dots: true },
  ], { height, width, yMin: 0, xMin: 0, key: "estg-" + key, title: "goals per match", legend: true, emptyText: "no estimate yet" });
}
