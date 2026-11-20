// The Lab area of the web app (web/app.py): dashboard of the experiment pipeline (API: lab/dashboard.py). Polls the JSON API every 10 s.
// It also owns the router: #/game/... routes go to the Game area (web/game.js).
// Routes: #/ now · #/live · #/runs · #/run/<name>[/<tab>] · #/compare?runs=a,b&kind=full · #/ranking · #/dataset[/<match>] · #/pi
// Charts are plain SVG (no libraries, no internet). Run colours are hashed from the run name, so they never change.
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
const state = { ov: null, detail: {}, health: null, lastOk: 0, firstFail: 0, sort: { key: "elo", dir: -1 }, filter: "", selected: new Set(), smooth: 0.8, hidden: {}, piHours: 12, cmpCache: {}, evalPick: {} };

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
  for (const t of niceTicks(y0, y1, 4)) g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fmtTick(t)}</text>`;
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

// ---------- NOW ----------
function viewNow() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const st = o.status, run = st.runner.running, pi = st.pi;
  let hero;
  if (run) {
    const row = o.runs.find((r) => r.name === run.run) || {};
    const spec = (o.queue.queued.find((q) => q.name === run.run) || {});
    const pct = run.target ? Math.min(100, (100 * (run.update || 0)) / run.target) : 0;
    const mode = run.evaluating ? "eval" : run.stalled ? "stale" : "";
    const lbl = run.evaluating ? badge("evaluating") : run.stalled ? `<span class="badge failed">no progress for ${dur(run.log_age_s)}</span>` : badge("running");
    const delta = run.train_pts_vs_rules != null && run.train_pts_at_start != null ? run.train_pts_vs_rules - run.train_pts_at_start : null;
    const lf = row.latest_fast;
    hero = `<section class="hero ${mode}"><div class="hero-top"><div class="min0"><div class="eyebrow">Running experiment</div><h1>${runLink(run.run)}</h1>
        <div class="notes">${esc(row.notes || "")}</div><div class="chips">${chips({ net: row.net, rewards_changed_vs_minimal: row.rewards_changed_vs_minimal, args: (state.detail[run.run]?.status?.spec?.args) || spec.args || {} })}</div></div><div>${lbl}</div></div>
      <div class="progress"><i style="width:${pct}%"></i></div>
      <div class="hero-stats"><div><b>${run.update ?? 0}<small> / ${run.target ?? "?"}</small></b><span>updates</span></div>
        <div><b>${run.eta_hours != null ? dur(run.eta_hours * 3600) : "–"}</b><span>training left</span></div>
        <div><b>${run.sec_per_update ? f(run.sec_per_update, 0) + " s" : "–"}</b><span>per update</span></div>
        <div><b>${f(run.train_pts_vs_rules)} <small class="${delta > 0 ? "pos" : delta < 0 ? "neg" : ""}">${delta != null ? sgn(delta) : ""}</small></b><span>training pts vs rules</span></div>
        <div><b>${lf ? f(lf.pts) : "–"}<small>${lf ? " u" + lf.update : ""}</small></b><span>last fast check</span></div>
        <div><b>${run.restarts.length}</b><span>restarts</span></div></div></section>`;
  } else {
    const nxt = o.queue.queued[0];
    hero = `<section class="hero idle"><div class="hero-top"><div><div class="eyebrow">Runner ${esc(st.runner.service || "")}</div><h1>Idle</h1><div class="notes">${nxt ? "Next: " + esc(nxt.name) : "The queue is empty."}</div></div>${badge("idle")}</div></section>`;
  }
  const th = throttle(pi.throttled);
  const hl = (o.health || []).filter((r) => r.t && r.t.includes("T"));
  const vit = (k, color, lo, hi) => sparkline(hl.map((r) => [parseT(r.t), r[k]]).filter((p) => p[1] != null), color, 110, 26, lo, hi);
  const rb = st.last_reboot;
  const vitals = `<section class="card vitals"><div class="card-h"><h2>Raspberry Pi</h2><a href="#/pi">details →</a></div>
    <div class="vrow"><span>Temperature</span><b class="${pi.temp_c > 75 ? "neg" : ""}">${f(pi.temp_c, 1)} °C</b>${vit("temp", css("--c2"), 30, 85)}</div>
    <div class="vrow"><span>CPU load</span><b>${f(pi.load_1m, 1)} <small>/ 4</small></b>${vit("load", css("--c1"), 0, 12)}</div>
    <div class="vrow"><span>Free memory</span><b class="${pi.mem_free_mb < 500 ? "neg" : ""}">${f(pi.mem_free_mb / 1024, 1)} GB</b>${vit("mem_mb", css("--c3"), 0, 3800)}</div>
    <div class="vrow"><span>Power</span><b class="${th.cls}">${esc(th.text)}</b><span class="muted small">up ${f(pi.uptime_hours, 1)} h</span></div>
    ${rb ? `<div class="vnote">Last reboot ${esc(ago(rb.back))} · last sample before it ${esc(rb.last_seen.replace("T", " "))}: load ${f(rb.last_sample.load, 1)}, ${f(rb.last_sample.mem_mb, 0)} MB free, ${f(rb.last_sample.temp, 0)} °C</div>` : ""}</section>`;
  let curve = '<div class="empty">Nothing training</div>';
  if (run) { const d = state.detail[run.run]; ensureDetail(run.run); curve = d && !d.error ? trainingChart(d, 200, "now") : '<div class="empty">Loading…</div>'; }
  const ev = o.events.slice(0, 9).map((e) => `<li class="ev ${esc(e.kind)}"><time>${esc((e.t || "").slice(11, 16))}</time><span>${esc(e.text)}</span></li>`).join("");
  const q = o.queue.queued.slice(0, 5).map((s, i) => `<li><span class="qn">${i + 1}</span><b>${esc(s.name)}</b><span class="chips">${chips({ rewards_changed_vs_minimal: s.rewards_changed_vs_minimal, args: s.args, net: s.net })}</span></li>`).join("");
  return `<div class="grid now-top">${hero}${vitals}</div>
    <div class="grid g2"><section class="card"><div class="card-h"><h2>League strength</h2><span class="muted small">latest full evaluation · 95% interval</span></div>${leaderboard(o.runs)}</section>
      <section class="card"><div class="card-h"><h2>Training${run ? " · " + esc(run.run) : ""}</h2>${smoothControl()}</div>${curve}</section></div>
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Events</h2><span class="muted small">last 24 h</span></div><ul class="events">${ev || '<li class="muted">nothing yet</li>'}</ul></section>
      <section class="card"><div class="card-h"><h2>Up next</h2><a href="#/runs">all runs →</a></div><ol class="queue">${q || '<li class="muted">queue empty</li>'}</ol></section></div>`;
}
function leaderboard(runs) {
  const rows = runs.filter((r) => r.latest_full && r.latest_full.protocol === "full/g1/d90" && r.latest_full.pts != null).sort((a, b) => b.latest_full.pts - a.latest_full.pts);
  if (!rows.length) return '<div class="empty">No full evaluations yet</div>';
  const P = (v) => Math.max(0, Math.min(100, (100 * v) / 3));
  const base = runs.find((r) => r.name.startsWith("start:") && r.latest_full)?.latest_full;
  return `<div class="lb">${rows.map((r) => {
    const a = r.latest_full, c = runColor(r.name);
    return `<div class="lb-row"><div class="name">${runLink(r.name)}</div><div class="lb-track"><div class="axis"></div>${base ? `<div class="base" style="left:${P(base.pts - 1.96 * base.se)}%;width:${P(base.pts + 1.96 * base.se) - P(base.pts - 1.96 * base.se)}%"></div>` : ""}
      <div class="err" style="left:${P(a.pts - 1.96 * a.se)}%;width:${P(a.pts + 1.96 * a.se) - P(a.pts - 1.96 * a.se)}%;background:${c}"></div><div class="pt" style="left:${P(a.pts)}%;background:${c}"></div></div>
      <div class="val">${f(a.pts)} <span class="pm">±${f(a.se)}</span></div></div>`;
  }).join("")}<div class="lb-row axisrow"><div></div><div class="ticks"><span>0</span><span>1</span><span>2</span><span>3 pts</span></div><div></div></div>
  ${base ? '<div class="muted small">grey band: the start net t48_u100 (95% interval)</div>' : ""}</div>`;
}
function trainingChart(d, height, key, width) {
  const t = d.training || [], a = state.smooth, mk = (k) => t.map((r) => ({ x: r.upd, y: r[k] }));
  return lineChart([
    { name: "vs rule bots (raw)", color: css("--c1"), points: mk("rules"), faint: true, noLegend: true },
    { name: "vs rule bots", color: css("--c1"), points: ema(mk("rules"), a) },
    { name: "vs frozen start net", color: css("--c2"), points: ema(mk("bench"), a), dashed: true },
    { name: "vs own snapshots", color: css("--c4"), points: ema(mk("league"), a), dashed: true },
  ], { height, width, yMin: 0, yMax: 3, key: "train-" + key, title: "training points" });
}

// ---------- RUNS ----------
const TYPE_LABEL = { rl: ["RL", "reinforcement learning (PPO self-play on the Pi)"], imitation: ["Imitation", "behaviour cloning on the recorded play (il/train.py)"] };
const shortVal = (v) => {
  if (v === null || v === undefined) return "off";
  if (typeof v === "number") return v !== 0 && Math.abs(v) < 0.001 ? v.toExponential() : String(+v.toPrecision(4));
  return String(v).split(",").map((x) => x.split("/").pop().replace(/\.(pt|json)$/, "").replace(/^rl_5v5_arena_v/, "RL")).join(", ");
};
function changeChips(list) {
  return (list || []).map((c) => {
    const was = c.was !== undefined && c.was !== null && c.k !== "start" ? `<span class="was">${esc(shortVal(c.was))} →</span> ` : "";
    return `<span class="chip ${c.kind === "reward" ? "rw" : ""}" title="${esc(c.k)}: ${esc(c.was ?? "default")} → ${esc(c.v ?? "default")}">${esc(c.k === "start" ? "from" : c.k)} ${was}${esc(shortVal(c.v))}</span>`;
  }).join("");
}
function changesCell(r) {
  if (r.state === "imported") return `<span class="muted small">${r.name.startsWith("start:") ? "imported checkpoint" : "older run"}</span>`;
  if (r.state === "reference") return '<span class="muted small">shipped team</span>';
  const ch = changeChips(r.changes);
  const start = r.start ? shortVal(r.start) : "";
  const sub = r.type === "imitation" ? "on the recorded play" : r.vs ? `vs ${esc(r.vs)}` : start ? `from ${esc(start)}` : "";
  return `<div class="chips">${ch || '<span class="muted small">same as reference</span>'}</div><div class="muted small">${sub}${r.net ? ` · net ${esc(r.net)}` : ""}</div>`;
}
function stateCell(r, o) {
  const run = o.status.runner.running;
  let sub = "";
  if (r.state === "running" && run && run.run === r.name) sub = run.evaluating ? "evaluating…" : run.eta_hours != null ? dur(run.eta_hours * 3600) + " left" : "";
  else if (r.queued) sub = `#${r.qpos} in queue`;
  else if (["diverged", "regressed", "failed", "cancelled"].includes(r.state)) sub = r.stop_reason && r.stop_reason !== r.state ? esc(r.stop_reason) : r.update != null ? `stopped at ${r.update}` : "";
  if (r.restarts) sub += `${sub ? " · " : ""}${r.restarts} restart${r.restarts > 1 ? "s" : ""}`;
  return `${badge(r.state === "evaluating" ? "evaluating" : r.state)}${sub ? `<div class="muted small">${sub}</div>` : ""}`;
}
function updateCell(r) {
  if (r.update == null && !r.target) return r.queued ? "" : "–";
  if (r.update_unit) return `${r.update}<span class="pm"> ${esc(r.update_unit)}</span>`;
  const pct = r.target ? Math.min(100, (100 * (r.update || 0)) / r.target) : 0;
  const cls = ["diverged", "regressed", "failed"].includes(r.state) ? "bad" : r.state === "cancelled" || r.queued ? "off" : "";
  return `${r.update ?? 0}${r.target ? `<span class="pm">/${r.target}</span><div class="mini ${cls}"><i style="width:${pct}%"></i></div>` : ""}`;
}
const ladderGoals = (e) => (e && e.games ? { gf: e.gf / e.games, ga: e.ga / e.games, gd: (e.gf - e.ga) / e.games } : null);
function eloCell(e, top) {
  if (!e) return '<span class="muted" title="not in the Elo ladder (no exported best checkpoint)">–</span>';
  const pm = e.hi != null ? Math.round((e.hi - e.lo) / 2) : null;
  return `<b class="${e.id === top ? "pos" : ""}">${Math.round(e.elo)}</b>${pm != null ? `<span class="pm">±${pm}</span>` : ""}<div class="muted small" title="${e.w}-${e.d}-${e.l} (won-drawn-lost) in ${e.games} ladder matches">${e.placed ? `#${e.rank}` : "placing"} · ${e.games} games${e.stored ? ' <span class="stored" title="rated from the ladder matches the Pi already played; this machine has no copy of the weights (out_5v5/ckpt/ stays on the Pi)">*</span>' : ""}</div>`;
}
const STOPPED = ["diverged", "regressed", "failed", "cancelled"];
const RF0 = { state: "all", type: "all", net: "", change: "", vs: "", ranked: false, hidden: false };
function runsFilter() {                                    // the Runs page filters, remembered in this browser
  if (!state.rf) { let saved = {}; try { saved = JSON.parse(localStorage.getItem("runsFilter") || "{}"); } catch (e) {} state.rf = { ...RF0, ...saved }; }
  return state.rf;
}
function setRunsFilter(k, v) {
  const rf = runsFilter();
  if (k === "reset") { state.rf = { ...RF0 }; state.filter = ""; } else rf[k] = v;
  try { localStorage.setItem("runsFilter", JSON.stringify(state.rf)); } catch (e) {}
  rerender();
}
function viewRuns() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const rf = runsFilter();
  const queued = o.queue.queued.map((s, i) => ({ name: s.name, net: s.net, state: "queued", type: "rl", notes: s.notes, changes: s.changes, vs: s.vs, start: s.start, target: s.updates, queued: true, qpos: i + 1 }));
  const all = o.runs.concat(o.imitation || [], queued);
  const stateOf = (r) => (STOPPED.includes(r.state) ? "stopped" : r.state);
  const tests = {
    search: (r) => !state.filter || (r.name + " " + (r.notes || "") + " " + (r.changes || []).map((c) => c.k + " " + shortVal(c.v)).join(" ")).toLowerCase().includes(state.filter.toLowerCase()),
    state: (r) => rf.state === "all" || stateOf(r) === rf.state,
    type: (r) => rf.type === "all" || r.type === rf.type,
    net: (r) => !rf.net || r.net === rf.net,
    change: (r) => !rf.change || (r.changes || []).some((c) => c.k === rf.change),
    vs: (r) => !rf.vs || r.vs === rf.vs || r.name === rf.vs,
    ranked: (r) => !rf.ranked || !!r.elo,
    hidden: (r) => rf.hidden || !r.hidden,                // exp/hidden_runs.json: failed, empty and leftover runs
  };
  const pass = (r, skip) => Object.entries(tests).every(([k, t]) => k === skip || t(r));
  let rows = all.filter((r) => pass(r));
  const k = state.sort.key, dir = state.sort.dir;
  const val = (r) => { const e = ladderGoals(r.elo); return { name: r.name, type: r.type, state: r.state, elo: r.elo?.elo ?? -1, gf: e ? e.gf : -99, gd: e ? e.gd : -99, ga: e ? e.ga : 99, cost: r.cost_hours ? (r.cost_hours.train || 0) + (r.cost_hours.eval || 0) : -1, fin: r.finished || r.started || "" }[k]; };
  rows.sort((x, y) => (val(x) > val(y) ? 1 : val(x) < val(y) ? -1 : 0) * dir);
  const th = (key, l, cls = "", tip = "") => `<th class="sort ${cls}" data-sort="${key}"${tip ? ` title="${esc(tip)}"` : ""}>${l}${k === key ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`;
  // each choice shows how many runs it would leave, given the other filters
  const seg = (key, list) => `<div class="rseg">${list.map(([v, l]) => { const c = all.filter((r) => pass(r, key) && (v === "all" || (key === "state" ? stateOf(r) : r[key]) === v)).length; return `<button class="${rf[key] === v ? "on" : ""}" data-rf="${key}" data-rv="${v}" ${c || v === "all" ? "" : "disabled"}>${l}<span>${c}</span></button>`; }).join("")}</div>`;
  const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
  const sel = (key, label, opts, tip = "") => `<label class="fsel ${rf[key] ? "on" : ""}" title="${esc(tip)}"><span>${label}</span><select data-rf="${key}"><option value="">any</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${rf[key] === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  const nets = uniq(all.map((r) => r.net)).map((n) => [n, n]);
  const keys = uniq(all.flatMap((r) => (r.changes || []).map((c) => c.k))).map((x) => [x, x === "start" ? "start net" : x]);
  const ctrls = uniq(all.map((r) => r.vs)).map((x) => [x, x]);
  const active = rf.state !== "all" || rf.type !== "all" || rf.net || rf.change || rf.vs || rf.ranked || rf.hidden || state.filter;
  const filters = `<div class="fbar">
      <input class="search" placeholder="Search name, notes, settings…" value="${esc(state.filter)}" data-filter>
      ${seg("state", [["all", "All"], ["running", "Running"], ["queued", "Queued"], ["done", "Done"], ["stopped", "Stopped"], ["imported", "Imported"], ["reference", "Reference"]])}
    </div>
    <div class="fbar">
      ${seg("type", [["all", "All types"], ["rl", "RL"], ["imitation", "Imitation"]])}${sel("net", "Net", nets)}${sel("change", "Changes", keys)}${sel("vs", "Experiment", ctrls, "a control run and the runs judged against it")}
      <label class="fchk ${rf.ranked ? "on" : ""}"><input type="checkbox" data-rf="ranked" ${rf.ranked ? "checked" : ""}> Has Elo</label>
      <label class="fchk ${rf.hidden ? "on" : ""}" title="failed, empty and leftover runs listed in exp/hidden_runs.json"><input type="checkbox" data-rf="hidden" ${rf.hidden ? "checked" : ""}> Show hidden <span class="muted">${all.filter((r) => r.hidden).length}</span></label>
      <span class="fcount">${rows.length} of ${all.length} runs</span>${active ? '<button class="linkbtn" data-rf="reset">Clear filters</button>' : ""}
    </div>`;
  const ladder = o.runs.concat(o.imitation || []).filter((r) => r.elo?.placed).sort((x, y) => y.elo.elo - x.elo.elo);
  const top = ladder[0]?.elo.id;
  const body = rows.map((r) => {
    const g = ladderGoals(r.elo), sel = state.selected.has(r.name), link = !r.queued && r.type !== "imitation";
    const [tl, tt] = TYPE_LABEL[r.type] || [r.type || "", ""];
    return `<tr class="${link ? "link" : "queued"}" data-run="${link ? esc(r.name) : ""}"><td class="k-hide">${link ? `<input type="checkbox" data-pick="${esc(r.name)}" ${sel ? "checked" : ""} aria-label="select ${esc(r.name)}">` : ""}</td>
      <td title="${esc(r.notes || "")}" class="${r.hidden ? "hid" : ""}">${link ? runLink(r.name) : `<span class="rl"><i class="dot" style="background:${r.queued ? "var(--line)" : runColor(r.name)}"></i>${esc(r.name)}</span>`}</td>
      <td class="k-hide"><span class="type ${esc(r.type || "")}" title="${esc(tt)}">${esc(tl)}</span></td>
      <td>${stateCell(r, o)}</td>
      <td class="k-hide">${changesCell(r)}</td>
      <td class="r">${updateCell(r)}</td>
      <td class="r elo">${r.queued ? "" : eloCell(r.elo, top)}</td>
      <td class="r">${g ? f(g.gf) : "–"}</td><td class="r">${g ? f(g.ga) : "–"}</td><td class="r ${g && g.gd > 0 ? "pos" : g && g.gd < 0 ? "neg" : ""}">${g ? sgn(g.gd) : "–"}</td>
      <td class="r small k-hide">${r.cost_hours ? f((r.cost_hours.train || 0) + (r.cost_hours.eval || 0), 1) + " h" : ""}</td><td class="small muted k-hide">${r.finished ? ago(r.finished) : r.started ? "since " + ago(r.started).replace(" ago", "") : ""}</td></tr>`;
  }).join("");
  const n = state.selected.size;
  return `<div class="head"><div><h1>Runs</h1><p>Experiments, imitation trainings, imported runs and the queue, ranked by Elo. Hover a name for its notes; tick runs to compare them; click a row for details.</p></div>
      <div class="tools"><a class="btn ${n ? "" : "disabled"}" href="#/compare?runs=${[...state.selected].map(encodeURIComponent).join(",")}">Compare ${n ? "(" + n + ")" : ""}</a></div></div>
    ${filters}
    <div class="card flush"><div class="tbl-wrap"><table class="runs"><thead><tr><th class="k-hide"></th>${th("name", "Run")}${th("type", "Type", "k-hide", "how the net was trained")}${th("state", "State")}<th class="k-hide" title="what this run changes against its control (vs …), or against the default recipe (from = the net it starts from)">Changes</th><th class="r">Update</th>${th("elo", "Elo", "r", "rating of the run's best checkpoint in the Elo ladder (lab/ladder.py: every team and net against each other), ±95%; the number to pick the best model by")}${th("gf", "GF", "r", "goals scored per match in the Elo ladder's matches (the same matches the Elo comes from)")}${th("ga", "GA", "r", "goals conceded per match in the Elo ladder's matches")}${th("gd", "GD", "r", "goal difference per match in the Elo ladder's matches")}${th("cost", "Cost", "r k-hide", "Pi hours: training + evaluation")}${th("fin", "When", "k-hide")}</tr></thead><tbody>${body || '<tr><td colspan="12" class="muted">No runs match</td></tr>'}</tbody></table></div></div>`;
}

// ---------- RUN ----------
const TABS = ["summary", "training", "evaluation", "behaviour", "scouting", "config"];
function viewRun(name, tab) {
  const d = state.detail[name]; ensureDetail(name);
  if (!d) return '<div class="empty">Loading…</div>';
  if (d.error) return `<div class="empty">${esc(d.error)}</div>`;
  tab = TABS.includes(tab) ? tab : "summary";
  const st = d.status || {}, row = d.row || {}, spec = st.spec || {};
  const head = `<div class="crumbs"><a href="#/runs">Runs</a> / ${esc(name)}</div>
    <div class="head"><div class="min0"><h1>${runLink(name)} ${badge(row.state)}</h1><p>${esc(row.notes || (row.state === "imported" ? "Imported from an older run (no spec)." : ""))}</p>${row.state === "imported" ? "" : `<div class="chips">${chips({ net: row.net, rewards_changed_vs_minimal: row.rewards_changed_vs_minimal, args: spec.args || {} })}</div>`}</div>
      <div class="meta">${row.update != null ? `update <b>${row.update}</b>${row.target ? " / " + row.target : ""}<br>` : ""}${row.started ? "started " + ago(row.started) + "<br>" : ""}${row.finished ? "finished " + ago(row.finished) + "<br>" : ""}${st.git_commit ? `commit <span class="mono">${esc(st.git_commit)}</span>${st.git_dirty ? " (dirty)" : ""}<br>` : ""}${(st.restarts || []).length ? `${st.restarts.length} restart(s)<br>` : ""}
      <a href="/api/v1/run/${encodeURIComponent(name)}" target="_blank">JSON</a> · <button class="linkbtn" data-copy="${esc(name)}">copy summary</button></div></div>
    <nav class="tabs">${TABS.map((t) => `<a class="${t === tab ? "on" : ""}" href="#/run/${encodeURIComponent(name)}/${t}">${t[0].toUpperCase() + t.slice(1)}</a>`).join("")}</nav>`;
  return head + ({ summary: runSummary, training: runTraining, evaluation: runEvaluation, behaviour: runBehaviour, scouting: runScouting, config: runConfig }[tab])(d);
}
const refEval = (d, protocol) => (d.reference?.evals || []).filter((e) => e.protocol === protocol).pop();
function runSummary(d) {
  const fulls = d.evals.filter((e) => e.kind === "full"), fasts = d.evals.filter((e) => e.kind === "fast");
  const last = fulls[fulls.length - 1], v = d.status.verdict, h = last?.h2h || {};
  const kp = `<div class="kpis">
    ${kpi(`League pts <span class="muted">${last ? "u" + last.update : ""}</span>`, last ? `${f(last.pts)}<small>± ${f(last.se)}</small>` : "–", last ? esc(last.protocol) : "no full evaluation yet")}
    ${kpi("Goal difference", last ? sgn(last.gd) : "–", last ? `GF ${f(last.gf)} · GA ${f(last.ga)}` : "", last && last.gd > 0 ? "pos" : last && last.gd < 0 ? "neg" : "")}
    ${kpi("Best move", last && last.greedy_pts != null ? f(last.greedy_pts) : "–", last && last.greedy_ga != null ? `GA ${f(last.greedy_ga)}` : "")}
    ${kpi("vs RL Team 4", f(h["RL Team 4"]?.pts), h["RL Team 4"] ? `n ${h["RL Team 4"].n} · GD ${sgn(h["RL Team 4"].gd)}` : "")}
    ${kpi("vs RL Team 5", f(h["RL Team 5"]?.pts), h["RL Team 5"] ? `n ${h["RL Team 5"].n} · GD ${sgn(h["RL Team 5"].gd)}` : "")}
    ${kpi("Verdict", v && v.verdict ? esc(v.verdict) : "–", v && v.verdict ? `${sgn(v.pts)} ± ${f(v.pts_se)} vs ${esc(v.reference)}${v.paired ? " · paired" : ""}` : "after the full evaluation", v?.verdict === "better" ? "pos" : v?.verdict === "worse" ? "neg" : "")}</div>`;
  const xMax = Math.max(100, d.row?.target || 0, ...d.evals.map((e) => e.update));
  const evChart = (list, protocol, title) => {
    const ref = refEval(d, protocol);
    return `<section class="card"><div class="card-h"><h2>${title}</h2><span class="muted small">${esc(protocol)} · 95% interval</span></div>${lineChart([{ name: d.run, color: runColor(d.run), points: list.map((e) => ({ x: e.update, y: e.pts, err: 1.96 * e.se, hollow: e.kind === "fast" })), dots: true, noLine: true }],
      { yMin: 0, yMax: 3, height: 200, xMin: 0, xMax, bands: ref ? [{ y0: ref.pts - 1.96 * ref.se, y1: ref.pts + 1.96 * ref.se, label: "reference " + (d.reference.name || "") }] : [], emptyText: "none yet", key: "ev" + protocol })}</section>`;
  };
  return `${kp}<div class="grid g2">${evChart(fulls, "full/g1/d90", "Full evaluations")}${evChart(fasts, "fast/g2/d60", "Fast checks")}</div>
    <section class="card"><div class="card-h"><h2>Training points</h2>${smoothControl()}</div>${trainingChart(d, 250, "run", 1240)}</section>`;
}
function runTraining(d) {
  const p = d.ppo || [], t = d.training || [], a = state.smooth;
  const small = (title, sub, series, opt = {}) => `<section class="card"><div class="card-h"><h3>${title}</h3></div>${sub ? `<div class="sub">${sub}</div>` : ""}${lineChart(series, { height: 170, width: 420, ...opt })}</section>`;
  const s = (k, c, name, extra = {}) => ({ name, color: css(c), points: ema(p.map((r) => ({ x: r.upd, y: r[k] })), a), ...extra });
  const hasTeacher = p.some((r) => r.kl_teacher != null);
  const terms = d.terms || [];
  const keys = [...new Set(terms.flatMap((r) => Object.keys(r).filter((k) => k !== "upd")))];
  const recent = terms.slice(-20);
  const means = keys.map((k) => ({ k, v: recent.reduce((acc, r) => acc + (r[k] || 0), 0) / Math.max(recent.length, 1) })).filter((m) => m.v).sort((x, y) => Math.abs(y.v) - Math.abs(x.v));
  const tot = means.reduce((acc, m) => acc + Math.abs(m.v), 0) || 1;
  const shareSeries = means.slice(0, 8).map((m, i) => ({ name: TERM_LABEL[m.k] || m.k, color: css(PALETTE[i % PALETTE.length]), points: ema(terms.map((r) => { const tt = keys.reduce((acc, kk) => acc + Math.abs(r[kk] || 0), 0) || 1; return { x: r.upd, y: (100 * Math.abs(r[m.k] || 0)) / tt }; }), a) }));
  const table = means.map((m) => `<tr><td>${esc(TERM_LABEL[m.k] || m.k)}</td><td class="r ${m.v > 0 ? "pos" : "neg"}">${sgn(m.v * DECISIONS_PER_MATCH, 2)}</td><td class="r">${f((100 * Math.abs(m.v)) / tot, 0)}%</td></tr>`).join("");
  return `<div class="toolbar">${smoothControl()}</div><div class="grid g3">
    ${small("Approx. KL per update", "healthy band 0.001–0.02", [s("kl", "--c1", "KL")], { bands: [{ y0: 0.001, y1: 0.02, color: "var(--good)" }], fmt: (v) => f(v, 4), key: "kl" })}
    ${small("Clip fraction", "share of samples clipped by PPO", [s("clipfrac", "--c2", "clip fraction")], { fmt: (v) => f(v, 3), key: "cf" })}
    ${small("Critic explained variance", "1 = perfect value predictions", [s("ev", "--c3", "explained variance")], { yMax: 1, key: "evr" })}
    ${small("Move entropy", "randomness of the moves", [s("ent_move", "--c4", "move")], { key: "em" })}
    ${small("Kick entropy", "", [s("ent_kick", "--c5", "kick")], { fmt: (v) => f(v, 3), key: "ek" })}
    ${hasTeacher ? small("Teacher KL", "distance to the teacher's moves, and its weight", [s("kl_teacher", "--c6", "KL to teacher"), s("kl_w", "--c7", "weight", { dashed: true })], { key: "klt" })
      : small("Decisions / s", "simulation speed", [{ name: "dec/s", color: css("--c6"), points: t.map((r) => ({ x: r.upd, y: r.dps })) }], { key: "dps", yMin: 0 })}
  </div><div class="grid g2"><section class="card"><div class="card-h"><h2>Reward composition</h2><span class="muted small">share of |reward| per term, %</span></div>${lineChart(shareSeries, { height: 240, yMin: 0, key: "terms", fmt: (v) => f(v, 1) + "%" })}</section>
  <section class="card flush"><div class="card-h pad"><h2>Reward per player and match</h2><span class="muted small">mean of the last 20 updates</span></div><div class="tbl-wrap"><table><thead><tr><th>Term</th><th class="r">per match</th><th class="r">share</th></tr></thead><tbody>${table || '<tr><td colspan="3" class="muted">no data</td></tr>'}</tbody></table></div></section></div>`;
}
function runEvaluation(d) {
  const evs = d.evals;
  if (!evs.length) return '<div class="empty">No evaluation yet</div>';
  const e = evs.find((x) => x.id && x.id === state.evalPick[d.run]) || evs.filter((x) => x.kind === "full").pop() || evs[evs.length - 1];
  const sel = `<select data-evalpick="${esc(d.run)}">${evs.map((x) => `<option value="${esc(x.id || "")}" ${x === e ? "selected" : ""}>${x.kind} · u${x.update} · ${esc(x.protocol)}</option>`).join("")}</select>`;
  const ref = refEval(d, e.protocol);
  const L = e.league_all || {}, G = e.greedy_all || {}, R = ref || null;
  const tiers = ["weak", "average", "strong", "elite", "held", "train", "all"].filter((t) => L[t]);
  const tierRows = tiers.map((t) => `<tr><td>${t === "held" ? "held-out teams" : t === "train" ? "trained-against" : t === "all" ? "<b>all 16</b>" : t}</td><td class="r">${f(L[t].pts)}<span class="pm">±${f(L[t].se)}</span></td><td class="r ${L[t].gd > 0 ? "pos" : L[t].gd < 0 ? "neg" : ""}">${sgn(L[t].gd)}</td><td class="r">${f(L[t].ga)}</td><td class="r">${L[t].n}</td><td class="r">${G[t] ? f(G[t].pts) : "–"}</td><td class="r">${G[t] ? f(G[t].ga) : "–"}</td></tr>`).join("");
  const h2h = Object.entries(e.h2h_full || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r">${f(v.pts)}<span class="pm">±${f(v.se)}</span></td><td class="r">${v.w}/${v.d}/${v.l}</td><td class="r ${v.gd > 0 ? "pos" : v.gd < 0 ? "neg" : ""}">${sgn(v.gd)}</td><td class="r">${v.n}</td></tr>`).join("");
  let fr;
  if (R && R.league_all && d.reference.name !== d.run) {
    const floor = (x) => Math.max(x.se, 0.5 / Math.sqrt(Math.max(x.n, 1)));
    const rowsF = tiers.filter((t) => R.league_all[t] && t !== "all").map((t) => { const dd = L[t].pts - R.league_all[t].pts, se = Math.hypot(floor(L[t]), floor(R.league_all[t])); return { label: t, d: dd, se, sig: Math.abs(dd / se) > 1.96 }; });
    const key = `${d.run}|${e.update}|${e.kind}`, c = state.cmpCache[key];
    if (c && c.pts != null) rowsF.unshift({ label: "all 16" + (c.paired ? " · paired" : ""), d: c.pts, se: c.pts_se, sig: Math.abs(c.z) > 1.96, sub: `z ${f(c.z, 1)}` });
    else fetchCompare(d.run, e, d.reference.name, R.update, key);
    fr = `<section class="card"><div class="card-h"><h2>Difference vs ${esc(d.reference.name)}</h2><span class="muted small">${esc(e.protocol)}</span></div>${forest(rowsF)}</section>`;
  } else fr = `<section class="card"><div class="card-h"><h2>Difference vs reference</h2></div><div class="empty">No reference evaluation with protocol ${esc(e.protocol)}</div></section>`;
  return `<div class="toolbar">Evaluation ${sel} <span class="muted small">${e.eval_seconds ? "took " + dur(e.eval_seconds) : ""}${e.paired_matches ? " · " + e.paired_matches + " matches stored" : ""}</span></div>
    <div class="grid g2"><section class="card flush"><div class="card-h pad"><h2>League by opponent tier</h2></div><div class="tbl-wrap"><table><thead><tr><th>Opponents</th><th class="r">Pts</th><th class="r">GD</th><th class="r">GA</th><th class="r">N</th><th class="r">Best move</th><th class="r">GA</th></tr></thead><tbody>${tierRows}</tbody></table></div></section>
    ${fr}</div><section class="card flush"><div class="card-h pad"><h2>Head to head</h2></div><div class="tbl-wrap"><table><thead><tr><th>Opponent</th><th class="r">Pts</th><th class="r">W/D/L</th><th class="r">GD</th><th class="r">N</th></tr></thead><tbody>${h2h || '<tr><td colspan="5" class="muted">none</td></tr>'}</tbody></table></div></section>`;
}
function runBehaviour(d) {
  const e = d.evals.filter((x) => x.kind === "full").pop();
  if (!e) return '<div class="empty">Behaviour is measured in full evaluations: none yet</div>';
  const b = e.behaviour || {}, rb = e.behaviour_rule_bots || {};
  const bars = BEHAVIOUR.filter(([k]) => b[k] != null).map(([k, label, , dec]) => {
    const v = b[k], r = rb[k], mx = Math.max(v, r || 0) * 1.15 || 1;
    return `<div class="bh"><div class="bl">${label}</div><div class="bt"><i style="width:${(100 * v) / mx}%;background:${runColor(d.run)}"></i>${r != null ? `<span class="rf" style="left:${(100 * r) / mx}%" title="rule bots ${f(r, dec)}"></span>` : ""}</div><div class="bv">${f(v, dec)}${r != null ? `<span class="pm"> rules ${f(r, dec)}</span>` : ""}</div></div>`;
  }).join("");
  const heats = (d.heat || []).map((hm) => heatmap(hm, hm.slot === "ball" ? "Ball" : "Player slot " + (Number(hm.slot) + 1))).join("");
  return `<div class="grid g2"><section class="card"><div class="card-h"><h2>Behaviour vs the rule bots</h2><span class="muted small">u${e.update} · tick = rule bots</span></div>${bars}</section>
    <section class="card"><div class="card-h"><h2>Where the players are</h2><span class="muted small">share of time · attacking right</span></div><div class="heats">${heats || '<div class="empty">no heatmaps</div>'}</div>
    <div class="hlegend"><span>rare</span><i></i><span>often</span></div><p class="muted small">Per player slot: with no fixed roles a slot is not a position. Role-based views come with the scouting page.</p></section></div>`;
}
function runConfig(d) {
  const c = d.config || {}, m = d.minimal || {}, df = d.defaults || {};
  const changed = Object.keys(c).filter((k) => (k in m && m[k] != c[k]) || (k in df && df[k] != c[k] && !["updates", "start_update"].includes(k)) || ["teacher", "opp_models", "kl_coef", "hidden"].includes(k) && c[k] && c[k] !== 128);
  const kv = (keys) => keys.map((k) => `<dt>${esc(k)}</dt><dd class="${changed.includes(k) ? "hl" : ""}">${esc(typeof c[k] === "object" ? JSON.stringify(c[k]) : c[k])}</dd>`).join("");
  return `<div class="grid g2"><section class="card"><div class="card-h"><h2>Changed vs the defaults</h2></div><dl class="kv">${kv(changed) || '<dt class="muted">nothing: minimal rewards, default settings</dt><dd></dd>'}</dl></section>
    <section class="card"><div class="card-h"><h2>Spec</h2></div><pre>${esc(JSON.stringify(d.status.spec || {}, null, 1))}</pre></section></div>
    <details class="card"><summary>All ${Object.keys(c).length} settings</summary><dl class="kv">${kv(Object.keys(c).sort())}</dl></details>`;
}

