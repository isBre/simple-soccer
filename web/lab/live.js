// The Lab (web/lab/core.js has the overview): the Live page.
"use strict";

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
