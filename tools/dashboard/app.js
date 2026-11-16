// Soccer Lab: single-page dashboard of the experiment pipeline. Polls the JSON API of tools/dashboard.py every 10 s.
// Views (hash routes): #/ overview, #/runs, #/run/<name>, #/compare?a=&b=, #/queue, #/pi. Charts are plain SVG, no libraries.
"use strict";

const POLL_MS = 10000;
const COLORS = ["--blue", "--orange", "--accent", "--purple", "--gold", "--teal", "--pink", "--slate"];
const TERM_LABEL = {
  goals: "goals", time: "time", pass_prog: "progressive pass", pass_fail: "failed pass", pass_team: "pass (team)", coop: "cooperation",
  open: "open for pass", space: "spacing", kick: "kick discipline", xg: "xG for", xga: "xG against", result: "win / draw", tackle: "tackles",
  goalside: "goal-side", opp_half: "opponent in our half", compact: "compactness", far: "far from ball", keeper: "keeper", jitter: "twitching", shaping: "shaping",
};
const state = { overview: null, detail: {}, health: null, sort: { key: "pts", dir: -1 }, lastOk: 0 };

// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
const sgn = (v, d = 2) => (v === null || v === undefined ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(d));
const colorOf = (i) => css(COLORS[i % COLORS.length]);
function dur(s) {
  if (s === null || s === undefined) return "–";
  s = Math.max(0, Math.round(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m` : `${s}s`;
}
function ago(ts) { return ts ? dur(Date.now() / 1000 - ts) + " ago" : "–"; }
function badge(stateName) {
  const s = (stateName || "unknown").replace(/\s+/g, "");
  return `<span class="badge ${esc(s)}">${esc(stateName || "unknown")}</span>`;
}
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
function setPulse(ok, text) {
  const p = $("#pulse");
  p.className = "pulse " + (ok ? "ok" : "err");
  $("span", p).textContent = text;
}
function zOf(a, ase, b, bse) {
  if (a == null || b == null) return null;
  const se = Math.sqrt((ase || 0) ** 2 + (bse || 0) ** 2);
  return se > 0 ? (a - b) / se : null;
}
function verdictFromZ(z) {
  if (z === null) return "";
  return z > 1.96 ? "better" : z < -1.96 ? "worse" : "no difference";
}
function runColor(name) {
  const runs = (state.overview?.runs || []).map((r) => r.run);
  const i = runs.indexOf(name);
  return colorOf(i < 0 ? 0 : i);
}
function throttleText(hex) {
  if (!hex) return { text: "–", cls: "" };
  const v = parseInt(hex, 16);
  const now = [], past = [];
  if (v & 0x1) now.push("under-voltage"); if (v & 0x2) now.push("frequency capped"); if (v & 0x4) now.push("throttled"); if (v & 0x8) now.push("soft temp limit");
  if (v & 0x10000) past.push("under-voltage"); if (v & 0x20000) past.push("freq. capped"); if (v & 0x40000) past.push("throttled"); if (v & 0x80000) past.push("soft temp limit");
  if (!v) return { text: "OK", cls: "pos", sub: "no throttling since boot" };
  return { text: now.length ? now.join(", ") : "OK now", cls: now.length ? "neg" : "", sub: past.length ? "since boot: " + past.join(", ") : "" };
}

// ---------- charts ----------
// series: [{name, color, points: [{x, y, err?, label?}], dashed?, dots?, width?}]
function lineChart(series, opt = {}) {
  const W = opt.width || 640, H = opt.height || 230, L = 46, R = 14, T = 12, B = 28;
  const pts = series.flatMap((s) => s.points.filter((p) => p.y !== null && p.y !== undefined && !Number.isNaN(p.y)));
  if (!pts.length) return `<div class="empty">${esc(opt.emptyText || "No data yet")}</div>`;
  let x0 = opt.xMin ?? Math.min(...pts.map((p) => p.x)), x1 = opt.xMax ?? Math.max(...pts.map((p) => p.x));
  if (x1 === x0) { x0 -= 1; x1 += 1; }
  let y0 = opt.yMin ?? Math.min(...pts.map((p) => p.y - (p.err || 0)), ...(opt.refs || []).map((r) => r.y));
  let y1 = opt.yMax ?? Math.max(...pts.map((p) => p.y + (p.err || 0)), ...(opt.refs || []).map((r) => r.y));
  if (opt.zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  if (y1 === y0) { y0 -= 0.5; y1 += 0.5; }
  const pad = (y1 - y0) * 0.08; if (opt.yMin === undefined) y0 -= pad; if (opt.yMax === undefined) y1 += pad;
  const X = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - R), Y = (y) => T + ((y1 - y) / (y1 - y0)) * (H - T - B);
  const ticks = niceTicks(y0, y1, 5), xt = niceTicks(x0, x1, 6);
  let g = "";
  for (const t of ticks) g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${L - 7}" y="${Y(t) + 4}" text-anchor="end">${fmtTick(t)}</text>`;
  for (const t of xt) if (t >= x0 && t <= x1) g += `<text class="ax" x="${X(t)}" y="${H - 8}" text-anchor="middle">${fmtTick(t)}</text>`;
  for (const r of opt.refs || []) g += `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(r.y)}" y2="${Y(r.y)}"/><text class="reft" x="${W - R}" y="${Y(r.y) - 4}" text-anchor="end">${esc(r.label)}</text>`;
  for (const s of series) {
    const p = s.points.filter((q) => q.y !== null && q.y !== undefined && !Number.isNaN(q.y)).sort((a, b) => a.x - b.x);
    if (!p.length) continue;
    if (s.band) {
      const up = p.map((q) => `${X(q.x)},${Y(q.y + (q.err || 0))}`), dn = p.slice().reverse().map((q) => `${X(q.x)},${Y(q.y - (q.err || 0))}`);
      g += `<polygon points="${up.concat(dn).join(" ")}" fill="${s.color}" opacity=".12"/>`;
    }
    if (p.length > 1 && !s.noLine) g += `<polyline points="${p.map((q) => `${X(q.x)},${Y(q.y)}`).join(" ")}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round" ${s.dashed ? 'stroke-dasharray="6 5"' : ""}/>`;
    for (const q of p) {
      if (q.err && !s.band) g += `<line x1="${X(q.x)}" x2="${X(q.x)}" y1="${Y(q.y - q.err)}" y2="${Y(q.y + q.err)}" stroke="${s.color}" stroke-width="2" opacity=".55"/>`;
      if (s.dots || p.length === 1 || q.big) g += `<circle cx="${X(q.x)}" cy="${Y(q.y)}" r="${q.big ? 5 : 3.5}" fill="${q.hollow ? "var(--panel)" : s.color}" stroke="${s.color}" stroke-width="2"/>`;
    }
  }
  const id = "c" + Math.random().toString(36).slice(2);
  chartData[id] = { series, X, Y, x0, x1, L, R, T, B, W, H, xLabel: opt.xLabel || "update", fmt: opt.fmt || ((v) => f(v, 2)) };
  const legend = series.length > 1 || opt.legend ? `<div class="legend">${series.filter((s) => s.points.length).map((s) => `<span><i class="${s.dashed ? "d" : ""}" style="background:${s.color};color:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : "";
  return `<div class="chart" data-chart="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.title || "chart")}">${g}<line class="hover-line" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/></svg>${legend}</div>`;
}
const chartData = {};
function niceTicks(a, b, n) {
  const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function fmtTick(v) {
  const a = Math.abs(v);
  return a >= 1000 ? (v / 1000).toFixed(a >= 10000 ? 0 : 1) + "k" : a >= 10 || v === 0 ? String(Math.round(v)) : a >= 1 ? v.toFixed(1).replace(/\.0$/, "") : a >= 0.001 ? String(+v.toPrecision(2)) : v.toExponential(0);
}
function attachCharts(root) {
  for (const el of root.querySelectorAll("[data-chart]")) {
    const d = chartData[el.dataset.chart];
    const svg = $("svg", el), line = $(".hover-line", el), tip = $("#tip");
    const move = (ev) => {
      const box = svg.getBoundingClientRect(), sx = ((ev.clientX - box.left) / box.width) * d.W;
      if (sx < d.L || sx > d.W - d.R) return leave();
      const xv = d.x0 + ((sx - d.L) / (d.W - d.L - d.R)) * (d.x1 - d.x0);
      let best = null;
      for (const s of d.series) for (const p of s.points) if (p.y != null && (best === null || Math.abs(p.x - xv) < Math.abs(best - xv))) best = p.x;
      if (best === null) return leave();
      line.setAttribute("x1", d.X(best)); line.setAttribute("x2", d.X(best)); line.setAttribute("visibility", "visible");
      let html = `<b>${esc(d.xLabel)} ${esc(fmtTick(best))}</b>`;
      for (const s of d.series) {
        const p = s.points.find((q) => q.x === best && q.y != null);
        if (p) html += `<br><span class="k" style="background:${s.color}"></span>${esc(s.name)}: <b>${d.fmt(p.y)}</b>${p.err ? ` ± ${d.fmt(p.err)}` : ""}${p.label ? ` <span style="opacity:.7">${esc(p.label)}</span>` : ""}`;
      }
      tip.innerHTML = html; tip.hidden = false;
      const tx = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = tx + "px"; tip.style.top = ev.clientY + 14 + "px";
    };
    const leave = () => { line.setAttribute("visibility", "hidden"); tip.hidden = true; };
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerleave", leave);
  }
}
function sparkline(vals, color, w = 110, h = 26) {
  if (!vals || vals.length < 2) return '<span class="muted">–</span>';
  const lo = Math.min(...vals), hi = Math.max(...vals), sp = hi - lo || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * (w - 4) + 2},${h - 3 - ((v - lo) / sp) * (h - 6)}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}
function heatmap(hm, title) {
  const w = hm.w, h = hm.h, cw = 14, ch = 14, W = w * cw, H = h * ch;
  const mx = Math.max(...hm.v, 1);
  const base = css("--accent");
  let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="var(--panel-2)"/>`;
  hm.v.forEach((v, i) => {
    const x = (i % w) * cw, y = Math.floor(i / w) * ch, a = Math.sqrt(v / mx);
    if (v > 0) g += `<rect x="${x}" y="${y}" width="${cw}" height="${ch}" fill="${base}" opacity="${(0.08 + 0.92 * a).toFixed(3)}"><title>${(v / 10).toFixed(1)}% of the time</title></rect>`;
  });
  g += `<rect x=".5" y=".5" width="${W - 1}" height="${H - 1}" fill="none" stroke="var(--line)"/>`;
  g += `<line x1="${W / 2}" x2="${W / 2}" y1="0" y2="${H}" stroke="var(--line)"/><circle cx="${W / 2}" cy="${H / 2}" r="${ch * 1.3}" fill="none" stroke="var(--line)"/>`;
  g += `<rect x="0" y="${H / 2 - ch * 1.5}" width="4" height="${ch * 3}" fill="var(--muted)" opacity=".6"/><rect x="${W - 4}" y="${H / 2 - ch * 1.5}" width="4" height="${ch * 3}" fill="var(--bad)" opacity=".6"/>`;
  return `<figure class="heat"><figcaption><span>${esc(title)}</span><span>${esc(hm.role !== "-" ? hm.role : "")}</span></figcaption><svg viewBox="0 0 ${W} ${H}">${g}</svg></figure>`;
}
function hbars(items) {
  const mx = Math.max(...items.map((i) => Math.abs(i.v)), 1e-12);
  return items.map((i) => {
    const wv = (Math.abs(i.v) / mx) * 50;
    const left = i.v >= 0 ? 50 : 50 - wv;
    return `<div class="hbar"><span title="${esc(i.k)}">${esc(i.label)}</span><div class="tr"><div class="mid"></div><i style="left:${left}%;width:${wv}%;background:${i.v >= 0 ? "var(--good)" : "var(--bad)"}"></i></div><span class="v">${i.v >= 0 ? "+" : ""}${i.v.toExponential(1)}</span></div>`;
  }).join("");
}
function kpi(label, value, sub = "", cls = "") {
  return `<div class="kpi"><div class="l">${label}</div><div class="v ${cls}">${value}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;
}

// ---------- views ----------
function viewOverview() {
  const o = state.overview;
  if (!o) return '<div class="empty">Loading…</div>';
  const sys = o.system, now = o.now;
  let hero;
  if (now) {
    const pct = now.target ? Math.min(100, (100 * (now.update || 0)) / now.target) : 0;
    const stale = now.log_age_s !== null && now.log_age_s > 600 && !now.eval;
    const mode = now.eval ? "eval" : stale ? "stale" : "";
    const label = now.eval ? `<span class="badge evaluating">evaluating ${esc(now.eval.checkpoint || "")}</span>` : stale ? '<span class="badge failed">no progress for ' + dur(now.log_age_s) + "</span>" : '<span class="badge running">training</span>';
    const delta = now.train_pts != null && now.base_train != null ? now.train_pts - now.base_train : null;
    hero = `<section class="hero ${mode}">
      <div class="hero-top"><div><h3>Running experiment</h3><h1><a href="#/run/${encodeURIComponent(now.run)}">${esc(now.run)}</a></h1>
      <p class="notes">${esc(now.notes)}</p><div>${Object.entries(now.rewards || {}).map(([k, v]) => `<span class="chip">${esc(k)} = ${esc(v)}</span>`).join("") || '<span class="chip">minimal rewards</span>'}</div></div>${label}</div>
      <div class="progress"><i style="width:${pct}%"></i></div>
      <div class="hero-stats">
        <div><b>${now.update ?? 0} / ${now.target ?? "?"}</b><span>updates</span></div>
        <div><b>${now.eta_s ? dur(now.eta_s) : "–"}</b><span>time left (training only)</span></div>
        <div><b>${now.sec_per_update ? f(now.sec_per_update, 0) + " s" : "–"}</b><span>per update</span></div>
        <div><b>${f(now.train_pts)} <span class="${delta > 0 ? "pos" : delta < 0 ? "neg" : ""}" style="font-size:13px">${delta != null ? sgn(delta) : ""}</span></b><span>training pts vs rule bots (start ${f(now.base_train)})</span></div>
        <div><b>${now.last ? now.last.dps : "–"}</b><span>decisions / s</span></div>
        <div><b>${now.started ? ago(now.started) : "–"}</b><span>started</span></div>
      </div></section>`;
  } else {
    hero = `<section class="hero idle"><div class="hero-top"><div><h3>Runner</h3><h1>Idle</h1><p class="notes">Nothing is training. The runner starts the next spec in exp/queue/ (${o.queue.length} waiting).</p></div><span class="badge queued">idle</span></div></section>`;
  }
  const full = o.runs.filter((r) => r.latest && r.latest.kind === "full" && r.latest.league.all);
  const best = full.slice().sort((a, b) => b.latest.league.all.pts - a.latest.league.all.pts)[0];
  const th = throttleText(sys.throttled);
  const done = o.runs.filter((r) => ["done", "diverged", "regressed", "failed"].includes(r.state)).length;
  const kpis = `<div class="kpis">
    ${kpi("Best league result", best ? `${f(best.latest.league.all.pts)}<small>± ${f(best.latest.league.all.se)}</small>` : "–", best ? `${esc(best.run)} · u${best.latest.update}` : "")}
    ${kpi("Experiments", `${done}<small>done</small> ${o.queue.length}<small>queued</small>`, `${o.runs.length} runs tracked`)}
    ${kpi("Pi temperature", sys.temp != null ? `${f(sys.temp, 1)}<small>°C</small>` : "–", "", sys.temp > 75 ? "neg" : "")}
    ${kpi("CPU load", sys.load.length ? `${f(sys.load[0], 1)}<small>/ 4 cores</small>` : "–", sys.load.length ? `5 min ${f(sys.load[1], 1)} · 15 min ${f(sys.load[2], 1)}` : "")}
    ${kpi("Free memory", `${(sys.mem_avail_mb / 1024).toFixed(1)}<small>of ${(sys.mem_total_mb / 1024).toFixed(1)} GB</small>`, "", sys.mem_avail_mb < 500 ? "neg" : "")}
    ${kpi("Power", th.text, th.sub || `up ${dur(sys.uptime_s)}`, th.cls)}
  </div>`;
  const lb = leaderboard(o.runs);
  let curve = "";
  if (now) {
    const d = state.detail[now.run];
    curve = d ? trainingChart(d, { height: 220 }) : '<div class="empty">Loading…</div>';
    ensureDetail(now.run);
  }
  const events = o.events.length ? `<ul class="events">${o.events.map((e) => { const m = e.match(/^\[(.+?)\] (.*)$/); return `<li>${m ? `<time>${esc(m[1].slice(5, 16))}</time>${esc(m[2])}` : esc(e)}</li>`; }).join("")}</ul>` : '<div class="empty">No events yet</div>';
  const q = o.queue.slice(0, 5).map((s, i) => `<div class="qcard"><div class="n">${i + 1}</div><div><b>${esc(s.name)}</b><p>${esc(s.notes)}</p>${Object.entries(s.rewards).map(([k, v]) => `<span class="chip">${esc(k)} = ${esc(v)}</span>`).join("") || '<span class="chip">minimal rewards</span>'}</div></div>`).join("");
  return `${hero}${kpis}
    <div class="grid g2">
      <div class="card"><h2>League strength by run</h2><div class="sub">Latest full evaluation: points per match against all 16 rule teams, bar = ± 2 standard errors. Dashed line = the start net.</div>${lb}</div>
      <div class="card"><h2>${now ? "Training progress · " + esc(now.run) : "Training progress"}</h2><div class="sub">Points per match during training (sampled moves, last 200 matches).</div>${curve || '<div class="empty">Nothing training</div>'}</div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Runner events</h2>${events}</div>
      <div class="card flush"><h2>Up next</h2>${q || '<div class="empty">Queue empty</div>'}${o.queue.length > 5 ? `<div style="padding:10px 16px"><a href="#/queue">All ${o.queue.length} queued →</a></div>` : ""}</div>
    </div>`;
}

function leaderboard(runs) {
  const rows = runs.filter((r) => r.latest && r.latest.kind === "full" && r.latest.league.all).sort((a, b) => b.latest.league.all.pts - a.latest.league.all.pts);
  if (!rows.length) return '<div class="empty">No full evaluations yet</div>';
  const lo = 0, hi = 3;
  const P = (v) => (100 * (Math.max(lo, Math.min(hi, v)) - lo)) / (hi - lo);
  const base = runs.find((r) => r.run.startsWith("start:") && r.latest)?.latest?.league?.all?.pts;
  return rows.map((r) => {
    const a = r.latest.league.all, c = runColor(r.run);
    return `<div class="lb-row"><a class="name" href="#/run/${encodeURIComponent(r.run)}" title="${esc(r.run)}"><span class="dot" style="background:${c}"></span>${esc(r.run)}</a>
      <div class="lb-track"><div class="axis"></div>${base != null ? `<div class="base" style="left:${P(base)}%"></div>` : ""}<div class="err" style="left:${P(a.pts - 2 * a.se)}%;width:${P(a.pts + 2 * a.se) - P(a.pts - 2 * a.se)}%;background:${c}"></div><div class="pt" style="left:${P(a.pts)}%;background:${c}"></div></div>
      <div class="val">${f(a.pts)} <span class="pm">±${f(a.se)}</span></div></div>`;
  }).join("") + `<div class="lb-row muted" style="font-size:11px"><span></span><div style="display:flex;justify-content:space-between"><span>0</span><span>1</span><span>2</span><span>3 pts</span></div><span></span></div>`;
}

function trainingChart(d, opt = {}) {
  const t = d.training || [];
  return lineChart([
    { name: "vs rule bots", color: css("--blue"), points: t.map((r) => ({ x: r.upd, y: r.rules })) },
    { name: "vs frozen start net", color: css("--orange"), points: t.map((r) => ({ x: r.upd, y: r.bench })) },
    { name: "vs own snapshots", color: css("--purple"), points: t.map((r) => ({ x: r.upd, y: r.league })), dashed: true },
  ], { height: opt.height || 240, yMin: 0, yMax: 3, title: "training points" });
}

function viewRuns() {
  const o = state.overview;
  if (!o) return '<div class="empty">Loading…</div>';
  const key = state.sort.key, dir = state.sort.dir;
  const val = (r) => {
    const a = r.latest?.league?.all || {};
    return { run: r.run, state: r.state, upd: r.latest?.update ?? -1, pts: a.pts ?? -9, gd: a.gd ?? -9, ga: a.ga ?? 9, rl4: r.latest?.h2h?.["RL Team 4"]?.pts ?? -9, rl5: r.latest?.h2h?.["RL Team 5"]?.pts ?? -9, dir: r.latest?.behaviour?.dir_changes_s ?? 99 }[key];
  };
  const rows = o.runs.slice().sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir);
  const th = (k, l, cls = "") => `<th class="sort ${cls}" data-sort="${k}">${l}${key === k ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`;
  const body = rows.map((r) => {
    const a = r.latest?.league?.all, h = r.latest?.h2h || {}, b = r.latest?.behaviour || {};
    const v = r.verdict?.verdict;
    return `<tr class="link" data-run="${esc(r.run)}"><td><span class="dot" style="background:${runColor(r.run)}"></span><b>${esc(r.run)}</b></td><td>${badge(r.state)}</td>
      <td class="r">${r.update ?? "–"}${r.target ? `<span class="pm">/${r.target}</span>` : ""}</td><td>${sparkline(r.spark, runColor(r.run))}</td>
      <td class="r">${a ? `${f(a.pts)}<span class="pm">±${f(a.se)}</span>` : "–"}</td><td class="r ${a && a.gd > 0 ? "pos" : a && a.gd < 0 ? "neg" : ""}">${a ? sgn(a.gd) : "–"}</td><td class="r">${a ? f(a.ga) : "–"}</td>
      <td class="r">${f(h["RL Team 4"]?.pts)}</td><td class="r">${f(h["RL Team 5"]?.pts)}</td><td class="r">${f(b.dir_changes_s, 1)}</td>
      <td>${r.latest ? `<span class="muted">${r.latest.kind} · u${r.latest.update}</span>` : ""}</td><td>${v ? badge(v) + ` <span class="pm">${sgn(r.verdict.pts)} ± ${f(r.verdict.pts_se)}</span>` : ""}</td></tr>`;
  }).join("");
  return `<div class="head"><div><h1>Runs</h1><p>Every experiment and imported run with its latest evaluation. Click a run for details; sort by any column.</p></div><a href="#/compare">Compare two runs →</a></div>
    <div class="card flush"><div class="tbl-wrap"><table><thead><tr>${th("run", "Run")}${th("state", "State")}${th("upd", "Update", "r")}<th>Training</th>${th("pts", "League pts", "r")}${th("gd", "Goal diff", "r")}${th("ga", "Conceded", "r")}${th("rl4", "vs RL4", "r")}${th("rl5", "vs RL5", "r")}${th("dir", "Dir. chg/s", "r")}<th>Eval</th><th>Verdict vs start</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function viewRun(name) {
  const d = state.detail[name];
  ensureDetail(name);
  if (!d) return '<div class="empty">Loading…</div>';
  const st = d.status || {}, spec = st.spec || {};
  const fulls = d.evals.filter((e) => e.kind === "full"), fasts = d.evals.filter((e) => e.kind === "fast");
  const last = fulls[fulls.length - 1] || fasts[fasts.length - 1];
  const a = last?.league?.all;
  const baseFull = (d.baseline?.evals || []).filter((e) => e.kind === "full").pop();
  const baseFast = (d.baseline?.evals || []).filter((e) => e.kind === "fast").pop();
  const ba = baseFull?.league?.all;
  const z = a && ba && last.kind === "full" ? zOf(a.pts, a.se, ba.pts, ba.se) : null;
  const h = last?.h2h || {};
  const kp = `<div class="kpis">
    ${kpi(`League pts <span class="muted">(${last ? last.kind + " · u" + last.update : "–"})</span>`, a ? `${f(a.pts)}<small>± ${f(a.se)}</small>` : "–", ba ? `start ${f(ba.pts)} ± ${f(ba.se)}` : "")}
    ${kpi("Goal difference", a ? sgn(a.gd) : "–", a ? `GF ${f(a.gf)} · GA ${f(a.ga)}` : "", a && a.gd > 0 ? "pos" : a && a.gd < 0 ? "neg" : "")}
    ${kpi("vs RL Team 4", f(h["RL Team 4"]?.pts), h["RL Team 4"] ? `W${h["RL Team 4"].w} D${h["RL Team 4"].d} L${h["RL Team 4"].l}` : "")}
    ${kpi("vs RL Team 5", f(h["RL Team 5"]?.pts), h["RL Team 5"] ? `W${h["RL Team 5"].w} D${h["RL Team 5"].d} L${h["RL Team 5"].l}` : "")}
    ${kpi("vs start net", f(h["start"]?.pts), h["start"] ? `GD ${sgn(h["start"].gd)}` : "")}
    ${kpi("Verdict vs start", z === null ? "–" : verdictFromZ(z), z === null ? "needs a full evaluation" : `${sgn(a.pts - ba.pts)} pts, z = ${f(z, 1)}`, z > 1.96 ? "pos" : z < -1.96 ? "neg" : "")}
  </div>`;
  const evalPts = [
    { name: "full", color: runColor(name), points: fulls.filter((e) => e.league.all).map((e) => ({ x: e.update, y: e.league.all.pts, err: e.league.all.se, big: true })), dots: true },
    { name: "fast check", color: runColor(name), points: fasts.filter((e) => e.league.all).map((e) => ({ x: e.update, y: e.league.all.pts, err: e.league.all.se, hollow: true })), dots: true, dashed: true },
  ];
  const refs = [];
  if (ba) refs.push({ y: ba.pts, label: "start (full) " + f(ba.pts) });
  if (baseFast?.league?.all) refs.push({ y: baseFast.league.all.pts, label: "start (fast) " + f(baseFast.league.all.pts) });
  const ppo = d.ppo || [];
  const terms = d.terms || [];
  const tkeys = [...new Set(terms.flatMap((t) => Object.keys(t).filter((k) => k !== "upd")))];
  const recent = terms.slice(-20);
  const means = tkeys.map((k) => ({ k, label: TERM_LABEL[k] || k, v: recent.reduce((s, t) => s + (t[k] || 0), 0) / Math.max(recent.length, 1) })).filter((x) => x.v !== 0).sort((x, y) => Math.abs(y.v) - Math.abs(x.v));
  const smooth = (rows, k, n = 5) => rows.map((r, i) => { const w = rows.slice(Math.max(0, i - n + 1), i + 1); return { x: r.upd, y: w.reduce((s, q) => s + (q[k] || 0), 0) / w.length }; });
  const termSeries = means.slice(0, 7).map((m, i) => ({ name: m.label, color: colorOf(i), points: smooth(terms, m.k) }));
  const heats = last && fulls.length ? (fulls[fulls.length - 1].heat || []) : [];
  const tierRows = ["weak", "average", "strong", "elite", "held", "all"].filter((t) => last?.league?.[t]).map((t) => {
    const s = last.league[t], g = last.greedy?.[t];
    return `<tr><td>${t === "held" ? "held-out teams" : t === "all" ? "<b>all 16 teams</b>" : t}</td><td class="r">${f(s.pts)}<span class="pm">±${f(s.se)}</span></td><td class="r ${s.gd > 0 ? "pos" : s.gd < 0 ? "neg" : ""}">${sgn(s.gd)}</td><td class="r">${f(s.ga)}</td><td class="r">${s.n}</td><td class="r">${g ? `${f(g.pts)}<span class="pm">±${f(g.se)}</span>` : "–"}</td><td class="r">${g ? f(g.ga) : "–"}</td></tr>`;
  }).join("");
  const h2hRows = Object.entries(h).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r">${f(v.pts)}<span class="pm">±${f(v.se)}</span></td><td class="r">${v.w} / ${v.d} / ${v.l}</td><td class="r ${v.gd > 0 ? "pos" : v.gd < 0 ? "neg" : ""}">${sgn(v.gd)}</td><td class="r">${f(v.gf)} – ${f(v.ga)}</td></tr>`).join("");
  const b = last?.behaviour || {};
  const cfg = d.config || {};
  const rewardKeys = Object.keys(cfg).filter((k) => k.startsWith("w_") || ["shaping", "pass_individual", "coop_cap", "random_start", "xg_cap", "def_cap", "far_radius"].includes(k));
  const cfgRows = rewardKeys.map((k) => `<dt>${esc(k)}</dt><dd class="${cfg[k] && k in (spec.rewards || {}) ? "hl" : ""}">${esc(cfg[k])}</dd>`).join("");
  const runKeys = ["lr", "updates", "start_update", "rollout", "minibatch", "epochs", "ent", "gamma", "lam", "workers_rule", "workers_self", "envs_per_worker", "learn_threads", "fast_every", "start"].filter((k) => k in cfg);
  const runRows = runKeys.map((k) => `<dt>${esc(k)}</dt><dd>${esc(cfg[k])}</dd>`).join("");
  return `<div class="head"><div><h3>Run</h3><h1><span class="dot" style="background:${runColor(name)}"></span>${esc(name)} ${badge(st.state || (name.startsWith("old_") || name.startsWith("start:") ? "imported" : ""))}</h1>
      <p>${esc(spec.notes || "")}</p><div>${Object.entries(spec.rewards || {}).map(([k, v]) => `<span class="chip">${esc(k)} = ${esc(v)}</span>`).join("")}</div></div>
      <div class="muted" style="text-align:right">${st.update != null ? `update ${st.update}${st.target_updates ? " / " + st.target_updates : ""}<br>` : ""}${st.started ? "started " + ago(st.started) : ""}${st.finished ? "<br>finished " + ago(st.finished) : ""}</div></div>
    ${kp}
    <div class="grid g2">
      <div class="card"><h2>League points at each evaluation</h2><div class="sub">Filled = full evaluation (32 matches), hollow = fast check (24 short matches). Bars ± 1 standard error.</div>${lineChart(evalPts, { refs, yMin: 0, yMax: 3, height: 230, legend: true })}</div>
      <div class="card"><h2>Training points</h2><div class="sub">During training, sampled moves, rolling window.</div>${trainingChart(d, { height: 230 })}</div>
    </div>
    <div class="grid g3">
      <div class="card"><h2>PPO: approx. KL</h2><div class="sub">How far each update moves the policy. Healthy here: 0.001–0.02.</div>${lineChart([{ name: "KL", color: css("--blue"), points: ppo.map((p) => ({ x: p.upd, y: p.kl })) }, { name: "clip fraction", color: css("--orange"), points: ppo.map((p) => ({ x: p.upd, y: p.clipfrac })), dashed: true }], { height: 220, width: 400, fmt: (v) => f(v, 4) })}</div>
      <div class="card"><h2>Critic explained variance</h2><div class="sub">1 = the value net predicts returns perfectly.</div>${lineChart([{ name: "explained variance", color: css("--accent"), points: ppo.map((p) => ({ x: p.upd, y: p.ev })) }], { height: 220, width: 400, yMax: 1 })}</div>
      <div class="card"><h2>Policy entropy</h2><div class="sub">Randomness of the moves; a rise means the net is less sure.</div>${lineChart([{ name: "move", color: css("--purple"), points: ppo.map((p) => ({ x: p.upd, y: p.ent_move })) }, { name: "kick", color: css("--gold"), points: ppo.map((p) => ({ x: p.upd, y: p.ent_kick })), dashed: true }], { height: 220, width: 400 })}</div>
    </div>
    <div class="grid g2">
      <div class="card"><h2>Reward terms over training</h2><div class="sub">Mean reward per agent decision, smoothed over 5 updates (largest 7 terms).</div>${lineChart(termSeries, { height: 240, zero: true, fmt: (v) => v.toExponential(2) })}</div>
      <div class="card"><h2>What the reward is made of</h2><div class="sub">Mean of the last 20 updates per term (green pays, red costs).</div>${means.length ? hbars(means) : '<div class="empty">No reward data</div>'}</div>
    </div>
    <div class="grid g2">
      <div class="card flush"><h2>League by tier ${last ? `<span class="muted">· ${last.kind} u${last.update}</span>` : ""}</h2><div class="tbl-wrap"><table><thead><tr><th>Opponents</th><th class="r">Pts</th><th class="r">GD</th><th class="r">GA</th><th class="r">N</th><th class="r" title="the net playing its best move instead of sampling">Pts best move</th><th class="r">GA</th></tr></thead><tbody>${tierRows || '<tr><td colspan="7" class="muted">No evaluation yet</td></tr>'}</tbody></table></div></div>
      <div class="card flush"><h2>Head to head</h2><div class="tbl-wrap"><table><thead><tr><th>Opponent</th><th class="r">Pts</th><th class="r">W / D / L</th><th class="r">Goal diff</th><th class="r">Score</th></tr></thead><tbody>${h2hRows || '<tr><td colspan="5" class="muted">No head-to-head yet</td></tr>'}</tbody></table></div>
        <div style="padding:12px 16px"><h3>Behaviour vs rule bots</h3><dl class="kv"><dt>direction changes / s</dt><dd>${f(b.dir_changes_s, 2)} <span class="muted">(rule bots ≈ 2.2)</span></dd><dt>idle</dt><dd>${f(b.idle_pct, 0)} %</dd><dt>teammate spacing</dt><dd>${f(b.spacing_px, 0)} px <span class="muted">(rule bots ≈ 270)</span></dd><dt>passes / match</dt><dd>${f(b.passes_match, 1)}</dd><dt>shots / match</dt><dd>${f(b.shots_match, 1)}</dd><dt>xA / match</dt><dd>${f(b.xa_match, 2)}</dd></dl></div></div>
    </div>
    ${heats.length ? `<div class="card" style="margin-bottom:14px"><h2>Where the players are</h2><div class="sub">Share of time per area, latest full evaluation, attacking to the right (red goal = opponent).</div><div class="heats">${heats.map((hm) => heatmap(hm, hm.slot === "ball" ? "Ball" : "Player " + (Number(hm.slot) + 1))).join("")}</div></div>` : ""}
    <div class="grid g2">
      <div class="card"><h2>Reward settings</h2><div class="sub">Highlighted = changed by this experiment.</div><dl class="kv">${cfgRows || '<dt class="muted">no config file</dt><dd></dd>'}</dl></div>
      <div class="card"><h2>Training settings</h2><dl class="kv">${runRows || '<dt class="muted">no config file</dt><dd></dd>'}</dl></div>
    </div>`;
}