// ---------- SCOUTING ----------
const STYLE = [
  ["possession_pct", "Possession %", 0], ["field_tilt_pct", "Field tilt % (our possession in the final third)", 0], ["ball_own_half_pct", "Ball in our half %", 0],
  ["ppda", "PPDA (opp. passes per our defensive action, their build-up zone)", 1], ["press_d1_px", "Pressing: nearest player to the ball px", 0], ["press_d2_px", "Pressing: 2nd nearest px", 0],
  ["at_wall_pct", "Time pressed against the wall % (per player)", 1], ["ball_corner_pct", "Ball in a corner % of the time", 1], ["ball_corner_ours_pct", "Ball in a corner after our touch %", 1], ["goal_guarded_pct", "Goal guarded % (someone within 180 px)", 0], ["goal_empty_pct", "Goal empty % (nobody within 300 px)", 0], ["deepest_to_goal_px", "Deepest player to our goal px", 0],
  ["passes_match", "Passes / match", 1], ["pass_ok_pct", "Pass completion %", 0], ["progressive_match", "Progressive passes / match", 1],
];
function styleTags(sc) {
  const t = [], sh = sc.shape || {};
  if (sc.possession_pct >= 56) t.push("possession"); else if (sc.possession_pct <= 44) t.push("counter-attacking");
  if (sc.press_d1_px <= 110) t.push("high press"); else if (sc.press_d1_px >= 220) t.push("sits back");
  if (sh.out && sh.out.back_line_px >= 520) t.push("high line"); else if (sh.out && sh.out.back_line_px <= 260) t.push("deep block");
  if (sc.goal_guarded_pct <= 35) t.push("no fixed keeper"); else if (sc.goal_guarded_pct >= 75) t.push("keeper stays home");
  if (sc.goal_empty_pct >= 15) t.push("empty goal often");
  const pl = (sc.pass_len || []).slice().sort((a, b) => a - b), med = pl.length ? pl[Math.floor(pl.length / 2)] : null;
  if (med !== null && med <= 40) t.push("short touches"); else if (med !== null && med >= 150) t.push("long balls");
  if (sh.in && sh.in.width_px >= 380) t.push("wide"); else if (sh.in && sh.in.width_px <= 200) t.push("narrow");
  return t;
}
function pitch(content, W = 640, H = 300) {
  const X = (x) => ((x + 1) / 2) * W, Y = (y) => ((y + 1) / 2) * H;
  let g = `<rect width="${W}" height="${H}" rx="6" fill="color-mix(in srgb, var(--c3) 9%, var(--panel-2))" stroke="var(--line)"/>`;
  g += `<line x1="${W / 2}" x2="${W / 2}" y1="0" y2="${H}" stroke="var(--line)"/><circle cx="${W / 2}" cy="${H / 2}" r="${H * 0.2}" fill="none" stroke="var(--line)"/>`;
  g += `<rect x="0" y="${Y(-0.63)}" width="${W * 0.13}" height="${Y(0.63) - Y(-0.63)}" fill="none" stroke="var(--line)"/><rect x="${W * 0.87}" y="${Y(-0.63)}" width="${W * 0.13}" height="${Y(0.63) - Y(-0.63)}" fill="none" stroke="var(--line)"/>`;
  g += `<rect x="-5" y="${Y(-0.38)}" width="5" height="${Y(0.38) - Y(-0.38)}" fill="var(--muted)"/><rect x="${W}" y="${Y(-0.38)}" width="5" height="${Y(0.38) - Y(-0.38)}" fill="var(--bad)"/>`;
  return `<svg viewBox="-6 -2 ${W + 12} ${H + 4}" class="pitchsvg">${g}${content(X, Y)}</svg>`;
}
const RANK = ["deepest", "2nd deepest", "middle", "2nd most advanced", "most advanced"];
function runScouting(d) {
  const sc = d.scout, ref = d.scout_ref;
  if (!sc) return '<div class="empty">No scouting data yet: it comes with the next full evaluation (or a scout evaluation).</div>';
  const c = runColor(d.run), tags = styleTags(sc);
  const formation = pitch((X, Y) => ["out", "in"].map((ph) => (sc.avg_pos[ph] || []).map((p, i) => `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="14" fill="${ph === "in" ? c : "var(--panel)"}" stroke="${c}" stroke-width="2.5" ${ph === "out" ? 'stroke-dasharray="4 3"' : ""}><title>${RANK[i]} · ${ph === "in" ? "in" : "out of"} possession</title></circle><text x="${X(p[0])}" y="${Y(p[1]) + 4.5}" text-anchor="middle" class="pnum" style="fill:${ph === "in" ? "#0d1117" : "var(--ink)"}">${i + 1}</text>`).join("")).join(""));
  const sh = sc.shape || {};
  const shapeRows = [["Width", "width_px"], ["Depth", "depth_px"], ["Last man from goal line", "last_man_px"], ["Back line (2nd deepest)", "back_line_px"]].map(([l, k]) => `<tr><td>${l}</td><td class="r">${f(sh.in?.[k], 0)}</td><td class="r">${f(sh.out?.[k], 0)}</td></tr>`).join("");
  const nm = sc.matches || 1, xgF = (sc.shots || []).reduce((a, s) => a + s[2], 0), xgA = (sc.shots_against || []).reduce((a, s) => a + s[2], 0);
  const shots = pitch((X, Y) => (sc.shots_against || []).map((s) => `<circle cx="${X(s[0])}" cy="${Y(s[1])}" r="${4 + 20 * Math.sqrt(s[2])}" fill="${s[3] ? "var(--bad)" : "none"}" fill-opacity=".45" stroke="var(--bad)" stroke-width="1.5"><title>against · xG ${f(s[2])}${s[3] ? " · on target" : ""}</title></circle>`).join("") +
    (sc.shots || []).map((s) => `<circle cx="${X(s[0])}" cy="${Y(s[1])}" r="${4 + 20 * Math.sqrt(s[2])}" fill="${s[3] ? c : "none"}" fill-opacity=".55" stroke="${c}" stroke-width="1.5"><title>for · xG ${f(s[2])}${s[3] ? " · on target" : ""}</title></circle>`).join(""));
  // pass network: a slot sits where its depth ranks put it (role share x average position in possession)
  const heatPos = (d.heat || []).filter((h) => h.slot !== "ball").map((h) => { let x = 0, y = 0, n = 0; h.v.forEach((v, i) => { x += v * (((i % h.w) + 0.5) / h.w * 2 - 1); y += v * ((Math.floor(i / h.w) + 0.5) / h.h * 2 - 1); n += v; }); return n ? [x / n, y / n] : null; });
  const slotPos = heatPos.length === 5 && heatPos.every(Boolean) ? heatPos      // each slot at its mean position (heatmap of the same evaluation)
    : (sc.role_share || []).map((row) => { let x = 0, y = 0; row.forEach((pct, r) => { const p = sc.avg_pos.in[r] || [0, 0]; x += (pct / 100) * p[0]; y += (pct / 100) * p[1]; }); return [x, y]; });
  const maxE = Math.max(1, ...(sc.edges || []).map((e) => e[2]));
  const net = pitch((X, Y) => (sc.edges || []).filter((e) => e[0] !== e[1]).map((e) => { const a = slotPos[e[0]], b = slotPos[e[1]]; return a && b ? `<line x1="${X(a[0])}" y1="${Y(a[1])}" x2="${X(b[0])}" y2="${Y(b[1])}" stroke="${c}" stroke-width="${1 + 7 * (e[2] / maxE)}" stroke-opacity=".55" stroke-linecap="round"><title>slot ${e[0] + 1} → ${e[1] + 1}: ${e[2]} passes</title></line>` : ""; }).join("") +
    slotPos.map((p, i) => `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="13" fill="${c}"/><text x="${X(p[0])}" y="${Y(p[1]) + 4.5}" text-anchor="middle" class="pnum" style="fill:#0d1117">${i + 1}</text>`).join(""));
  const recov = pitch((X, Y) => (sc.recoveries || []).map((r) => `<circle cx="${X(r[0])}" cy="${Y(r[1])}" r="4.5" fill="${r[2] === "t" ? "var(--c2)" : r[2] === "i" ? "var(--c1)" : "var(--c5)"}" fill-opacity=".8"><title>${{ t: "tackle", i: "interception", r: "loose ball" }[r[2]]}</title></circle>`).join(""));
  const roleRows = (sc.role_share || []).map((row, i) => `<tr><td>slot ${i + 1}</td>${row.map((v) => `<td class="r rs" style="background:color-mix(in srgb, ${c} ${Math.round(v * 0.85)}%, transparent)">${f(v, 0)}</td>`).join("")}</tr>`).join("");
  const nums = STYLE.map(([k, l, dec]) => `<tr><td>${l}</td><td class="r"><b>${f(sc[k], dec)}</b></td>${ref ? `<td class="r muted">${f(ref[k], dec)}</td>` : ""}</tr>`).join("");
  return `<div class="tagrow">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("") || '<span class="muted">no strong style signals</span>'}<span class="muted small">${esc(sc.kind)} evaluation u${sc.update} · ${nm} matches of 60 s vs 4 rule teams · sampled moves</span></div>
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Formation by depth rank</h2><span class="muted small">filled = in possession · dashed = out · attacking right</span></div>${formation}
      <table class="mini"><thead><tr><th>Shape px</th><th class="r">in poss.</th><th class="r">out of poss.</th></tr></thead><tbody>${shapeRows}</tbody></table></section>
      <section class="card"><div class="card-h"><h2>Shots</h2><span class="muted small">size = xG · filled = on target · red = against</span></div>${shots}
      <div class="statline"><span>for <b>${f((sc.shots || []).length / nm, 1)}</b> shots · xG <b>${f(xgF / nm)}</b> / match · ${f(xgF / Math.max((sc.shots || []).length, 1))} per shot</span><span>against <b>${f((sc.shots_against || []).length / nm, 1)}</b> · xG <b>${f(xgA / nm)}</b></span></div></section></div>
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Pass network</h2><span class="muted small">completed passes between slots · node = the slot's mean position</span></div>${net}</section>
      <section class="card"><div class="card-h"><h2>Where the ball is won</h2><span class="muted small"><i class="lgd" style="background:var(--c2)"></i>tackle <i class="lgd" style="background:var(--c1)"></i>interception <i class="lgd" style="background:var(--c5)"></i>loose ball</span></div>${recov}</section></div>
    <div class="grid g2"><section class="card flush"><div class="card-h pad"><h2>Style numbers</h2>${ref ? `<span class="muted small">grey: ${esc(ref.name)}</span>` : ""}</div><div class="tbl-wrap"><table><tbody>${nums}</tbody></table></div></section>
      <section class="card flush"><div class="card-h pad"><h2>Who plays where</h2><span class="muted small">% of time each slot is at each depth rank</span></div><div class="tbl-wrap"><table><thead><tr><th></th>${RANK.map((r) => `<th class="r small">${r}</th>`).join("")}</tr></thead><tbody>${roleRows}</tbody></table></div>
      <p class="muted small pad">No fixed roles: a slot that is the deepest most of the time is the de-facto keeper.</p></section></div>`;
}

