// The Lab (web/lab/core.js has the overview): the Live page and the Live card on Now.
// The live demo match (lab/live.py) streams the Game's own match data (game/session.py meta / frame, kickoff intro included); the
// dashboard relays it as server-sent events and the Game's renderer draws it (Game.viewer = web/game/render.js), so Live looks and
// moves exactly like a match in the Game. One stream feeds every view on the page (the Live page, the card on Now).
"use strict";

const FS_ICON = [   // enter / leave full screen
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>'];
const live = { es: null, meta: null, frames: [], recv: [], lastFrameAt: 0, views: [], raf: 0, infoAt: 0, mode: "match",
  follow: (() => { try { return localStorage.getItem("liveFollow") !== "0"; } catch (e) { return true; } })() };
const CARD_ZOOM = 2.2;               // the Now card is small: its camera follows the ball closer than the Game's
const LIVE_DELAY_MS = 60;            // drawn this far behind the newest frame: the stream has 30 frames/s, the screen 60+

// ---------- the stream ----------
function startLive() {
  if (live.es) return;
  live.es = new EventSource("/api/live");
  live.es.addEventListener("meta", (e) => {
    const m = JSON.parse(e.data);
    if (!m.teams?.[0]?.kit) return;                                                       // a stream from an older lab/live.py: not the Game's format
    if (live.meta && live.meta.id === m.id) { live.meta.upd = m.upd; return; }           // the same match: sent again every second
    Game.viewer.prepareMeta(live, m);                                                     // sets live.meta (kits, goal colours, players by uid)
    live.frames.length = 0;
    for (const M of live.views) resetView(M);
  });
  live.es.onmessage = (e) => {
    const fr = JSON.parse(e.data), last = live.frames[live.frames.length - 1];
    if (last && (last.id !== fr.id || fr.t < last.t)) live.frames.length = 0;              // a new match
    fr.at = performance.now();
    for (const M of live.views) {
      for (const ev of fr.ev || []) Game.viewer.onGoal(M, ev);
      if (fr.st === 1 && last && last.st !== 1 && !(fr.ev || []).length) Game.viewer.onGoal(M, { team: fr.gt, scorer_name: "" });   // the goal frame was dropped
    }
    live.frames.push(fr); if (live.frames.length > 12) live.frames.shift();
    live.recv.push(fr.at); while (live.recv.length && fr.at - live.recv[0] > 2000) live.recv.shift();
    live.lastFrameAt = fr.at;
  };
  if (!live.raf) live.raf = requestAnimationFrame(liveLoop);
}
function stopLive() {
  if (live.es) { live.es.close(); live.es = null; }
  cancelAnimationFrame(live.raf); live.raf = 0;
  live.meta = null; live.frames.length = 0; live.views = [];
}
// every <canvas data-live="page|card"> on the page becomes a view of the stream (called after every render)
function mountLive(root) {
  const canvases = [...root.querySelectorAll("canvas[data-live]")];
  live.views = live.views.filter((M) => M.cv.isConnected);
  if (!canvases.length) { if (!live.views.length) stopLive(); return; }
  for (const cv of canvases) if (!live.views.some((M) => M.cv === cv)) live.views.push(resetView({ cv, card: cv.dataset.live === "card" }));
  startLive();
  if (root.querySelector("#lv-opp")) loadOpponents();
  liveInfo();
}
function resetView(M) {
  return Object.assign(M, { viewer: true, p: {}, meta: live.meta, frames: live.frames, cam: null, parts: [], mes: [], goal: null, lastStep: 0, partAcc: 0,
    paused: false, delay: LIVE_DELAY_MS, zoom: M.card ? CARD_ZOOM : live.follow ? "" : "fit", noHud: M.card, waitText: "Waiting for the live match…" });
}
function liveLoop(ts) {
  live.raf = requestAnimationFrame(liveLoop);
  for (const M of live.views) { M.meta = live.meta; Game.viewer.drawMatch(M, ts); }
  if (ts - live.infoAt > 1000) { live.infoAt = ts; liveInfo(); }
}

// ---------- who plays, and their ratings ----------
// our side: the run's checkpoint (its own rating if it has one, else the run's newest estimate); the opponent: a player, a team or a
// checkpoint of the ratings, found by its id or by its net file
function liveSides() {
  const m = live.meta; if (!m || !m.elo) return null;
  const rows = rk.data?.rows || [], find = (e) => rows.find((r) => r.id === e.id && r.games) || (e.model ? rows.find((r) => r.model === e.model && r.games && r.entry !== "team") : null);
  const run = m.tag && m.tag.startsWith("x_") ? m.tag.slice(2) : m.tag, row = (state.ov?.runs || []).find((r) => r.name === run), est = row?.elo_estimate;
  const own = find(m.elo[0]), opp = find(m.elo[1]);
  return [
    { name: m.teams[0].name, run, kind: own ? eloKind(own.entry) : "checkpoint Elo", elo: own ? own.elo : est?.elo, pm: own ? 1.96 * own.se : est ? 1.96 * est.se : null, est: !own && !!est },
    { name: m.teams[1].name, kind: opp ? eloKind(opp.entry) : "not rated", elo: opp?.elo, pm: opp ? 1.96 * opp.se : null, est: false },
  ];
}
const sideLine = (s) => `<div class="lv-team"><span class="nm">${esc(s.name)}</span><span>${eloText(s.elo, s.pm, s.est)}</span><span class="muted small">${esc(s.kind)}${s.est ? " · estimate" : ""}</span></div>`;
// the parts that change while the page stays (every second): the Live page's side panel and the Now card's footer
function liveInfo() {
  loadRanking();
  const fr = live.frames[live.frames.length - 1], m = live.meta, fresh = live.lastFrameAt && performance.now() - live.lastFrameAt < 3000, sides = liveSides();
  const score = m && fr ? `${fr.sc[0]} – ${fr.sc[1]}` : "– : –", clock = fr ? (fr.st === 2 ? "full time" : (m?.mode === "puzzle" ? "puzzle · " : "") + clockText(fr.tl)) : "";
  const card = $("#lc-foot");
  if (card) card.innerHTML = sides ? `<div class="lc-score"><span class="nm">${esc(sides[0].name)}</span><b>${score}</b><span class="nm r">${esc(sides[1].name)}</span></div>
      <div class="lc-elo"><span>${eloText(sides[0].elo, null, sides[0].est)} <span class="muted">${esc(sides[0].kind)}</span></span><span class="muted">${esc(clock)}</span><span>${eloText(sides[1].elo)} <span class="muted">${esc(sides[1].kind)}</span></span></div>`
    : `<div class="muted small">${fresh && m ? "starting…" : "No live match: it plays the newest checkpoint of this machine's current run"}</div>`;
  const el = $("#lv-info"); if (!el) return;
  const run = state.ov?.status?.runner?.running, fps = live.recv.length / 2;
  const prog = run ? `<div class="lv-prog"><div class="eyebrow">Training · ${esc(run.run)}</div><div class="progress"><i style="width:${run.target ? Math.min(100, (100 * (run.update || 0)) / run.target) : 0}%"></i></div>
      <div class="muted small">update ${run.update ?? 0} / ${run.target ?? "?"} · ${run.evaluating ? "evaluating…" : run.eta_hours != null ? dur(run.eta_hours * 3600) + " left" : ""}</div></div>` : '<div class="muted small">Nothing is training.</div>';
  el.innerHTML = `${prog}<div class="lv-sides"><div class="eyebrow">This match</div>${sides ? sideLine(sides[0]) + sideLine(sides[1]) : '<div class="muted small">waiting for the match…</div>'}</div>
    <div class="muted small">${fresh ? `live · ${fps.toFixed(0)} frames/s` : '<span class="neg">no frames</span>'}${m ? ` · ${esc(m.playing || "")}` : ""}</div>`;
}

// ---------- the Live page ----------
function viewLive() {
  return `<div class="live-wrap fit">
      <div class="live-main"><canvas data-live="page"></canvas>
        <button class="fs-btn" data-fs title="Full screen" aria-label="Full screen">${FS_ICON[document.body.classList.contains("live-fs") ? 1 : 0]}</button></div>
      <aside class="card live-side"><div id="lv-info"></div>
        <div class="lv-ctl"><div class="eyebrow">Mode</div>${seg("livemode", [["match", "Match"], ["puzzle", "Puzzle"]], live.mode)}
          <div class="eyebrow">Camera</div>${seg("livecam", [["1", "Follow ball"], ["0", "Whole pitch"]], live.follow ? "1" : "0")}
          <div class="eyebrow">Opponent of the next match</div><select id="lv-opp" aria-label="Opponent of the next match"><option>…</option></select></div>
        <p class="muted small">Puzzle: a random layout of every player and the ball, 60 s, over at the first goal.</p></aside>
    </div>`;
}
onSeg.livemode = (v) => { live.mode = v; rerender(); fetch("/api/live/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: v }) }).catch(() => {}); };
onSeg.livecam = (v) => {
  live.follow = v === "1"; try { localStorage.setItem("liveFollow", v); } catch (e) {}
  for (const M of live.views) if (!M.card) M.zoom = live.follow ? "" : "fit";   // the Now card always follows the ball, closer
  rerender();
};
// the opponent of the demo match: "random" (default) draws a handmade team or an earlier run for every match; a pinned choice applies from the next match
async function loadOpponents() {
  const sel = $("#lv-opp"); if (!sel) return;
  try {
    const d = await getJSON("/api/live/opponents"), groups = {};
    if (d.mode && d.mode !== live.mode) { live.mode = d.mode; rerender(); return; }
    for (const o of d.opponents) (groups[o.group] = groups[o.group] || []).push(o);
    sel.innerHTML = Object.entries(groups).map(([g, os]) => `<optgroup label="${esc(g)}">${os.map((o) => `<option value="${esc(o.id)}"${o.id === d.selected ? " selected" : ""}>${esc(o.label)}${o.tier ? " · " + esc(o.tier) : ""}</option>`).join("")}</optgroup>`).join("");
  } catch (e) { sel.innerHTML = "<option>unavailable</option>"; }
}
document.addEventListener("change", (e) => {
  if (e.target.id !== "lv-opp") return;
  fetch("/api/live/opponent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: e.target.value }) }).catch(() => {});
});
// full screen (like a video player): only the match; the browser goes full screen too when it can. The button or Esc leaves it.
function toggleFullscreen(on) {
  on = on ?? !document.body.classList.contains("live-fs");
  document.body.classList.toggle("live-fs", on);
  try {
    if (on && !document.fullscreenElement && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  } catch (e) {}
  const b = $("[data-fs]"); if (b) { b.innerHTML = FS_ICON[on ? 1 : 0]; b.title = on ? "Exit full screen" : "Full screen"; }
}
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && document.body.classList.contains("live-fs")) toggleFullscreen(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("live-fs")) toggleFullscreen(false); });