function viewCompare(params) {
  const o = state.overview;
  if (!o) return '<div class="empty">Loading…</div>';
  const names = o.runs.map((r) => r.run);
  const A = params.get("a") || names.find((n) => n.startsWith("start:")) || names[0], B = params.get("b") || names[names.length - 1];
  const sel = (id, v) => `<select data-pick="${id}">${names.map((n) => `<option ${n === v ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`;
  const da = state.detail[A], db = state.detail[B];
  ensureDetail(A); ensureDetail(B);
  const ra = o.runs.find((r) => r.run === A), rb = o.runs.find((r) => r.run === B);
  const pick = (r, path) => path.reduce((x, k) => (x == null ? null : x[k]), r?.latest);
  const metrics = [
    ["League pts (all)", ["league", "all", "pts"], ["league", "all", "se"], 1],
    ["Goal difference", ["league", "all", "gd"], ["league", "all", "gd_se"], 1],
    ["Conceded / match", ["league", "all", "ga"], null, -1],
    ["Scored / match", ["league", "all", "gf"], null, 1],
    ["Elite teams pts", ["league", "elite", "pts"], ["league", "elite", "se"], 1],
    ["Held-out teams pts", ["league", "held", "pts"], ["league", "held", "se"], 1],
    ["Best-move pts", ["greedy", "all", "pts"], ["greedy", "all", "se"], 1],
    ["vs RL Team 4", ["h2h", "RL Team 4", "pts"], ["h2h", "RL Team 4", "se"], 1],
    ["vs RL Team 5", ["h2h", "RL Team 5", "pts"], ["h2h", "RL Team 5", "se"], 1],
    ["Direction changes / s", ["behaviour", "dir_changes_s"], null, -1],
    ["Idle %", ["behaviour", "idle_pct"], null, -1],
    ["Spacing px", ["behaviour", "spacing_px"], null, 0],
  ];
  const rows = metrics.map(([label, p, se, better]) => {
    const va = pick(ra, p), vb = pick(rb, p), sa = se ? pick(ra, se) : null, sb = se ? pick(rb, se) : null;
    const diff = va != null && vb != null ? vb - va : null;
    const z = se ? zOf(vb, sb, va, sa) : null;
    const good = diff == null || better === 0 ? "" : diff * better > 0 ? "pos" : diff * better < 0 ? "neg" : "";
    return `<tr><td>${label}</td><td class="r">${f(va)}${sa != null ? `<span class="pm">±${f(sa)}</span>` : ""}</td><td class="r">${f(vb)}${sb != null ? `<span class="pm">±${f(sb)}</span>` : ""}</td><td class="r ${good}">${sgn(diff)}</td><td>${z !== null ? badge(verdictFromZ(z * (better || 1))) + ` <span class="pm">z ${f(z, 1)}</span>` : '<span class="muted">no error bar</span>'}</td></tr>`;
  }).join("");
  const ser = [];
  if (da) ser.push({ name: A + " · rule bots", color: runColor(A), points: (da.training || []).map((r) => ({ x: r.upd, y: r.rules })) });
  if (db) ser.push({ name: B + " · rule bots", color: runColor(B), points: (db.training || []).map((r) => ({ x: r.upd, y: r.rules })), dashed: true });
  const ev = [];
  for (const [n, d] of [[A, da], [B, db]]) if (d) ev.push({ name: n, color: runColor(n), points: d.evals.filter((e) => e.league.all).map((e) => ({ x: e.update, y: e.league.all.pts, err: e.league.all.se, hollow: e.kind === "fast", label: e.kind })), dots: true });
  return `<div class="head"><div><h1>Compare</h1><p>Second run minus first. A verdict needs a difference larger than 1.96 combined standard errors; smaller differences are noise.</p></div></div>
    <div class="pick">${sel("a", A)}<span class="muted">vs</span>${sel("b", B)}</div>
    <div class="card flush" style="margin-bottom:14px"><div class="tbl-wrap"><table><thead><tr><th>Metric (latest evaluation)</th><th class="r">${esc(A)}</th><th class="r">${esc(B)}</th><th class="r">Difference</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table></div></div>
    <div class="grid g2"><div class="card"><h2>Training points vs rule bots</h2>${lineChart(ser, { yMin: 0, yMax: 3, height: 230 })}</div>
    <div class="card"><h2>League points at each evaluation</h2>${lineChart(ev, { yMin: 0, yMax: 3, height: 230 })}</div></div>`;
}

function viewQueue() {
  const o = state.overview;
  if (!o) return '<div class="empty">Loading…</div>';
  const q = o.queue.map((s, i) => `<div class="qcard"><div class="n">${i + 1}</div><div><b>${esc(s.name)}</b> <span class="muted mono">${esc(s.file)}</span><p>${esc(s.notes)}</p>
    ${Object.entries(s.rewards).map(([k, v]) => `<span class="chip">${esc(k)} = ${esc(v)}</span>`).join("") || '<span class="chip">minimal rewards</span>'}<span class="chip">updates ${esc(s.updates ?? 300)}</span><span class="chip">lr ${esc(s.lr ?? "5e-5")}</span><span class="chip">from ${esc((s.start || "").split("/").pop())}</span></div></div>`).join("");
  const fin = o.runs.filter((r) => !r.run.startsWith("old_") && !r.run.startsWith("start:") && r.state !== "running");
  const done = fin.map((r) => `<tr class="link" data-run="${esc(r.run)}"><td><b>${esc(r.run)}</b></td><td>${badge(r.state)}</td><td>${r.verdict?.verdict ? badge(r.verdict.verdict) : ""}</td><td class="muted">${r.finished ? ago(r.finished) : ""}</td></tr>`).join("");
  return `<div class="head"><div><h1>Queue</h1><p>Specs in <span class="mono">exp/queue/</span> run in file-name order, one at a time. Add a JSON file there (or ask the agent) to queue an experiment.</p></div></div>
    <div class="grid g2"><div class="card flush"><h2>Waiting (${o.queue.length})</h2>${q || '<div class="empty">Queue empty</div>'}</div>
    <div class="card flush"><h2>Finished</h2><div class="tbl-wrap"><table><thead><tr><th>Run</th><th>State</th><th>Verdict</th><th>Finished</th></tr></thead><tbody>${done || '<tr><td colspan="4" class="muted">None yet</td></tr>'}</tbody></table></div></div></div>`;
}

function viewPi() {
  const o = state.overview, hl = state.health;
  if (!o) return '<div class="empty">Loading…</div>';
  if (!hl) { loadHealth(); }
  const sys = o.system, th = throttleText(sys.throttled);
  const rows = hl || [];
  const X = (r, i) => i;
  const lbl = (r) => r.t;
  const mk = (k) => rows.map((r, i) => ({ x: i, y: r[k], label: r.t }));
  const opts = { height: 210, xLabel: "sample" };
  return `<div class="head"><div><h1>Raspberry Pi</h1><p>From <span class="mono">logs/pi_health.log</span> (one sample every 10 s, last 12 hours). After a freeze the last samples show what the Pi was doing.</p></div></div>
    <div class="kpis">${kpi("Temperature", sys.temp != null ? `${f(sys.temp, 1)}<small>°C</small>` : "–")}${kpi("CPU load", `${f(sys.load[0], 1)}<small>/ 4</small>`, `5 min ${f(sys.load[1], 1)} · 15 min ${f(sys.load[2], 1)}`)}${kpi("Free memory", `${(sys.mem_avail_mb / 1024).toFixed(2)}<small>GB</small>`, `of ${(sys.mem_total_mb / 1024).toFixed(1)} GB`)}${kpi("Power / throttling", th.text, th.sub, th.cls)}${kpi("Uptime", dur(sys.uptime_s), "hardware watchdog on (15 s)")}</div>
    <div class="grid g2">
      <div class="card"><h2>Temperature °C</h2>${lineChart([{ name: "temperature", color: css("--orange"), points: mk("temp") }], { ...opts, refs: [{ y: 80, label: "throttles at 80" }] })}</div>
      <div class="card"><h2>CPU load (1 min)</h2>${lineChart([{ name: "load", color: css("--blue"), points: mk("load") }], { ...opts, yMin: 0, refs: [{ y: 4, label: "4 cores" }] })}</div>
      <div class="card"><h2>Free memory MB</h2>${lineChart([{ name: "free", color: css("--accent"), points: mk("mem") }], { ...opts, yMin: 0 })}</div>
      <div class="card"><h2>CPU clock MHz</h2>${lineChart([{ name: "clock", color: css("--purple"), points: mk("clock") }], { ...opts, yMin: 0 })}</div>
    </div>`;
}


// ---------- live match (streamed from the Pi's viewer, drawn here) ----------
const live = { es: null, meta: null, frames: [], trail: [], raf: 0, recv: [], idleAge: null, lastFrameAt: 0, sideAt: 0, cam: null,
  follow: (() => { try { return localStorage.getItem("liveFollow") !== "0"; } catch (e) { return true; } })() };
function viewLive() {
  return `<div class="head live-head"><div><h1>Live match</h1><p>The match the Pi's viewer is playing, drawn in your browser from a stream of positions (about 30 per second). The Pi does not encode video, so this costs training almost nothing.</p></div></div>
    <div class="live-wrap">
      <div class="card live-main"><div class="scorebar" id="lv-sb"><div class="tm"><i class="kit"></i><span>–</span></div><div class="mid"><div class="score">– : –</div><div class="clock">–</div></div><div class="tm r"><span>–</span><i class="kit"></i></div></div>
        <canvas id="lv-c" width="1400" height="710"></canvas><div class="lv-over" id="lv-over">Waiting for the Pi's viewer…</div></div>
      <div class="card live-side"><div id="lv-prog"></div><div class="seg" id="lv-cam"><button data-cam="1">Follow ball</button><button data-cam="0">Whole pitch</button></div><dl class="kv" id="lv-side"><dt>stream</dt><dd>connecting…</dd></dl></div>
    </div>`;
}
function startLive() {
  if (!live.es) {
    live.es = new EventSource("/api/live");
    live.es.addEventListener("meta", (e) => { live.meta = JSON.parse(e.data); liveSide(); });
    live.es.addEventListener("idle", (e) => { live.idleAge = +e.data; liveSide(); });
    live.es.onmessage = (e) => {
      const fr = JSON.parse(e.data), now = performance.now();
      fr.at = now;
      const last = live.frames[live.frames.length - 1];
      if (last && (last.id !== fr.id || fr.t < last.t)) { live.frames = []; live.trail = []; }
      live.frames.push(fr);
      if (live.frames.length > 12) live.frames.shift();
      live.recv.push(now);
      while (live.recv.length && now - live.recv[0] > 2000) live.recv.shift();
      live.idleAge = 0; live.lastFrameAt = now;
    };
    live.es.onerror = () => { live.idleAge = null; };
  }
  if (!live.raf) live.raf = requestAnimationFrame(liveDraw);
  liveSide();
}
function stopLive() {
  if (live.es) { live.es.close(); live.es = null; }
  if (live.raf) { cancelAnimationFrame(live.raf); live.raf = 0; }
  live.frames = []; live.trail = [];
}
function clockText(s) { s = Math.max(0, Math.ceil(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
function liveSide() {
  const pr = $("#lv-prog"), now = state.overview?.now;
  if (pr) pr.innerHTML = now ? `<div class="live-prog"><div class="row"><span>${esc(now.run)}${now.eval ? " · evaluating" : ""}</span><b>${now.update ?? 0} / ${now.target ?? "?"}</b></div>
      <div class="progress"><i style="width:${now.target ? Math.min(100, (100 * (now.update || 0)) / now.target) : 0}%"></i></div>
      <div class="row" style="margin-top:6px"><span>training pts vs rules</span><b>${f(now.train_pts)}</b></div><div class="row"><span>time left</span><b>${now.eta_s ? dur(now.eta_s) : "–"}</b></div></div>` : "";
  for (const bt of document.querySelectorAll("#lv-cam button")) bt.classList.toggle("on", (bt.dataset.cam === "1") === live.follow);
  const el = $("#lv-side"); if (!el) return;
  const m = live.meta, fps = live.recv.length / 2;
  const fresh = live.lastFrameAt && performance.now() - live.lastFrameAt < 3000;
  const last = live.frames[live.frames.length - 1];
  let rows = `<dt>stream</dt><dd class="${fresh ? "pos" : "neg"}">${fresh ? `live · ${fps.toFixed(0)} frames/s` : live.es ? "no frames from the Pi" : "closed"}</dd>`;
  if (m) {
    const runName = m.tag && m.tag.startsWith("x_") ? m.tag.slice(2) : m.tag;
    rows += `<dt>run</dt><dd><a href="#/run/${encodeURIComponent(runName)}">${esc(runName)}</a></dd><dt>net playing</dt><dd class="mono">${esc(m.playing || "–")}</dd><dt>training update</dt><dd>${esc(m.upd)}</dd>
      <dt>moves</dt><dd>${m.best_move ? "best move (greedy)" : "sampled (as in training)"}</dd><dt>checkpoint</dt><dd>${m.best_ckpt ? "best of the run" : "newest"}</dd>
      <dt>left team</dt><dd>${m.teams[0].net ? "the run's net" : "rule bot"} <span class="muted">(kit of ${esc(m.teams[0].name)})</span></dd><dt>right team</dt><dd>${esc(m.teams[1].name)}</dd>`;
  }
  if (last && last.paused) rows += `<dt>note</dt><dd class="neg">paused: the Pi's viewer is on another page</dd>`;
  el.innerHTML = rows;
}
function liveDraw() {
  live.raf = requestAnimationFrame(liveDraw);
  const cv = $("#lv-c"), m = live.meta;
  if (!cv) return;
  const over = $("#lv-over");
  if (!m || !live.frames.length) { over.hidden = false; over.innerHTML = live.es ? "Waiting for the Pi's viewer…<small>the Godot viewer must be running on the Pi</small>" : "Stream closed"; return; }
  const P = m.pitch, dpr = window.devicePixelRatio || 1, cssW = cv.clientWidth || 800, cssH = cssW * P.out_y / P.out_x;
  if (cv.width !== Math.round(cssW * dpr) || cv.height !== Math.round(cssH * dpr)) { cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr); }
  const ctx = cv.getContext("2d");
  // state at "now - 70 ms", interpolated between the two frames around it
  const rt = performance.now() - 70, fr = live.frames;
  let a = fr[fr.length - 1], b = a, u = 0;
  for (let i = fr.length - 1; i > 0; i--) if (fr[i - 1].at <= rt) { a = fr[i - 1]; b = fr[i]; u = Math.min(1, Math.max(0, (rt - a.at) / Math.max(b.at - a.at, 1))); break; }
  if (a.p.length !== b.p.length) { a = b; u = 0; }
  const L = (x, y) => x + (y - x) * u;
  const ball = [L(a.b[0], b.b[0]), L(a.b[1], b.b[1])];
  // camera: the whole pitch, or zoomed in and following the ball (smoothed, kept inside the pitch's outer area)
  const zoom = live.follow ? 1.9 : 1, k = (cv.width / (2 * P.out_x)) * zoom;
  const vx = P.out_x / zoom, vy = P.out_y / zoom;
  const target = live.follow ? [Math.max(-P.out_x + vx, Math.min(P.out_x - vx, ball[0])), Math.max(-P.out_y + vy, Math.min(P.out_y - vy, ball[1]))] : [0, 0];
  if (!live.cam) live.cam = target.slice();
  live.cam[0] += (target[0] - live.cam[0]) * 0.12; live.cam[1] += (target[1] - live.cam[1]) * 0.12;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = shade("#" + P.outer, -0.25); ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.setTransform(k, 0, 0, k, cv.width / 2 - live.cam[0] * k, cv.height / 2 - live.cam[1] * k);
  // pitch
  const hw = P.half_w, hh = P.half_h;
  ctx.fillStyle = "#" + P.outer; ctx.fillRect(-P.out_x, -P.out_y, 2 * P.out_x, 2 * P.out_y);
  const n = Math.max(P.stripes, 1), sw = (2 * hw) / n;
  for (let i = 0; i < n; i++) { ctx.fillStyle = P.stripes > 0 && i % 2 === 0 ? shade("#" + P.pitch, -0.07) : "#" + P.pitch; ctx.fillRect(-hw + i * sw, -hh, sw + 0.5, 2 * hh); }
  for (let t = 0; t < 2; t++) {                       // nets, in the colour of the team defending them
    const sx = t === 0 ? -1 : 1, x0 = sx * hw, x1 = sx * (hw + P.net_depth), col = "#" + m.teams[t].primary;
    ctx.fillStyle = shade("#" + P.pitch, -0.2); ctx.fillRect(Math.min(x0, x1), -P.goal_half, P.net_depth, 2 * P.goal_half);
    ctx.strokeStyle = col; ctx.globalAlpha = 0.45; ctx.lineWidth = 1; ctx.beginPath();
    for (let g = 0; g <= P.net_depth; g += 10) { ctx.moveTo(x0 + sx * g, -P.goal_half); ctx.lineTo(x0 + sx * g, P.goal_half); }
    for (let g = -P.goal_half; g <= P.goal_half; g += 10) { ctx.moveTo(x0, g); ctx.lineTo(x1, g); }
    ctx.stroke(); ctx.globalAlpha = 1;
    ctx.lineWidth = 6; ctx.strokeStyle = "rgba(0,0,0,.7)"; ctx.strokeRect(Math.min(x0, x1), -P.goal_half, P.net_depth, 2 * P.goal_half);
    ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.strokeRect(Math.min(x0, x1), -P.goal_half, P.net_depth, 2 * P.goal_half);
  }
  ctx.strokeStyle = "#" + P.line; ctx.lineWidth = 3;
  ctx.strokeRect(-hw, -hh, 2 * hw, 2 * hh);
  ctx.beginPath(); ctx.moveTo(0, -hh); ctx.lineTo(0, hh); ctx.stroke();
  ctx.beginPath(); ctx.arc(0, 0, P.center_r, 0, 2 * Math.PI); ctx.stroke();
  ctx.fillStyle = "#" + P.line; ctx.beginPath(); ctx.arc(0, 0, 4, 0, 2 * Math.PI); ctx.fill();
  if (P.box_depth > 0) { ctx.lineWidth = 2.5; ctx.strokeRect(-hw, -P.box_half, P.box_depth, 2 * P.box_half); ctx.strokeRect(hw - P.box_depth, -P.box_half, P.box_depth, 2 * P.box_half); }
  for (const px of [-hw, hw]) for (const py of [-P.goal_half, P.goal_half]) disc(ctx, px, py, P.post_r, "#f2f2f2", "#000", 2);
  // ball trail
  live.trail.push(ball); if (live.trail.length > 14) live.trail.shift();
  for (let i = 0; i < live.trail.length - 1; i++) { ctx.globalAlpha = (i / live.trail.length) * 0.35; disc(ctx, live.trail[i][0], live.trail[i][1], m.ball_r * (0.4 + 0.5 * i / live.trail.length), "#fff"); }
  ctx.globalAlpha = 1;
  // players
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  m.players.forEach((pl, i) => {
    if (2 * i + 1 >= a.p.length) return;
    const x = L(a.p[2 * i], b.p[2 * i]), y = L(a.p[2 * i + 1], b.p[2 * i + 1]), tm = m.teams[pl.team], r = pl.r;
    ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.clip();
    ctx.fillStyle = "#" + tm.primary; ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
    ctx.fillStyle = "#" + tm.secondary;
    if (tm.pattern === "stripes") { ctx.fillRect(x - 0.55 * r, y - r, 0.35 * r, 2 * r); ctx.fillRect(x + 0.2 * r, y - r, 0.35 * r, 2 * r); }
    else if (tm.pattern === "halves") ctx.fillRect(x, y - r, r, 2 * r);
    else if (tm.pattern === "hoops") { ctx.fillRect(x - r, y - 0.55 * r, 2 * r, 0.35 * r); ctx.fillRect(x - r, y + 0.2 * r, 2 * r, 0.35 * r); }
    else if (tm.pattern === "band") ctx.fillRect(x - 0.3 * r, y - r, 0.6 * r, 2 * r);
    ctx.restore();
    ctx.lineWidth = 2.5; ctx.strokeStyle = "#000"; ctx.beginPath(); ctx.arc(x, y, r - 1, 0, 2 * Math.PI); ctx.stroke();
    // centre the digits on their real ink height ("middle" uses the font's em box, which puts digits a bit low)
    ctx.font = `700 ${Math.round(r * 0.95)}px system-ui, sans-serif`; ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,.85)";
    ctx.textBaseline = "alphabetic";
    const txt = String(pl.n), mt = ctx.measureText(txt), ty = y + (mt.actualBoundingBoxAscent - mt.actualBoundingBoxDescent) / 2;
    ctx.strokeText(txt, x, ty); ctx.fillStyle = "#fff"; ctx.fillText(txt, x, ty);
  });
  disc(ctx, ball[0], ball[1], m.ball_r, "#fff", "#000", 2);
  // scoreboard and banners
  const sb = $("#lv-sb");
  if (sb) {
    const runName = m.tag && m.tag.startsWith("x_") ? m.tag.slice(2) : m.tag;
    const t0 = { ...m.teams[0], name: m.teams[0].net && runName ? `${runName} · ${(m.playing || "").replace(/^.*_u/, "u")}` : m.teams[0].name }, t1 = m.teams[1];
    const key = `${t0.name}|${t1.name}|${b.sc}|${Math.ceil(b.tl)}|${b.st}`;
    if (sb.dataset.key !== key) {
      sb.dataset.key = key;
      sb.innerHTML = `<div class="tm"><i class="kit" style="background:#${t0.primary}"></i><span>${esc(t0.name)}</span></div><div class="mid"><div class="score">${b.sc[0]} : ${b.sc[1]}</div><div class="clock">${b.st === 2 ? "full time" : clockText(b.tl)}</div></div><div class="tm r"><span>${esc(t1.name)}</span><i class="kit" style="background:#${t1.primary}"></i></div>`;
    }
  }
  const stale = performance.now() - live.lastFrameAt > 3000;
  if (b.st === 1) { over.hidden = false; over.innerHTML = `GOAL<small>${esc(m.teams[b.gt]?.name || "")}</small>`; }
  else if (b.st === 2) { over.hidden = false; over.innerHTML = `FULL TIME<small>${b.sc[0]} : ${b.sc[1]}</small>`; }
  else if (b.paused) { over.hidden = false; over.innerHTML = "PAUSED<small>the Pi's viewer is on another page</small>"; }
  else if (stale) { over.hidden = false; over.innerHTML = "NO SIGNAL<small>waiting for the Pi's viewer</small>"; }
  else over.hidden = true;
  if (performance.now() - live.sideAt > 1000) { live.sideAt = performance.now(); liveSide(); }
}
function disc(ctx, x, y, r, fill, stroke, lw) {
  ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fillStyle = fill; ctx.fill();
  if (stroke) { ctx.lineWidth = lw || 2; ctx.strokeStyle = stroke; ctx.stroke(); }
}
function shade(hex, amt) {
  const v = parseInt(hex.slice(1), 16), f2 = (c) => Math.max(0, Math.min(255, Math.round(c * (1 + amt))));
  return `rgb(${f2(v >> 16)},${f2((v >> 8) & 255)},${f2(v & 255)})`;
}