// ---------- COMPARE ----------
function viewCompare(params) {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const names = o.runs.map((r) => r.name);
  let runs = (params.get("runs") || "").split(",").filter((n) => names.includes(n));
  if (!runs.length) runs = [names.find((n) => n.startsWith("start:")), o.status.runner.running?.run].filter(Boolean);
  const kind = params.get("kind") || "full";
  runs.forEach(ensureDetail);
  const ref = runs[0];
  const add = `<select data-addrun><option value="">+ add run…</option>${names.filter((n) => !runs.includes(n)).map((n) => `<option>${esc(n)}</option>`).join("")}</select>`;
  const chipsR = runs.map((n, i) => `<span class="rchip">${runLink(n)}${i === 0 ? ' <span class="muted small">reference</span>' : ""}<button data-rmrun="${esc(n)}" aria-label="remove">×</button></span>`).join("");
  const kinds = ["full", "fast"].map((k) => `<button class="pill ${kind === k ? "on" : ""}" data-kind="${k}">${k === "full" ? "full evaluations" : "fast checks"}</button>`).join("");
  const latestOf = (n) => (state.detail[n]?.evals || []).filter((e) => e.kind === kind).pop();
  const rows = [], warn = [];
  for (const n of runs.slice(1)) {
    const a = latestOf(n), b = latestOf(ref);
    if (!a || !b) { if (state.detail[n] && state.detail[ref]) warn.push(`${n}: no ${kind} evaluation`); continue; }
    if (a.protocol !== b.protocol) { warn.push(`${n}: protocol ${a.protocol} ≠ ${b.protocol}`); continue; }
    const key = `${n}|${a.update}|${kind}|${ref}`, c = state.cmpCache[key];
    if (!c) fetchCompare(n, a, ref, b.update, key);
    rows.push({ label: n, d: c && c.pts != null ? c.pts : a.pts - b.pts, se: c && c.pts != null ? c.pts_se : Math.hypot(a.se, b.se), sig: c && c.z != null ? Math.abs(c.z) > 1.96 : null, sub: c && c.z != null ? `z ${f(c.z, 1)}${c.paired ? " paired" : ""}` : "…" });
  }
  const metrics = [["League pts", (e) => e.pts, (e) => e.se], ["Goal difference", (e) => e.gd, (e) => e.gd_se], ["Conceded", (e) => e.ga], ["Best-move pts", (e) => e.greedy_pts], ["vs RL Team 4", (e) => e.h2h?.["RL Team 4"]?.pts], ["vs RL Team 5", (e) => e.h2h?.["RL Team 5"]?.pts], ["Direction changes/s", (e) => e.behaviour?.dir_changes_s], ["Idle %", (e) => e.behaviour?.idle_pct], ["Spacing px", (e) => e.behaviour?.spacing_px]];
  const r0 = latestOf(ref);
  const table = `<table><thead><tr><th>Latest ${kind}</th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${metrics.map(([lbl, g, s]) => `<tr><td>${lbl}</td>${runs.map((n, i) => { const e = latestOf(n), v = e ? g(e) : null, dv = i && v != null && r0 && g(r0) != null ? v - g(r0) : null; return `<td class="r">${f(v)}${s && e && s(e) != null ? `<span class="pm">±${f(s(e))}</span>` : ""}${dv != null ? `<div class="small ${dv > 0 ? "pos" : dv < 0 ? "neg" : "muted"}">${sgn(dv)}</div>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table>`;
  const styleTable = runs.some((n) => state.detail[n]?.scout) ? `<section class="card flush" style="margin-bottom:14px"><div class="card-h pad"><h2>Style</h2><span class="muted small">latest scouting data of each run</span></div><div class="tbl-wrap"><table><thead><tr><th></th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${STYLE.map(([k, l, dec]) => `<tr><td>${l}</td>${runs.map((n) => `<td class="r">${f(state.detail[n]?.scout?.[k], dec)}</td>`).join("")}</tr>`).join("")}<tr><td>Tags</td>${runs.map((n) => `<td class="r small">${state.detail[n]?.scout ? esc(styleTags(state.detail[n].scout).join(", ")) : "–"}</td>`).join("")}</tr></tbody></table></div></section>` : "";
  const tr = runs.map((n) => ({ name: n, color: runColor(n), points: ema((state.detail[n]?.training || []).map((r) => ({ x: r.upd, y: r.rules })), state.smooth) }));
  const ev = runs.map((n) => ({ name: n, color: runColor(n), points: (state.detail[n]?.evals || []).filter((e) => e.kind === kind).map((e) => ({ x: e.update, y: e.pts, err: 1.96 * e.se })), dots: true, noLine: true }));
  return `<div class="head"><div><h1>Compare</h1><p>Each run against the first, on the same evaluation protocol only; paired over identical matches when possible.</p></div><div class="pills">${kinds}</div></div>
    <div class="rchips">${chipsR}${add}</div>${warn.length ? `<div class="flag warn">${warn.map(esc).join(" · ")}</div>` : ""}
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Difference vs ${esc(ref || "")}</h2><span class="muted small">league pts, 95% interval</span></div>${forest(rows)}</section>
      <section class="card flush"><div class="tbl-wrap">${table}</div></section></div>
    ${styleTable}
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Training points vs rule bots</h2>${smoothControl()}</div>${lineChart(tr, { yMin: 0, yMax: 3, height: 220, key: "cmp-tr" })}</section>
      <section class="card"><div class="card-h"><h2>${kind === "full" ? "Full evaluations" : "Fast checks"}</h2><span class="muted small">95% interval</span></div>${lineChart(ev, { yMin: 0, yMax: 3, height: 220, xMin: 0, key: "cmp-ev" })}</section></div>`;
}

// ---------- PI ----------
// ---- Docs: the project's Markdown files, rendered here (a small Markdown renderer: headings, tables, lists, code, links; no libraries)
const docs = { list: null, text: {}, loading: new Set() };
function loadDocs(id) {
  const key = id || "*";
  if (docs.loading.has(key)) return;
  docs.loading.add(key);
  (id ? fetch("/api/docs/" + encodeURIComponent(id)).then((r) => (r.ok ? r.text() : Promise.reject())).then((t) => { docs.text[id] = t; })
      : fetch("/api/docs").then((r) => r.json()).then((d) => { docs.list = d.docs; }))
    .catch(() => { if (id) docs.text[id] = null; else docs.list = []; })
    .finally(() => { docs.loading.delete(key); rerender(); });
}
function resolveDoc(href, base) {          // a relative link of a document -> a path from the project root
  const dir = base.includes("/") ? base.slice(0, base.lastIndexOf("/") + 1) : "";
  return (dir + href).split("/").reduce((a, p) => { if (p === "..") a.pop(); else if (p && p !== ".") a.push(p); return a; }, []).join("/");
}
// ---------- maths in the docs: a small TeX subset ($inline$, $$display$$) rendered to HTML, no external library ----------
// Only for documents with a display formula (a line starting with $$), so a stray $ elsewhere is never touched.
let mdMath = false;
const TEX_SYM = { alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", theta: "θ", lambda: "λ", mu: "μ", pi: "π", sigma: "σ",
  tau: "τ", phi: "φ", Sigma: "Σ", sum: "Σ", le: "≤", leq: "≤", ge: "≥", geq: "≥", cdot: "·", times: "×", sim: "∼", in: "∈",
  propto: "∝", leftarrow: "←", rightarrow: "→", to: "→", infty: "∞", approx: "≈", ne: "≠", pm: "±", top: "⊤", ldots: "…",
  lfloor: "⌊", rfloor: "⌋", ln: "ln", log: "log", exp: "exp", min: "min", max: "max", cos: "cos", sin: "sin",
  quad: "\u2003", qquad: "\u2003\u2003", ",": "\u2009", ";": "\u2005", " ": " ", "!": "", "{": "{", "}": "}", "|": "‖", "%": "%" };
function tex(s) {
  let i = 0;
  const skip = () => { while (s[i] === " ") i++; };
  const raw = () => {                       // the argument as plain text (\text, \mathrm)
    skip();
    if (s[i] !== "{") return esc(s[i++] || "");
    let d = 0, j = i;
    for (; j < s.length; j++) { if (s[j] === "{") d++; else if (s[j] === "}" && --d === 0) break; }
    const t = s.slice(i + 1, j); i = j + 1; return esc(t);
  };
  const arg = () => { skip(); if (s[i] === "{") { i++; return parse(true); } if (s[i] === "\\") return cmd(); return atom(s[i++] || ""); };
  const atom = (c) => (/[a-zA-Z]/.test(c) ? `<i>${c}</i>` : esc(c));
  function cmd() {
    i++;
    let name;
    if (/[a-zA-Z]/.test(s[i])) { let j = i; while (j < s.length && /[a-zA-Z]/.test(s[j])) j++; name = s.slice(i, j); i = j; } else name = s[i++];
    switch (name) {
      case "frac": case "tfrac": case "dfrac": { const a = arg(), b = arg(); return `<span class="tx-frac"><span>${a}</span><span>${b}</span></span>`; }
      case "sqrt": return `√<span class="tx-sqrt">${arg()}</span>`;
      case "mathbf": case "boldsymbol": return `<b class="tx-bf">${arg().replace(/<\/?i>/g, "")}</b>`;
      case "mathrm": case "text": case "operatorname": return `<span class="tx-rm">${raw()}</span>`;
      case "mathcal": return `<span class="tx-cal">${raw()}</span>`;
      case "overline": case "bar": return `<span class="tx-over">${arg()}</span>`;
      case "left": case "right": case "big": case "Big": case "bigg": case "Bigg": return "";
      default: return TEX_SYM[name] !== undefined ? TEX_SYM[name] : esc("\\" + name);
    }
  }
  function parse(inGroup) {
    let out = "";
    while (i < s.length) {
      const c = s[i];
      if (c === "}") { i++; if (inGroup) return out; continue; }
      if (c === "{") { i++; out += parse(true); continue; }
      if (c === "^") { i++; out += `<sup>${arg()}</sup>`; continue; }
      if (c === "_") { i++; out += `<sub>${arg()}</sub>`; continue; }
      if (c === "\\") { out += cmd(); continue; }
      out += atom(c); i++;
    }
    return out;
  }
  return parse(false);
}
function mdInline(t, base) {
  const maths = [];
  if (mdMath) t = t.replace(/\$([^$]+?)\$/g, (_, m) => { maths.push(m); return "\u0000" + (maths.length - 1) + "\u0000"; });
  t = esc(t);
  t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, "$1<i>$2</i>");
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => `<img class="md-img" loading="lazy" alt="${alt}" src="/api/docfile?path=${encodeURIComponent(resolveDoc(src.replace(/&amp;/g, "&"), base))}">`);
  t = t.replace(/&lt;br\s*\/?&gt;/g, "<br>");
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    href = href.replace(/&amp;/g, "&");
    if (/^https?:/.test(href)) return `<a href="${esc(href)}" target="_blank" rel="noopener">${label}</a>`;
    const norm = resolveDoc(href.split("#")[0], base);
    const d = (docs.list || []).find((x) => x.path === norm);
    return d ? `<a href="#/docs/${esc(d.id)}">${label}</a>` : label;
  });
  if (maths.length) t = t.replace(/\u0000(\d+)\u0000/g, (_, k) => `<span class="tx">${tex(maths[+k])}</span>`);
  return t;
}
function md(src, base) {
  src = src.replace(/<img\s[^>]*?src="([^"]+)"[^>]*?alt="([^"]*)"[^>]*>/g, "![$2]($1)").replace(/<\/?p[^>]*>/g, "");   // the few HTML tags of the READMEs
  mdMath = /^\s*\$\$/m.test(src);
  const lines = src.replace(/\r/g, "").split("\n"), out = [];
  let i = 0, para = [];
  const flush = () => { if (para.length) { out.push(`<p>${mdInline(para.join(" "), base)}</p>`); para = []; } };
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { flush(); const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push(`<pre>${esc(buf.join("\n"))}</pre>`); continue; }
    const dm = mdMath && /^\s*\$\$(.+)\$\$\s*$/.exec(l);
    if (dm) { flush(); out.push(`<div class="tx tx-display">${tex(dm[1])}</div>`); i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) { flush(); const n = h[1].length; out.push(`<h${n} id="${esc(h[2].toLowerCase().replace(/[^a-z0-9]+/g, "-"))}">${mdInline(h[2], base)}</h${n}>`); i++; continue; }
    if (/^\s*---+\s*$/.test(l)) { flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush(); const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<div class="tbl-wrap"><table class="md">${head.some((c) => c) ? `<thead><tr>${head.map((c) => `<th>${mdInline(c, base)}</th>`).join("")}</tr></thead>` : ""}<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${mdInline(c, base)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*>/.test(l)) { flush(); const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, "")); out.push(`<blockquote>${mdInline(buf.join(" "), base)}</blockquote>`); continue; }
    const li = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(l);
    if (li) {
      flush(); const ordered = /\d/.test(li[2]), items = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (m) { items.push({ depth: Math.min(3, Math.floor(m[1].length / 2)), text: m[3] }); i++; }
        else if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1].text += " " + lines[i].trim(); i++; }
        else break;
      }
      out.push(`<${ordered ? "ol" : "ul"} class="md">${items.map((it) => `<li style="margin-left:${it.depth * 18}px">${mdInline(it.text.replace(/^\[ \]/, "☐").replace(/^\[x\]/i, "☑"), base)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l.trim()); i++;
  }
  flush();
  return out.join("\n");
}
// ---------- RANKING: the Elo ranking of every team of every league (lab/ladder.py) ----------
const LEAGUES = [["all", "All"], ["rules", "Rule Based"], ["rl", "Reinforcement Learning"], ["ml", "Machine Learning"], ["dl", "Deep Learning"]];
const LEAGUE_COLOR = { rules: "--c5", rl: "--c1", ml: "--c3", dl: "--c4" };
const rk = { data: null, t: 0, league: "all" };
function loadRanking(force) {
  if (pending._rk || (!force && rk.data && Date.now() - rk.t < POLL_MS)) return;
  pending._rk = true;
  getJSON("/api/ranking").then((d) => { rk.data = d; rk.t = Date.now(); render(); })
    .catch(() => { rk.data = { error: true }; rk.t = Date.now(); render(); }).finally(() => { delete pending._rk; });
}
const LEAGUE_SHORT = { rules: "Rules", rl: "RL", ml: "ML", dl: "DL" };
const leagueChip = (lg) => `<span class="chip" title="${esc((LEAGUES.find((l) => l[0] === lg) || [lg, lg])[1])} League" style="border-color:${css(LEAGUE_COLOR[lg] || "--muted")};color:${css(LEAGUE_COLOR[lg] || "--muted")}">${esc(LEAGUE_SHORT[lg] || lg)}</span>`;
function viewRanking() {
  loadRanking();
  const d = rk.data;
  if (!d) return '<div class="empty">Loading…</div>';
  if (d.error) return '<div class="empty">The ranking could not be computed (see the web app\'s log).</div>';
  const head = `<div class="head"><div><h1>Ranking</h1><p>One Elo rating for every team of every league, from matches between them (5v5 on the arena, 90 s, every pair from both sides with the same seed). 1500 is the middle; 400 points more means 10:1 odds. The bar is the 95% interval. New teams play ${6} placement games first.</p></div>
    <div class="pills">${LEAGUES.map(([k, l]) => { const n = k === "all" ? d.rows.length : d.rows.filter((r) => r.league === k).length; return n || k === "all" ? `<button class="pill ${rk.league === k ? "on" : ""}" data-league="${k}">${esc(l)} <span class="muted">${n}</span></button>` : ""; }).join("")}</div></div>`;
  const rows = d.rows.filter((r) => rk.league === "all" || r.league === rk.league);
  const played = d.rows.filter((r) => r.games), lead = played[0];
  const kpis = `<div class="kpis">${kpi("Matches", d.matches.toLocaleString(), d.stale ? `${d.stale} no longer count (a file changed)` : "all count")}${kpi("Teams ranked", `${played.length}<small>/ ${d.rows.length}</small>`, `${d.rows.filter((r) => r.placed).length} placed`)}${kpi("Top", lead ? esc(lead.name) : "–", lead ? `${f(lead.elo, 0)} · ${esc(lead.league)}` : "")}${kpi("Last match", d.last ? ago(d.last) : "–", d.off ? "ladder off (exp/ladder_off)" : "the Pi plays rounds when the queue is empty")}</div>`;
  if (!d.matches) return head + kpis + '<div class="card"><h2>No matches yet</h2><p class="muted">Run <span class="mono">python3 lab/ladder.py round</span>, or wait for the runner: it plays a round whenever the queue is empty.</p></div>';
  const lo = Math.min(...rows.map((r) => r.lo)), hi = Math.max(...rows.map((r) => r.hi)), W = 200;
  const X = (v) => 6 + ((v - lo) / (hi - lo || 1)) * (W - 12);
  const axis = niceTicks(lo, hi, 5);
  const bar = (r) => `<svg width="${W}" height="16" viewBox="0 0 ${W} 16" class="rkbar">${axis.map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="0" y2="16" stroke="var(--grid)"/>`).join("")}<line x1="${X(r.lo)}" x2="${X(r.hi)}" y1="8" y2="8" stroke="${css(LEAGUE_COLOR[r.league] || "--muted")}" stroke-width="3" stroke-linecap="round" opacity="${r.placed ? 0.55 : 0.25}"/><circle cx="${X(r.elo)}" cy="8" r="4.5" fill="${css(LEAGUE_COLOR[r.league] || "--muted")}" opacity="${r.placed ? 1 : 0.5}"><title>${f(r.lo, 0)} – ${f(r.hi, 0)}</title></circle></svg>`;
  const body = rows.map((r) => `<tr class="${r.placed ? "" : "dim"}"><td class="r muted">${r.rank}</td><td title="${esc(r.kind === "rules" ? "handmade AI" : r.model || "")}"><b>${esc(r.name)}</b>${r.kind === "net" ? ' <span class="muted small">checkpoint</span>' : ""}</td><td>${leagueChip(r.league)}</td>
    <td class="r"><b>${f(r.elo, 0)}</b><span class="pm">±${f(1.96 * r.se, 0)}</span></td><td>${bar(r)}</td><td class="r">${r.games}${r.placed ? "" : ' <span class="small muted">placing</span>'}</td>
    <td class="r nowrap">${r.w}–${r.d}–${r.l}</td><td class="r">${r.pts == null ? "–" : f(r.pts, 2)}</td><td class="r">${r.games ? sgn((r.gf - r.ga) / r.games, 2) : "–"}</td></tr>`).join("");
  const table = `<section class="card flush"><div class="tbl-wrap"><table class="rank"><thead><tr><th class="r">#</th><th>Team</th><th>League</th><th class="r">Elo</th><th><span class="small muted">${f(lo, 0)} … ${f(hi, 0)}</span></th><th class="r">Games</th><th class="r">W–D–L</th><th class="r">Pts / game</th><th class="r">GD / game</th></tr></thead><tbody>${body}</tbody></table></div></section>`;
  // history: the rating after each round, for the top teams of the filter
  const top = rows.filter((r) => r.games).slice(0, 8);
  const series = top.map((r, i) => ({ name: r.name, color: css(PALETTE[i % PALETTE.length]), points: d.history.filter((h) => h.elo[r.id] != null).map((h) => ({ x: parseT(h.t), y: h.elo[r.id] })) }));
  const hist = `<section class="card"><div class="card-h"><h2>Rating history</h2><span class="muted small">top ${top.length} of the list above, after every round</span></div>${lineChart(series, { height: 220, time: true, key: "rkh", fmt: (v) => f(v, 0), emptyText: "the history starts with the next round" })}</section>`;
  const name = Object.fromEntries(d.rows.map((r) => [r.id, r.name]));
  const recent = d.recent.slice(-15).reverse().map((m) => `<tr><td class="muted small nowrap">${esc(ago(m.t))}</td><td class="r">${esc(name[m.a] || m.a)}</td><td class="r"><b>${m.ga}–${m.gb}</b></td><td>${esc(name[m.b] || m.b)}</td></tr>`).join("");
  const rec = `<section class="card flush"><div class="card-h pad"><h2>Latest matches</h2><span class="muted small">left team's goals first</span></div><div class="tbl-wrap"><table class="mini"><tbody>${recent}</tbody></table></div></section>`;
  return head + kpis + table + `<div class="grid g2">${hist}${rec}</div>`;
}

// ---------- DATASET: the user's recorded play (data/human/, game/recorder.py), analysed by il/analysis.py ----------
const MOVE_NAMES = ["stand", "up", "up + forward", "forward", "down + forward", "down", "down + back", "back", "up + back"];
const MOVE_VEC = [[0, 0], [0, -1], [0.707, -0.707], [1, 0], [0.707, 0.707], [0, 1], [-0.707, 0.707], [-1, 0], [-0.707, -0.707]];
const ds = { data: null, t: 0, replay: null };
function loadDataset(force) {
  if (pending._ds || (!force && ds.data && Date.now() - ds.t < POLL_MS)) return;
  pending._ds = true;
  getJSON("/api/dataset").then((d) => { ds.data = d; ds.t = Date.now(); render(); })
    .catch(() => { ds.data = { error: true }; ds.t = Date.now(); render(); }).finally(() => { delete pending._ds; });
}
// the 9 moves as a radar in the player's own frame (right = towards the opponent goal): an octagon whose corners sit at each
// direction's share of the decisions (rings at 25 / 50 / 75 / 100% of the most used direction); the centre dot = standing still
function compass(moves, color, size = 220, labels = true) {
  const c = size / 2, R = c - (labels ? 34 : 4), mx = Math.max(...moves.slice(1), 1), pt = (i, r) => [c + MOVE_VEC[i][0] * r, c + MOVE_VEC[i][1] * r];
  const ring = (k) => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => pt(i, R * k).map((v) => v.toFixed(1)).join(",")).join(" ");
  let g = "";
  for (const k of [0.25, 0.5, 0.75, 1]) g += `<polygon points="${ring(k)}" fill="${k === 1 ? "var(--panel-2)" : "none"}" stroke="var(--line)" stroke-width="1"/>`;
  for (let i = 1; i < 9; i++) { const [x, y] = pt(i, R); g += `<line x1="${c}" y1="${c}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--line)"/>`; }
  const shape = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => pt(i, R * Math.max(0.04, moves[i] / mx)).map((v) => v.toFixed(1)).join(",")).join(" ");
  g += `<polygon points="${shape}" fill="${color}" fill-opacity=".35" stroke="${color}" stroke-width="${labels ? 2.5 : 1.5}" stroke-linejoin="round"/>`;
  for (let i = 1; i < 9; i++) {
    const [x, y] = pt(i, R * Math.max(0.04, moves[i] / mx));
    if (labels) g += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="${color}"><title>${MOVE_NAMES[i]}: ${f(moves[i], 1)}%</title></circle>`;
    if (labels) { const [lx, ly] = pt(i, R + 18); g += `<text x="${lx.toFixed(1)}" y="${(ly + 4).toFixed(1)}" text-anchor="middle" class="ax">${f(moves[i], 0)}%</text>`; }
  }
  g += `<circle cx="${c}" cy="${c}" r="${(labels ? 3 : 2) + (labels ? 12 : 6) * Math.sqrt(moves[0] / 100)}" fill="var(--panel)" stroke="${color}" stroke-width="1.5"><title>stand: ${f(moves[0], 1)}%</title></circle>`;
  if (labels) g += `<text x="${size - 2}" y="${size - 4}" text-anchor="end" class="ax">→ goal</text>`;
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="max-width:100%">${g}</svg>`;
}
function vsBar(label, v, net, rules, dec, unit = "") {
  const mx = Math.max(v || 0, net || 0, rules || 0) * 1.12 || 1, col = css("--c3");
  const tick = (x, name, cl) => (x == null ? "" : `<span class="rf" style="left:${(100 * x) / mx}%;background:${cl}" title="${name} ${f(x, dec)}${unit}"></span>`);
  return `<div class="bh vs"><div class="bl">${label}</div><div class="bt"><i style="width:${(100 * (v || 0)) / mx}%;background:${col}"></i>${tick(net, "net", "var(--c2)")}${tick(rules, "rule bots", "var(--ink)")}</div>
    <div class="bv"><b>${f(v, dec)}</b>${unit}<span class="pm"> net ${f(net, dec)} · rules ${f(rules, dec)}</span></div></div>`;
}
function viewDataset(id) {
  if (id) return viewReplay(id);
  loadDataset();
  const d = ds.data;
  if (!d) return '<div class="empty">Loading…</div>';
  if (d.error) return '<div class="empty">The dataset could not be read (see the web app\'s log).</div>';
  const head = `<div class="head"><div><h1>Dataset</h1><p>Your play, recorded in the Game with "Record my play" on: every decision (30 per second) of the player you control, as the nets see it. This is what the ML and DL leagues will learn from. Files: <span class="mono">${esc(d.folder)}/</span></p></div></div>`;
  if (d.empty) return head + `<div class="card"><h2>Nothing recorded yet</h2><p class="muted">Play a match in the Game (Quick Match or a tournament) with <b>Dataset: Record my play</b>. It is saved at the final whistle, or when you quit after 10 s of play.</p></div>`;
  const b = d.behaviour, ref = d.reference || {}, net = ref.net || {}, rules = ref.rules || {}, rec = d.record;
  const mins = (k) => d.minutes_by[k] || 0;
  const kpis = `<div class="kpis">${kpi("Matches", `${d.files}`, `${rec.W}W ${rec.D}D ${rec.L}L${rec.left ? ` · ${rec.left} left early` : ""}`)}${kpi("Play recorded", `${f(d.minutes, 1)}<small>min</small>`, `${d.rows.toLocaleString()} decisions`)}${kpi("Goals", `${d.goals[0]}<small>–</small>${d.goals[1]}`, "for – against, finished matches")}${kpi("Direction changes", `${f(b.dir_changes_s, 1)}<small>/ s</small>`, `net ${f(net.dir_changes_s, 1)} · rules ${f(rules.dir_changes_s, 1)}`)}${kpi("Kick presses", `${f(b.kick_presses_s * 60, 1)}<small>/ min</small>`, `kick held ${f(b.kick_held_pct, 1)}% of the time`)}${kpi("One player / whole team", `${f(mins("control:single"), 1)}<small>min</small> · ${f(mins("control:team"), 1)}<small>min</small>`, "minutes of each control mode")}</div>`;
  const behaviour = `<section class="card"><div class="card-h"><h2>How you move</h2><span class="muted small">your player's frame · → = towards the opponent goal</span></div>
    <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap"><div>${compass(d.moves, css("--c3"))}</div><div style="flex:1;min-width:220px">
      <dl class="kv"><dt>180° turns / s</dt><dd>${f(b.turn180_s, 2)}</dd><dt>Kick held</dt><dd>${f(b.kick_held_pct, 1)}%</dd><dt>Moving towards the ball</dt><dd>${f(b.toward_ball_pct, 0)}% of moving decisions</dd><dt>Nearest team to the ball</dt><dd>yours ${f(d.phase.ours_pct, 0)}% of the time</dd><dt>Ball in your half</dt><dd>${f(d.phase.ball_own_half_pct, 0)}%</dd></dl></div></div>
      <div style="margin-top:12px">${vsBar("Direction changes / s", b.dir_changes_s, net.dir_changes_s, rules.dir_changes_s, 1)}${vsBar("Standing still %", b.idle_pct, net.idle_pct, rules.idle_pct, 0)}
      <p class="muted small">Ticks: <i class="lgd" style="background:var(--c2)"></i>net ${esc(ref.run || "–")}${ref.update != null ? " u" + ref.update : ""} · <i class="lgd" style="background:var(--ink)"></i>the rule bots it played (newest full evaluation, same definitions).</p></div></section>`;
  const where = `<section class="card"><div class="card-h"><h2>Where</h2><span class="muted small">share of time · you always attack right</span></div><div class="heats">${heatmap({ ...d.heat.player, role: "-" }, "Your player")}${heatmap({ ...d.heat.ball, role: "-" }, "The ball")}${heatmap({ ...d.heat.kicks, role: "-" }, `Your kicks (${d.heat.kicks.n})`)}</div><div class="hlegend"><span>rare</span><i></i><span>often</span></div></section>`;
  const secs = (n) => (n >= 1800 ? f(n / 1800, 1) + " min" : Math.round(n / 30) + " s");
  const distRows = d.distance.map((x) => `<div class="bh"><div class="bl">${esc(x.label)}</div><div class="bt"><i style="width:${x.pct}%;background:var(--c1)"></i></div><div class="bv">${f(x.pct, 0)}%</div></div>`).join("");
  const rankRows = d.ranks.map((r) => `<tr class="${r.rows < 1800 ? "thin" : ""}"><td>${esc(r.label)}</td><td class="r">${f(r.pct, 0)}%</td><td class="r">${secs(r.ours_rows)}</td><td class="r">${secs(r.theirs_rows)}</td><td class="r">${r.rows ? f(r.toward_pct, 0) + "%" : "–"}</td><td class="r">${r.rows ? f(r.idle_pct, 0) + "%" : "–"}</td><td class="r">${r.rows ? f(r.dist_px, 0) : "–"}</td></tr>`).join("");
  const coverage = `<section class="card flush"><div class="card-h pad"><h2>Coverage: which situations you have played</h2><span class="muted small">no fixed roles: the net must learn the role from the situation, so it needs examples of each</span></div>
    <div class="pad" style="padding:4px 16px 0">${distRows}</div>
    <div class="tbl-wrap"><table class="mini"><thead><tr><th>Your depth among your 5 (keeper counts)</th><th class="r">time</th><th class="r" title="time with your team nearest the ball">yours</th><th class="r" title="time with theirs nearest the ball">theirs</th><th class="r">to ball</th><th class="r">still</th><th class="r">dist px</th></tr></thead><tbody>${rankRows}</tbody></table></div>
    ${d.thin.length ? `<p class="small pad" style="padding:8px 16px 14px"><b>Under a minute of examples:</b> ${d.thin.map(esc).join(" · ")}. Play these (e.g. one player as a defender or the keeper) so the models see them.</p>` : `<p class="muted small pad" style="padding:8px 16px 14px">Every situation has at least a minute of examples.</p>`}</section>`;
  const sit = d.situations.map((s) => `<tr><td>${esc(s.label)}</td><td class="r">${secs(s.rows)}</td><td>${s.rows ? compass(s.moves, css("--c3"), 64, false) : '<span class="muted">none</span>'}</td><td class="r">${s.rows ? f(s.toward_pct, 0) + "%" : "–"}</td><td class="r">${s.rows ? f(s.idle_pct, 0) + "%" : "–"}</td></tr>`).join("");
  const situations = `<section class="card flush"><div class="card-h pad"><h2>What you do, by situation</h2><span class="muted small">"possession" = your team has the player nearest the ball</span></div><div class="tbl-wrap"><table class="mini"><thead><tr><th>Situation</th><th class="r">time</th><th>moves (→ goal)</th><th class="r">towards ball</th><th class="r">standing</th></tr></thead><tbody>${sit}</tbody></table></div></section>`;
  const oc = { W: "pos", L: "neg", D: "", left: "muted" };
  // puzzle rounds (game: Puzzle) are grouped by session: one row per session, its rounds in a fold-out
  const groups = [];
  for (const m of d.matches) {
    const g = m.puzzle && m.session ? groups.find((x) => x.session === m.session) : null;
    if (g) g.rounds.push(m); else groups.push(m.puzzle && m.session ? { session: m.session, rounds: [m], started: m.started } : m);
  }
  const roundLine = (m) => `<a href="#/dataset/${encodeURIComponent(m.id)}">${m.round || "?"}: ${esc(m.team.name)} ${m.gf}–${m.ga} ${esc(m.opponent.name)}</a>`;
  const sessionRow = (g) => { const R = g.rounds, cnt = (o) => R.filter((r) => r.outcome === o).length, mins = R.reduce((s, r) => s + r.minutes, 0), pts = 3 * cnt("W") + cnt("D");
    return `<tr><td class="nowrap">${esc(new Date(g.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))}</td><td><b>Puzzle</b> <span class="muted">${R.length} rounds, random teams</span>
      <details><summary class="small muted">rounds</summary><div class="small" style="display:grid;gap:2px">${R.map(roundLine).join("")}</div></details></td>
      <td class="r"><b>${pts} pts</b> <span class="small">${cnt("W")}W ${cnt("D")}D ${cnt("L")}L</span></td><td>${esc(R[0].control)} <span class="muted small">${esc([...new Set(R.flatMap((r) => Object.keys(r.roles)))].join(" "))}</span></td>
      <td class="r">${f(mins, 1)}</td><td class="r">${f(R.reduce((s, r) => s + r.dir_changes_s * r.minutes, 0) / mins, 1)}</td><td class="r">${f(R.reduce((s, r) => s + r.kick_presses_min * r.minutes, 0) / mins, 1)}</td>
      <td class="r">${f(R.reduce((s, r) => s + r.on_ball_pct * r.minutes, 0) / mins, 0)}%</td><td></td></tr>`; };
  const rows = groups.slice().reverse().map((m) => m.rounds ? sessionRow(m) : m.error ? `<tr><td colspan="9" class="neg">${esc(m.id)}: ${esc(m.error)}</td></tr>` :
    `<tr><td class="nowrap">${esc(new Date(m.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))}</td><td>${esc(m.team.name)} <span class="muted">vs</span> ${esc(m.opponent.name)} <span class="muted small">${esc(m.opponent.league)}</span></td>
     <td class="r"><b class="${oc[m.outcome]}">${m.gf}–${m.ga}${m.shootout?.length ? ` (p ${m.shootout.join("–")})` : ""}</b> <span class="small ${oc[m.outcome]}">${m.outcome === "left" ? "left early" : m.outcome}</span></td>
     <td>${esc(m.control)}${m.picked ? ` · ${esc(m.picked)}` : ""} <span class="muted small">${esc(Object.keys(m.roles).join(" "))}</span></td><td class="r">${f(m.minutes, 1)}</td><td class="r">${f(m.dir_changes_s, 1)}</td><td class="r">${f(m.kick_presses_min, 1)}</td><td class="r">${f(m.on_ball_pct, 0)}%</td><td><a href="#/dataset/${encodeURIComponent(m.id)}">replay ▶</a></td></tr>`).join("");
  const table = `<section class="card flush"><div class="card-h pad"><h2>Recorded matches</h2><span class="muted small">newest first</span></div><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Match</th><th class="r">Score</th><th>Control · roles played</th><th class="r">min</th><th class="r">changes/s</th><th class="r">kicks/min</th><th class="r">on ball</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  return head + kpis + `<div class="grid g2">${behaviour}${where}</div>` + `<div class="grid g2">${coverage}${situations}</div>` + table;
}

// ---------- replay of one recorded match (drawn from the stored states; the arrow is your key direction) ----------
function viewReplay(id) {
  return `<div class="head"><div><h1><a class="rl" href="#/dataset">Dataset</a> · replay</h1><p class="mono small">${esc(id)}</p></div></div>
    <section class="card"><canvas id="rp-cv" style="width:100%;display:block;border-radius:8px;background:var(--panel-2)"></canvas>
    <div class="rp-ctl" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px">
      <button class="pill" id="rp-play">⏸ pause</button><span class="pills" style="margin:0">${[0.5, 1, 2, 4].map((s) => `<button class="pill${s === 1 ? " on" : ""}" data-rpspeed="${s}">${s}×</button>`).join("")}</span>
      <input type="range" id="rp-seek" min="0" max="0" value="0" style="flex:1;min-width:200px"><span id="rp-info" class="mono small"></span></div>
    <p class="muted small" style="margin-top:6px">Ringed: the player you controlled. Arrow: the direction you held at that decision (none = standing); the ring turns red while you hold kick. Space = play / pause, ← → = 1 s.</p></section>`;
}
function startReplay(id) {
  stopReplay();
  const R = ds.replay = { id, d: null, i: 0, playing: true, speed: 1, last: 0, raf: 0 };
  getJSON("/api/dataset/match/" + encodeURIComponent(id)).then((d) => {
    if (ds.replay !== R) return;
    R.d = d; const seek = $("#rp-seek"); if (seek) seek.max = d.tick.length - 1;
    R.raf = requestAnimationFrame((t) => replayFrame(R, t));
  }).catch(() => { const i = $("#rp-info"); if (i) i.textContent = "this match could not be loaded"; });
}
function stopReplay() { if (ds.replay) cancelAnimationFrame(ds.replay.raf); ds.replay = null; }
function replayFrame(R, ts) {
  if (ds.replay !== R) return;
  R.raf = requestAnimationFrame((t) => replayFrame(R, t));
  const d = R.d, n = d.tick.length, dt = R.last ? Math.min(0.1, (ts - R.last) / 1000) : 0;
  R.last = ts;
  if (R.playing) { R.i += dt * 30 * R.speed; if (R.i >= n - 1) { R.i = n - 1; R.playing = false; } }
  const i = Math.max(0, Math.min(n - 1, Math.floor(R.i)));
  const cv = $("#rp-cv"); if (!cv) return;
  const pd = d.meta.pitch, W = cv.clientWidth, H = Math.round(W * (pd.out_y / pd.out_x));
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px"; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const s = W / (2 * pd.out_x), X = (x) => W / 2 + x * s, Y = (y) => H / 2 + y * s;
  ctx.fillStyle = "#5f7d4c"; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#6f8f5a"; ctx.fillRect(X(-pd.half_w), Y(-pd.half_h), 2 * pd.half_w * s, 2 * pd.half_h * s);
  ctx.strokeStyle = "rgba(230,245,225,.8)"; ctx.lineWidth = 2;
  ctx.strokeRect(X(-pd.half_w), Y(-pd.half_h), 2 * pd.half_w * s, 2 * pd.half_h * s);
  ctx.beginPath(); ctx.moveTo(X(0), Y(-pd.half_h)); ctx.lineTo(X(0), Y(pd.half_h)); ctx.stroke();
  ctx.beginPath(); ctx.arc(X(0), Y(0), 80 * s, 0, 2 * Math.PI); ctx.stroke();
  ctx.lineWidth = 4; ctx.strokeStyle = "#fff";
  for (const gx of [-pd.half_w, pd.half_w]) { ctx.beginPath(); ctx.moveTo(X(gx), Y(-pd.goal_half)); ctx.lineTo(X(gx), Y(pd.goal_half)); ctx.stroke(); }
  const P = d.p[i], ctrl = d.ctrl[i];
  d.meta.players.forEach((pl, k) => {
    const x = X(P[2 * k]), y = Y(P[2 * k + 1]), me = pl.uid === ctrl;
    disc(ctx, x, y, 15 * s, d.colors[pl.team], "rgba(0,0,0,.6)", 1.5);
    if (me) { ctx.beginPath(); ctx.arc(x, y, 15 * s + 5, 0, 2 * Math.PI); ctx.lineWidth = 3; ctx.strokeStyle = d.kick[i] ? "#ef6a5b" : "#fff"; ctx.stroke(); }
    if (me && d.move[i] > 0) {
      const [vx, vy] = MOVE_VEC[d.move[i]], ax = vx * d.attack, L = 34 + 15 * s;
      const ex = x + ax * L, ey = y + vy * L, a = Math.atan2(vy, ax);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x + ax * (15 * s + 6), y + vy * (15 * s + 6)); ctx.lineTo(ex, ey); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.moveTo(ex + Math.cos(a) * 8, ey + Math.sin(a) * 8); ctx.lineTo(ex + Math.cos(a + 2.5) * 9, ey + Math.sin(a + 2.5) * 9); ctx.lineTo(ex + Math.cos(a - 2.5) * 9, ey + Math.sin(a - 2.5) * 9); ctx.fill();
    }
  });
  disc(ctx, X(d.b[i][0]), Y(d.b[i][1]), 10 * s, "#fff", "#000", 1.5);
  const sc = d.score[i], tl = d.time_left[i], tm = d.meta.teams;
  ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(0, 0, W, 28);
  ctx.fillStyle = "#fff"; ctx.font = "600 14px system-ui, sans-serif"; ctx.textAlign = "center";
  ctx.fillText(`${tm[0].name}  ${sc[0]} – ${sc[1]}  ${tm[1].name}     ${clockText(tl)}`, W / 2, 19);
  const seek = $("#rp-seek"); if (seek && document.activeElement !== seek) seek.value = i;
  const info = $("#rp-info"); if (info) info.textContent = `${i + 1} / ${n} · ${MOVE_NAMES[d.move[i]]}${d.kick[i] ? " + kick" : ""}`;
  const pb = $("#rp-play"); if (pb) pb.textContent = R.playing ? "⏸ pause" : "▶ play";
}

function viewDocs(id) {
  if (docs.list === null) { loadDocs(""); return '<div class="empty">Loading…</div>'; }
  const groups = {};
  for (const d of docs.list) (groups[d.group] = groups[d.group] || []).push(d);
  const side = Object.entries(groups).map(([g, ds]) => `<div class="doc-g">${esc(g)}</div>${ds.map((d) => `<a class="doc-l${d.id === id ? " on" : ""}" href="#/docs/${esc(d.id)}">${esc(d.title)}<small>${esc(d.path)}</small></a>`).join("")}`).join("");
  let body;
  if (!id) body = `<div class="card"><h2>Docs</h2><p class="muted">The project's notes, read from the repository on the Pi: the lab notebook, the reward register, how to run experiments and how the game works.</p><div class="doc-cards">${docs.list.map((d) => `<a class="doc-card" href="#/docs/${esc(d.id)}"><b>${esc(d.title)}</b><span class="muted small">${esc(d.path)} · updated ${esc(ago(d.updated))}</span></a>`).join("")}</div></div>`;
  else {
    const d = docs.list.find((x) => x.id === id);
    if (!d) body = '<div class="empty">Unknown document.</div>';
    else if (docs.text[id] === undefined) { loadDocs(id); body = '<div class="empty">Loading…</div>'; }
    else if (docs.text[id] === null) body = '<div class="empty">Could not load this document.</div>';
    else body = `<article class="card doc-body"><div class="muted small">${esc(d.path)} · updated ${esc(ago(d.updated))}</div>${md(docs.text[id], d.path)}</article>`;
  }
  return `<div class="docs-wrap"><nav class="doc-side">${side}</nav><div class="doc-main">${body}</div></div>`;
}
function viewPi() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  if (!state.health || state.health.hours !== state.piHours) loadHealth();
  const pi = o.status.pi, th = throttle(pi.throttled), H = state.health;
  const rows = (H?.rows || []).filter((r) => r.t && r.t.includes("T"));
  const vl = (H?.reboots || []).map((r) => ({ x: parseT(r.back), label: "reboot (last seen " + r.last_seen.slice(11, 16) + ")" }));
  const mk = (k) => rows.map((r) => ({ x: parseT(r.t), y: r[k] }));
  const opt = { height: 180, time: true, vlines: vl, gap: 120 };
  const win = [3, 12, 48].map((h) => `<button class="pill ${state.piHours === h ? "on" : ""}" data-hours="${h}">${h} h</button>`).join("");
  const last = rows[rows.length - 1];
  return `<div class="head"><div><h1>Raspberry Pi</h1><p>One sample every 10 s (<span class="mono">logs/pi_health.log</span>). Red lines mark reboots; the last sample before one shows what the Pi was doing.</p></div><div class="pills">${win}</div></div>
    <div class="kpis">${kpi("Temperature", `${f(pi.temp_c, 1)}<small>°C</small>`)}${kpi("CPU load", `${f(pi.load_1m, 1)}<small>/ 4</small>`)}${kpi("Free memory", `${f(pi.mem_free_mb / 1024, 2)}<small>GB</small>`)}${kpi("Power", esc(th.text), esc(th.sub || ""), th.cls)}${kpi("Uptime", dur(pi.uptime_hours * 3600), "boot " + esc(pi.boot_id || ""))}${kpi("Last sample", last ? ago(last.t) : "–", "watchdog: reboot after 15 s frozen")}</div>
    <div class="grid g2">
      <section class="card"><div class="card-h"><h3>Temperature °C</h3></div>${lineChart([{ name: "temperature", color: css("--c2"), points: mk("temp") }], { ...opt, refs: [{ y: 80, label: "throttles at 80" }], key: "pt", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU load (1 min)</h3></div>${lineChart([{ name: "load", color: css("--c1"), points: mk("load") }], { ...opt, yMin: 0, refs: [{ y: 4, label: "4 cores" }], key: "pl", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>Free memory MB</h3></div>${lineChart([{ name: "free", color: css("--c3"), points: mk("mem_mb") }], { ...opt, yMin: 0, key: "pm", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU clock MHz</h3></div>${lineChart([{ name: "clock", color: css("--c4"), points: mk("clock_mhz") }], { ...opt, yMin: 0, key: "pc", emptyText: "no dated samples yet" })}</section>
    </div>`;
}

// ---------- LIVE (streamed from the Pi's match, drawn here) ----------
const FS_ICON = [   // enter / leave full screen, drawn (the Pi's fonts have no such symbols)
  '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>'];
const live = { mode: "match", es: null, meta: null, frames: [], trail: [], raf: 0, recv: [], lastFrameAt: 0, sideAt: 0, cam: null,
  follow: (() => { try { return localStorage.getItem("liveFollow") !== "0"; } catch (e) { return true; } })() };
function viewLive() {
  return `<div class="live-wrap">
      <div class="live-main"><div class="scorebar" id="lv-sb"><div class="tm"><i class="kit"></i><span>–</span></div><div class="mid"><div class="score">– : –</div><div class="clock">–</div></div><div class="tm r"><span>–</span><i class="kit"></i></div></div>
        <canvas id="lv-c" width="1400" height="710"></canvas><div class="lv-over" id="lv-over">Waiting for the Pi's match…</div>
        <button class="ctl-btn" data-ctl title="Controls" aria-label="Controls">⚙</button>
        <button class="fs-btn" data-fs title="Full screen" aria-label="Full screen">${FS_ICON[document.body.classList.contains("live-fs") ? 1 : 0]}</button></div>
      <div class="card live-side"><button class="ctl-close" data-ctl aria-label="Close controls">✕ Close</button><div id="lv-prog"></div><div class="seg" id="lv-mode" title="Puzzle: random layout of every player and the ball, 60 s, over at the first goal"><button data-mode="match">Match</button><button data-mode="puzzle">Puzzle</button></div><div class="seg" id="lv-cam"><button data-cam="1">Follow ball</button><button data-cam="0">Whole pitch</button></div>
        <label class="lv-opp">Opponent <select id="lv-opp" aria-label="Opponent of the next match"><option>…</option></select></label>
        <details class="lv-more"><summary>Details</summary><dl class="kv" id="lv-side"></dl></details></div>
    </div>`;
}
function startLive() {
  if (!live.es) {
    live.es = new EventSource("/api/live");
    live.es.addEventListener("meta", (e) => { live.meta = JSON.parse(e.data); liveSide(); });
    live.es.onmessage = (e) => {
      const fr = JSON.parse(e.data), now = performance.now();
      fr.at = now;
      const last = live.frames[live.frames.length - 1];
      if (last && (last.id !== fr.id || fr.t < last.t)) { live.frames = []; live.trail = []; }
      live.frames.push(fr);
      if (live.frames.length > 12) live.frames.shift();
      live.recv.push(now);
      while (live.recv.length && now - live.recv[0] > 2000) live.recv.shift();
      live.lastFrameAt = now;
    };
  }
  if (!live.raf) live.raf = requestAnimationFrame(liveDraw);
  liveSide();
}
function stopLive() {
  if (live.es) { live.es.close(); live.es = null; }
  if (live.raf) { cancelAnimationFrame(live.raf); live.raf = 0; }
  live.frames = []; live.trail = []; live.cam = null;
}
function clockText(s) { s = Math.max(0, Math.ceil(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
// the opponent of the demo match: "random" (default) draws a handmade team or an earlier run for every match; a pinned choice applies from the next match
async function loadOpponents() {
  const sel = $("#lv-opp"); if (!sel) return;
  try {
    const d = await (await fetch("/api/live/opponents")).json(), groups = {};
    live.mode = d.mode || "match"; liveSide();
    for (const o of d.opponents) (groups[o.group] = groups[o.group] || []).push(o);
    sel.innerHTML = Object.entries(groups).map(([g, os]) => `<optgroup label="${esc(g)}">${os.map((o) => `<option value="${esc(o.id)}"${o.id === d.selected ? " selected" : ""}>${esc(o.label)}${o.tier ? " · " + esc(o.tier) : ""}</option>`).join("")}</optgroup>`).join("");
  } catch (e) { sel.innerHTML = "<option>unavailable</option>"; }
}
document.addEventListener("change", async (e) => {
  if (e.target.id !== "lv-opp") return;
  try { await fetch("/api/live/opponent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: e.target.value }) }); } catch (err) {}
});
function liveSide() {
  const run = state.ov?.status?.runner?.running, pr = $("#lv-prog");
  if (pr) pr.innerHTML = run ? `<div class="big3"><div><b>${run.update ?? 0}<small>/${run.target ?? "?"}</small></b><span>${esc(run.run)}</span></div>
      <div><b>${run.eta_hours != null ? dur(run.eta_hours * 3600) : "–"}</b><span>${run.evaluating ? "evaluating…" : "training left"}</span></div>
      <div><b>${f(run.train_pts_vs_rules)}</b><span>training pts</span></div></div><div class="progress"><i style="width:${run.target ? Math.min(100, (100 * (run.update || 0)) / run.target) : 0}%"></i></div>` : '<div class="muted">nothing training</div>';
  for (const bt of document.querySelectorAll("#lv-mode button")) bt.classList.toggle("on", bt.dataset.mode === live.mode);
  for (const bt of document.querySelectorAll("#lv-cam button")) bt.classList.toggle("on", (bt.dataset.cam === "1") === live.follow);
  const el = $("#lv-side"); if (!el) return;
  const m = live.meta, fps = live.recv.length / 2, fresh = live.lastFrameAt && performance.now() - live.lastFrameAt < 3000;
  let rows = `<dt>stream</dt><dd class="${fresh ? "pos" : "neg"}">${fresh ? `live · ${fps.toFixed(0)} fps` : "no frames"}</dd>`;
  if (m) rows += `<dt>net</dt><dd class="mono">${esc(m.playing || "–")}</dd><dt>moves</dt><dd>${m.best_move ? "best move" : "sampled"}</dd><dt>opponent</dt><dd>${esc(m.teams[1].name)}</dd>`;
  el.innerHTML = rows;
}
const KIOSK_FRAME_MS = 66;              // the Pi's own screen draws at ~15 fps: drawing costs the CPU that training needs
function liveDraw(ts) {
  live.raf = requestAnimationFrame(liveDraw);
  if (document.body.classList.contains("kiosk")) {
    if (ts - (live.drawnAt || 0) < KIOSK_FRAME_MS) return;
    live.drawnAt = ts;
  }
  const cv = $("#lv-c"), m = live.meta;
  if (!cv) return;
  const over = $("#lv-over");
  if (performance.now() - live.sideAt > 1000) { live.sideAt = performance.now(); liveSide(); }
  if (!m || !live.frames.length) { over.hidden = false; over.innerHTML = "Waiting for the Pi's match…<small>it plays while an experiment trains</small>"; return; }
  const P = m.pitch, dpr = window.devicePixelRatio || 1, aspect = P.out_x / P.out_y;
  const box = cv.parentElement.getBoundingClientRect(), sbH = $("#lv-sb")?.offsetHeight || 0;
  const kiosk = document.body.classList.contains("kiosk"), fs = document.body.classList.contains("live-fs");
  const fill = kiosk || fs;                                   // kiosk and full screen: the canvas covers the whole area (any aspect ratio)
  cv.parentElement.classList.toggle("fill", fill);
  let cssW, cssH;
  if (fill) { cssW = Math.max(200, Math.round(box.width)); cssH = Math.max(120, Math.round(box.height)); }
  else {
    const availH = window.innerHeight - box.top - sbH - 24;
    cssW = Math.round(Math.max(200, Math.min(box.width, availH * aspect))); cssH = Math.round(cssW / aspect);
    if (cv.style.width !== cssW + "px") { cv.style.width = cssW + "px"; cv.style.height = cssH + "px"; }
  }
  if (cv.width !== Math.round(cssW * dpr) || cv.height !== Math.round(cssH * dpr)) { cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr); }
  const ctx = cv.getContext("2d");
  const rt = performance.now() - 70, fr = live.frames;
  let a = fr[fr.length - 1], b = a, u = 0;
  for (let i = fr.length - 1; i > 0; i--) if (fr[i - 1].at <= rt) { a = fr[i - 1]; b = fr[i]; u = Math.min(1, Math.max(0, (rt - a.at) / Math.max(b.at - a.at, 1))); break; }
  if (a.p.length !== b.p.length) { a = b; u = 0; }
  const Lp = (x, y) => x + (y - x) * u;
  const ball = [Lp(a.b[0], b.b[0]), Lp(a.b[1], b.b[1])];
  const zoom = live.follow ? 1.9 : 1, k = Math.min(cv.width / (2 * P.out_x), cv.height / (2 * P.out_y)) * zoom;
  const vx = cv.width / (2 * k), vy = cv.height / (2 * k);   // half the visible area in pitch units
  const clampTo = (v, half, out) => (half >= out ? 0 : Math.max(-out + half, Math.min(out - half, v)));
  const target = live.follow ? [clampTo(ball[0], vx, P.out_x), clampTo(ball[1], vy, P.out_y)] : [0, 0];
  if (!live.cam) live.cam = target.slice();
  live.cam[0] += (target[0] - live.cam[0]) * 0.12; live.cam[1] += (target[1] - live.cam[1]) * 0.12;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = shade("#" + P.outer, -0.25); ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.setTransform(k, 0, 0, k, cv.width / 2 - live.cam[0] * k, cv.height / 2 - live.cam[1] * k);
  const hw = P.half_w, hh = P.half_h;
  ctx.fillStyle = "#" + P.outer; ctx.fillRect(-P.out_x, -P.out_y, 2 * P.out_x, 2 * P.out_y);
  const n = Math.max(P.stripes, 1), sw = (2 * hw) / n;
  for (let i = 0; i < n; i++) { ctx.fillStyle = P.stripes > 0 && i % 2 === 0 ? shade("#" + P.pitch, -0.07) : "#" + P.pitch; ctx.fillRect(-hw + i * sw, -hh, sw + 0.5, 2 * hh); }
  for (let t = 0; t < 2; t++) {                               // goal floor and goal line; the net goes on top after the ball
    const sx = t === 0 ? -1 : 1, x0 = sx * hw, x1 = sx * (hw + P.net_depth), col = "#" + m.teams[t].primary;
    ctx.fillStyle = shade("#" + P.pitch, -0.2); ctx.fillRect(Math.min(x0, x1), -P.goal_half, P.net_depth, 2 * P.goal_half);
    ctx.beginPath(); ctx.moveTo(x0, -P.goal_half); ctx.lineTo(x0, P.goal_half);
    ctx.lineWidth = 6; ctx.strokeStyle = "rgba(0,0,0,.7)"; ctx.stroke(); ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.stroke();
  }
  ctx.strokeStyle = "#" + P.line; ctx.lineWidth = 3;
  ctx.strokeRect(-hw, -hh, 2 * hw, 2 * hh);
  ctx.beginPath(); ctx.moveTo(0, -hh); ctx.lineTo(0, hh); ctx.stroke();
  ctx.beginPath(); ctx.arc(0, 0, P.center_r, 0, 2 * Math.PI); ctx.stroke();
  ctx.fillStyle = "#" + P.line; ctx.beginPath(); ctx.arc(0, 0, 4, 0, 2 * Math.PI); ctx.fill();
  if (P.box_depth > 0) { ctx.lineWidth = 2.5; ctx.strokeRect(-hw, -P.box_half, P.box_depth, 2 * P.box_half); ctx.strokeRect(hw - P.box_depth, -P.box_half, P.box_depth, 2 * P.box_half); }
  live.trail.push(ball); if (live.trail.length > 14) live.trail.shift();
  for (let i = 0; i < live.trail.length - 1; i++) { ctx.globalAlpha = (i / live.trail.length) * 0.35; disc(ctx, live.trail[i][0], live.trail[i][1], m.ball_r * (0.4 + 0.5 * i / live.trail.length), "#fff"); }
  ctx.globalAlpha = 1;
  ctx.textAlign = "center";
  m.players.forEach((pl, i) => {
    if (2 * i + 1 >= a.p.length) return;
    const x = Lp(a.p[2 * i], b.p[2 * i]), y = Lp(a.p[2 * i + 1], b.p[2 * i + 1]), tm = m.teams[pl.team], r = pl.r;
    ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.clip();
    ctx.fillStyle = "#" + tm.primary; ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
    ctx.fillStyle = "#" + tm.secondary;
    if (tm.pattern === "stripes") { ctx.fillRect(x - 0.55 * r, y - r, 0.35 * r, 2 * r); ctx.fillRect(x + 0.2 * r, y - r, 0.35 * r, 2 * r); }
    else if (tm.pattern === "halves") ctx.fillRect(x, y - r, r, 2 * r);
    else if (tm.pattern === "hoops") { ctx.fillRect(x - r, y - 0.55 * r, 2 * r, 0.35 * r); ctx.fillRect(x - r, y + 0.2 * r, 2 * r, 0.35 * r); }
    else if (tm.pattern === "band") ctx.fillRect(x - 0.3 * r, y - r, 0.6 * r, 2 * r);
    ctx.restore();
    ctx.lineWidth = 2.5; ctx.strokeStyle = "#000"; ctx.beginPath(); ctx.arc(x, y, r - 1, 0, 2 * Math.PI); ctx.stroke();
    ctx.font = `700 ${Math.round(r * 0.95)}px system-ui, sans-serif`; ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,.85)"; ctx.textBaseline = "alphabetic";
    const txt = String(pl.n), mt = ctx.measureText(txt), ty = y + (mt.actualBoundingBoxAscent - mt.actualBoundingBoxDescent) / 2;   // centred on the digits' ink
    ctx.strokeText(txt, x, ty); ctx.fillStyle = "#fff"; ctx.fillText(txt, x, ty);
  });
  disc(ctx, ball[0], ball[1], m.ball_r, "#fff", "#000", 2);
  for (let t = 0; t < 2; t++) {                               // nets over the ball and players
    const sx = t === 0 ? -1 : 1, x0 = sx * hw, x1 = sx * (hw + P.net_depth), col = "#" + m.teams[t].primary, gh = P.goal_half;
    ctx.strokeStyle = col; ctx.globalAlpha = 0.45; ctx.lineWidth = 1; ctx.beginPath();
    for (let gg = 0; gg <= P.net_depth; gg += 10) { ctx.moveTo(x0 + sx * gg, -gh); ctx.lineTo(x0 + sx * gg, gh); }
    for (let gg = -gh; gg <= gh; gg += 10) { ctx.moveTo(x0, gg); ctx.lineTo(x1, gg); }
    ctx.stroke(); ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.moveTo(x0, -gh); ctx.lineTo(x1, -gh); ctx.lineTo(x1, gh); ctx.lineTo(x0, gh); ctx.lineJoin = "miter";
    ctx.lineWidth = 6; ctx.strokeStyle = "rgba(0,0,0,.7)"; ctx.stroke(); ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.stroke();
  }
  for (const px of [-hw, hw]) for (const py of [-P.goal_half, P.goal_half]) disc(ctx, px, py, P.post_r, "#f2f2f2", "#000", 2);
  const sb = $("#lv-sb");
  if (sb) {
    const runName = m.tag && m.tag.startsWith("x_") ? m.tag.slice(2) : m.tag;
    const t0 = { ...m.teams[0], name: m.teams[0].net && runName ? `${runName} · ${(m.playing || "").replace(/^.*_u/, "u")}` : m.teams[0].name }, t1 = m.teams[1];
    const key = `${t0.name}|${t1.name}|${b.sc}|${Math.ceil(b.tl)}|${b.st}|${m.mode}`;
    if (sb.dataset.key !== key) {
      sb.dataset.key = key;
      sb.innerHTML = `<div class="tm"><i class="kit" style="background:#${t0.primary}"></i><span>${esc(t0.name)}</span></div><div class="mid"><div class="score">${b.sc[0]} : ${b.sc[1]}</div><div class="clock">${m.mode === "puzzle" ? "PUZZLE · " : ""}${b.st === 2 ? "full time" : clockText(b.tl)}</div></div><div class="tm r"><span>${esc(t1.name)}</span><i class="kit" style="background:#${t1.primary}"></i></div>`;
    }
  }
  const stale = performance.now() - live.lastFrameAt > 3000;
  if (b.st === 1) { over.hidden = false; over.innerHTML = `GOAL<small>${esc(m.teams[b.gt]?.name || "")}</small>`; }
  else if (b.st === 2) { over.hidden = false; over.innerHTML = `FULL TIME<small>${b.sc[0]} : ${b.sc[1]}</small>`; }
  else if (stale) { over.hidden = false; over.innerHTML = "NO SIGNAL<small>waiting for the Pi's match</small>"; }
  else over.hidden = true;
}
function disc(ctx, x, y, r, fill, stroke, lw) { ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fillStyle = fill; ctx.fill(); if (stroke) { ctx.lineWidth = lw || 2; ctx.strokeStyle = stroke; ctx.stroke(); } }
function shade(hex, amt) { const v = parseInt(hex.slice(1), 16), g = (c) => Math.max(0, Math.min(255, Math.round(c * (1 + amt)))); return `rgb(${g(v >> 16)},${g((v >> 8) & 255)},${g(v & 255)})`; }

// ---------- data ----------
const pending = {};
function ensureDetail(name) {
  if (!name || pending[name] || (state.detail[name] && Date.now() - state.detail[name]._t < POLL_MS)) return;
  pending[name] = true;
  getJSON("/api/run/" + encodeURIComponent(name)).then((d) => { d._t = Date.now(); state.detail[name] = d; render(); })
    .catch(() => { state.detail[name] = { error: "Unknown run " + name, _t: Date.now() }; render(); }).finally(() => { delete pending[name]; });
}
function fetchCompare(run, e, ref, refUpdate, key) {
  if (!ref || pending["c" + key]) return;
  pending["c" + key] = true;
  getJSON(`/api/v1/compare?a=${encodeURIComponent(run)}&b=${encodeURIComponent(ref)}&kind=${e.kind}&ua=${e.update}${refUpdate != null ? "&ub=" + refUpdate : ""}`)
    .then((d) => { state.cmpCache[key] = d.data.difference_a_minus_b; rerender(); }).catch(() => { state.cmpCache[key] = {}; }).finally(() => { delete pending["c" + key]; });
}
function loadHealth() {
  if (pending._h) return;
  pending._h = true;
  getJSON("/api/health?hours=" + state.piHours).then((d) => { state.health = d; render(); }).catch(() => {}).finally(() => { delete pending._h; });
}
async function poll() {
  if (route().view === "game") return;                       // the Game area needs none of this
  try {
    state.ov = await getJSON("/api/overview");
    state.lastOk = Date.now(); state.firstFail = 0;
    const r = route();
    if (r.view === "run" && state.detail[r.arg]) state.detail[r.arg]._t = 0;
    if (r.view === "pi") state.health = null;
    if (r.view === "dataset" && !r.arg) loadDataset(true);
    if (r.view === "ranking") loadRanking(true);
    if (r.view === "compare") for (const n of (r.params.get("runs") || "").split(",")) if (state.detail[n]) state.detail[n]._t = 0;
    const run = state.ov.status.runner.running;
    if (run && state.detail[run.run]) state.detail[run.run]._t = 0;
    setPulse(true);
    render();
  } catch (e) {
    if (!state.firstFail) state.firstFail = Date.now();
    setPulse(false);
  }
}
function setPulse(ok) {
  const p = $("#pulse"), off = $("#offline"), pi = $("#pichip"), s = state.ov?.status?.pi;
  p.className = "pulse " + (ok ? "ok" : "err");
  if (pi && s) pi.innerHTML = `<i class="${s.temp_c > 75 || (s.throttled && s.throttled !== "0x0") ? "warn" : "ok"}"></i>${f(s.temp_c, 0)}°C · load ${f(s.load_1m, 1)}`;
  const down = !ok && state.firstFail && Date.now() - state.firstFail > 25000;
  off.hidden = !down;
  if (down) off.innerHTML = `<b>The Pi stopped answering</b>${state.lastOk ? " · last data " + new Date(state.lastOk).toLocaleTimeString() + " (" + dur((Date.now() - state.lastOk) / 1000) + " ago)" : ""} · if it froze, the watchdog reboots it and the runner resumes`;
}

// ---------- routing and events ----------
function route() {
  const h = location.hash.replace(/^#\/?/, ""), [path, qs] = h.split("?"), parts = path.split("/"), params = new URLSearchParams(qs || "");
  if (parts[0] === "run" && parts[1]) return { view: "run", arg: decodeURIComponent(parts[1]), tab: parts[2], params };
  if (parts[0] === "dataset") return { view: "dataset", arg: parts[1] ? decodeURIComponent(parts[1]) : "", params };
  if (parts[0] === "docs") return { view: "docs", arg: parts[1] ? decodeURIComponent(parts[1]) : "", params };
  if (parts[0] === "game") return { view: "game", parts: parts.slice(1), params };
  return { view: ["runs", "compare", "pi", "live", "ranking"].includes(parts[0]) ? parts[0] : "now", params };
}
let lastHTML = "";
function render() {
  const r = route();
  const area = r.view === "game" ? "game" : "lab";
  document.body.dataset.area = area;
  for (const a of document.querySelectorAll("[data-area-link]")) a.classList.toggle("on", a.dataset.areaLink === area);
  try { localStorage.setItem("area", area); } catch (e) {}
  if (area === "game") {                                    // the Game area draws itself (web/game.js)
    stopLive();
    const key = "game:" + r.parts.join("/");
    if (lastHTML !== key) { lastHTML = key; document.title = "Simple Soccer"; Game.show(r.parts); }
    return;
  }
  Game.stopMatch();
  if (!state.ov && !state.firstFail && !pending._ov) { pending._ov = true; poll().finally(() => { delete pending._ov; }); }
  for (const a of document.querySelectorAll("[data-v]")) a.classList.toggle("on", a.dataset.v === (r.view === "run" ? "runs" : r.view));
  document.body.dataset.view = r.view;
  if (r.view !== "live") { stopLive(); document.body.classList.remove("live-ctl"); }
  if (!(r.view === "dataset" && r.arg)) stopReplay();
  const before = new Set(Object.keys(chartData));
  const html = r.view === "live" ? viewLive() : r.view === "runs" ? viewRuns() : r.view === "run" ? viewRun(r.arg, r.tab) : r.view === "compare" ? viewCompare(r.params) : r.view === "pi" ? viewPi() : r.view === "docs" ? viewDocs(r.arg) : r.view === "dataset" ? viewDataset(r.arg) : r.view === "ranking" ? viewRanking() : viewNow();
  const cleaned = html.replace(/data-chart="c[a-z0-9]+"/g, "");
  const drop = (keep) => { for (const k of Object.keys(chartData)) if (before.has(k) !== keep) delete chartData[k]; };
  if (cleaned === lastHTML) { drop(true); return; }
  drop(false);
  lastHTML = cleaned;
  const view = $("#view"), active = document.activeElement, focus = active && active.dataset && active.dataset.filter !== undefined, caret = focus ? active.selectionStart : 0;
  view.innerHTML = html;
  attachCharts(view);
  if (focus) { const i = $("[data-filter]"); if (i) { i.focus(); i.setSelectionRange(caret, caret); } }
  if (r.view === "dataset" && r.arg) startReplay(r.arg);
  if (r.view === "live") { loadOpponents(); if (live.raf) cancelAnimationFrame(live.raf); live.raf = 0; startLive(); }
  document.title = (r.view === "run" ? r.arg + " · " : "") + "Soccer Lab · Simple Soccer";
  const dl = $("#runlist");
  if (dl && state.ov) dl.innerHTML = state.ov.runs.map((x) => `<option value="${esc(x.name)}">`).join("");
}
// the kiosk's control panel closes by itself 12 s after the last touch inside it
let ctlTimer = 0;
function setCtl(on) { document.body.classList.toggle("live-ctl", on); clearTimeout(ctlTimer); if (on) ctlTimer = setTimeout(() => document.body.classList.remove("live-ctl"), 12000); }
function rerender() { lastHTML = ""; render(); }
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("[data-fs]")) { toggleFullscreen(); return; }
  if (t.closest("[data-ctl]")) { setCtl(!document.body.classList.contains("live-ctl")); return; }
  if (document.body.classList.contains("live-ctl")) { if (t.closest(".live-side")) setCtl(true); else { setCtl(false); return; } }   // a tap outside the panel closes it; a tap inside keeps it open
  const md = t.closest("button[data-mode]");
  if (md) { live.mode = md.dataset.mode; liveSide(); fetch("/api/live/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: live.mode }) }).catch(() => {}); return; }
  const cam = t.closest("button[data-cam]");
  if (cam) { live.follow = cam.dataset.cam === "1"; try { localStorage.setItem("liveFollow", live.follow ? "1" : "0"); } catch (err) {} liveSide(); return; }
  const lg = t.closest("button.lg");
  if (lg) { const k = lg.dataset.key, s = lg.dataset.series; state.hidden[k] = state.hidden[k] || new Set(); if (state.hidden[k].has(s)) state.hidden[k].delete(s); else state.hidden[k].add(s); rerender(); return; }
  const th = t.closest("th[data-sort]");
  if (th) { const k = th.dataset.sort; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : k === "name" || k === "state" ? 1 : -1 }; rerender(); return; }
  const rfb = t.closest("button[data-rf]");
  if (rfb) { setRunsFilter(rfb.dataset.rf, rfb.dataset.rv); return; }
  const kd = t.closest("[data-kind]");
  if (kd) { const p = route().params; p.set("kind", kd.dataset.kind); location.hash = "#/compare?" + p.toString(); return; }
  const lgp = t.closest("[data-league]");
  if (lgp) { rk.league = lgp.dataset.league; rerender(); return; }
  const hrs = t.closest("[data-hours]");
  if (hrs) { state.piHours = +hrs.dataset.hours; state.health = null; rerender(); return; }
  const rm = t.closest("[data-rmrun]");
  if (rm) { const p = route().params; p.set("runs", (p.get("runs") || "").split(",").filter((n) => n && n !== rm.dataset.rmrun).join(",")); location.hash = "#/compare?" + p.toString(); return; }
  const cp = t.closest("[data-copy]");
  if (cp) { copySummary(cp.dataset.copy, cp); return; }
  if (t.closest("#rp-play") && ds.replay) { const R = ds.replay; if (!R.playing && R.d && R.i >= R.d.tick.length - 1) R.i = 0; R.playing = !R.playing; return; }
  const rs = t.closest("[data-rpspeed]");
  if (rs && ds.replay) { ds.replay.speed = +rs.dataset.rpspeed; for (const b of document.querySelectorAll("[data-rpspeed]")) b.classList.toggle("on", b === rs); return; }
  if (t.closest("input")) return;
  const tr = t.closest("tr[data-run]");
  if (tr && tr.dataset.run && !t.closest("a")) location.hash = "#/run/" + encodeURIComponent(tr.dataset.run);
});
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.rf !== undefined && t.tagName !== "BUTTON") { setRunsFilter(t.dataset.rf, t.type === "checkbox" ? t.checked : t.value); return; }
  if (t.dataset.pick !== undefined) { if (t.checked) state.selected.add(t.dataset.pick); else state.selected.delete(t.dataset.pick); rerender(); }
  if (t.dataset.addrun !== undefined && t.value) { const p = route().params; const runs = (p.get("runs") || "").split(",").filter(Boolean); runs.push(t.value); p.set("runs", runs.join(",")); location.hash = "#/compare?" + p.toString(); }
  if (t.dataset.evalpick !== undefined) { state.evalPick[t.dataset.evalpick] = t.value; rerender(); }
  if (t.id === "picker" && t.value) { location.hash = "#/run/" + encodeURIComponent(t.value); t.value = ""; t.blur(); }
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.filter !== undefined) { state.filter = t.value; rerender(); }
  if (t.dataset.smooth !== undefined) { state.smooth = +t.value; rerender(); }
  if (t.id === "rp-seek" && ds.replay) ds.replay.i = +t.value;
});
document.addEventListener("keydown", (e) => {
  if (document.body.dataset.area === "game") return;
  const R = ds.replay;
  if (R && R.d && document.activeElement?.tagName !== "INPUT") {          // the replay: space = play / pause, arrows = 1 s
    if (e.key === " ") { e.preventDefault(); R.playing = !R.playing; return; }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); R.i = Math.max(0, Math.min(R.d.tick.length - 1, R.i + (e.key === "ArrowLeft" ? -30 : 30))); return; }
  }
  if ((e.key === "/" || (e.key === "k" && (e.metaKey || e.ctrlKey))) && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); $("#picker")?.focus(); }
});
async function copySummary(name, btn) {
  try {
    const d = await getJSON("/api/v1/run/" + encodeURIComponent(name) + "?tail=5"), r = d.data, lf = r.latest_full;
    const md = `**${r.name}** (${r.state}${r.stop_reason ? ", " + r.stop_reason : ""}) · update ${r.update}/${r.target}\nchanges: ${JSON.stringify(r.rewards_changed_vs_minimal)}\n` +
      (lf ? `full u${lf.update}: ${lf.pts} ± ${lf.se} pts, GD ${lf.gd}, GA ${lf.ga}, vs RL4 ${lf.h2h["RL Team 4"]?.pts}, vs RL5 ${lf.h2h["RL Team 5"]?.pts}\n` : "") +
      (r.verdict ? `verdict vs ${r.verdict.reference}: ${r.verdict.verdict} (${r.verdict.pts} ± ${r.verdict.pts_se}, z ${r.verdict.z})\n` : "");
    await navigator.clipboard.writeText(md);
    btn.textContent = "copied";
  } catch (err) { btn.textContent = "copy failed"; }
  setTimeout(() => (btn.textContent = "copy summary"), 1500);
}
window.addEventListener("hashchange", () => { if (document.body.classList.contains("live-fs") && route().view !== "live") toggleFullscreen(false); lastHTML = ""; window.scrollTo(0, 0); render(); });
// full screen live match (like a video player): the page shows only the pitch and the score; the browser goes full screen too when it
// can (on the Pi's kiosk it already is). A tap on the button or Esc leaves it.
function toggleFullscreen(on) {
  on = on ?? !document.body.classList.contains("live-fs");
  document.body.classList.toggle("live-fs", on);
  try {
    if (on && !document.fullscreenElement && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  } catch (e) {}
  const b = $("[data-fs]"); if (b) { b.innerHTML = FS_ICON[on ? 1 : 0]; b.title = on ? "Exit full screen" : "Full screen"; }
}
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && document.body.classList.contains("live-fs") && !document.body.classList.contains("kiosk")) toggleFullscreen(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("live-fs")) toggleFullscreen(false); });

// kiosk: the Pi's 1024x600 touch screen opens on the live match; theme: dark unless the user picked light
if (new URLSearchParams(location.search).has("kiosk")) {
  document.body.classList.add("kiosk");
  document.documentElement.classList.add("kiosk");
  history.replaceState(null, "", location.pathname + location.search + "#/live");
}
function setThemeButton() { $("#theme").textContent = document.documentElement.dataset.theme === "light" ? "☾" : "☀"; }
$("#theme").addEventListener("click", () => {
  const light = document.documentElement.dataset.theme !== "light";
  if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("theme", light ? "light" : "dark"); } catch (e) {}
  setThemeButton(); rerender();
});
setThemeButton();
try { if (!location.hash && !document.body.classList.contains("kiosk") && localStorage.getItem("area") === "game") history.replaceState(null, "", "#/game"); } catch (e) {}
render();
setInterval(poll, POLL_MS);
// the kiosk keeps one page open for days: reload it when the dashboard's files changed on the Pi
let pageVersion = null;
setInterval(async () => {
  try { const v = (await (await fetch("/api/version")).json()).v; if (pageVersion === null) pageVersion = v; else if (v !== pageVersion) location.reload(); } catch (e) {}
}, 30000);