// ---------- data loading ----------
const pending = {};
function ensureDetail(name) {
  if (pending[name] || (state.detail[name] && Date.now() - state.detail[name]._t < POLL_MS)) return;
  pending[name] = true;
  getJSON("/api/run/" + encodeURIComponent(name)).then((d) => { d._t = Date.now(); state.detail[name] = d; render(); }).catch(() => {}).finally(() => { delete pending[name]; });
}
function loadHealth() {
  if (pending._h) return;
  pending._h = true;
  getJSON("/api/health").then((d) => { state.health = d; render(); }).catch(() => {}).finally(() => { delete pending._h; });
}
async function poll() {
  try {
    state.overview = await getJSON("/api/overview");
    state.lastOk = Date.now();
    setPulse(true, "live");
    const r = route();
    if (r.view === "run") state.detail[r.arg] && (state.detail[r.arg]._t = 0);
    if (r.view === "pi") state.health = null;
    if (r.view === "compare") for (const k of ["a", "b"]) { const n = r.params.get(k); if (n && state.detail[n]) state.detail[n]._t = 0; }
    if (state.overview.now && state.detail[state.overview.now.run]) state.detail[state.overview.now.run]._t = 0;
    render();
  } catch (e) {
    setPulse(false, state.lastOk ? "offline · " + dur((Date.now() - state.lastOk) / 1000) : "offline");
  }
}

// ---------- routing ----------
function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const parts = path.split("/");
  const params = new URLSearchParams(qs || "");
  if (parts[0] === "run" && parts[1]) return { view: "run", arg: decodeURIComponent(parts.slice(1).join("/")), params };
  return { view: ["runs", "compare", "queue", "pi", "live"].includes(parts[0]) ? parts[0] : "overview", params };
}
let lastHTML = "";
function render() {
  const r = route();
  for (const a of document.querySelectorAll("#nav a")) a.classList.toggle("on", a.dataset.v === (r.view === "run" ? "runs" : r.view));
  const before = new Set(Object.keys(chartData));
  if (r.view !== "live") stopLive();
  const html = r.view === "live" ? viewLive() : r.view === "runs" ? viewRuns() : r.view === "run" ? viewRun(r.arg) : r.view === "compare" ? viewCompare(r.params) : r.view === "queue" ? viewQueue() : r.view === "pi" ? viewPi() : viewOverview();
  const cleaned = html.replace(/data-chart="c[a-z0-9]+"/g, "");
  const drop = (keep) => { for (const k of Object.keys(chartData)) if (before.has(k) !== keep) delete chartData[k]; };
  if (cleaned === lastHTML) { drop(true); return; }      // nothing changed: keep scroll, selection and hover (and the old charts' data)
  drop(false);
  lastHTML = cleaned;
  const view = $("#view");
  view.innerHTML = html;
  attachCharts(view);
  if (r.view === "live") { live.raf && cancelAnimationFrame(live.raf); live.raf = 0; startLive(); }
  document.title = (r.view === "run" ? r.arg + " · " : "") + "Soccer Lab";
}
document.addEventListener("click", (e) => {
  const cam = e.target.closest("button[data-cam]");
  if (cam) { live.follow = cam.dataset.cam === "1"; try { localStorage.setItem("liveFollow", live.follow ? "1" : "0"); } catch (err) {} liveSide(); }
  const tr = e.target.closest("tr[data-run]");
  if (tr && !e.target.closest("a")) location.hash = "#/run/" + encodeURIComponent(tr.dataset.run);
  const th = e.target.closest("th[data-sort]");
  if (th) {
    const k = th.dataset.sort;
    state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : k === "run" || k === "state" ? 1 : -1 };
    render();
  }
});
document.addEventListener("change", (e) => {
  const s = e.target.closest("select[data-pick]");
  if (!s) return;
  const p = route().params;
  p.set(s.dataset.pick, s.value);
  location.hash = "#/compare?" + p.toString();
});
window.addEventListener("hashchange", () => { lastHTML = ""; window.scrollTo(0, 0); render(); });
if (new URLSearchParams(location.search).has("kiosk")) {                                      // the Pi's touch screen: opens on the live match
  document.body.classList.add("kiosk");
  history.replaceState(null, "", location.pathname + location.search + "#/live");             // always start on Live (also after a restore)
}
function setThemeButton() { $("#theme").textContent = document.documentElement.dataset.theme === "light" ? "☾" : "☀"; }
$("#theme").addEventListener("click", () => {
  const light = document.documentElement.dataset.theme !== "light";
  if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("theme", light ? "light" : "dark"); } catch (e) {}
  setThemeButton(); lastHTML = ""; render();
});
setThemeButton();
poll();
setInterval(poll, POLL_MS);
