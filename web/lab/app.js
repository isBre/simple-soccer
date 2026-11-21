// The Lab (web/lab/core.js has the overview): data polling, routing, events and start-up (loaded last).
"use strict";

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
  getJSON("/api/health?hours=" + state.healthHours).then((d) => { state.health = d; render(); }).catch(() => {}).finally(() => { delete pending._h; });
}
async function poll() {
  if (route().view === "game") return;                       // the Game area needs none of this
  try {
    state.ov = await getJSON("/api/overview");
    state.lastOk = Date.now(); state.firstFail = 0;
    const r = route();
    if (r.view === "run" && state.detail[r.arg]) state.detail[r.arg]._t = 0;
    if (r.view === "machine") state.health = null;
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
  const p = $("#pulse"), off = $("#offline"), chip = $("#machinechip"), s = state.ov?.status?.machine;
  p.className = "pulse " + (ok ? "ok" : "err");
  if (chip && s) { chip.innerHTML = `<i class="${s.temp_c > tempWarn(s) || (s.throttled && s.throttled !== "0x0") || s.thermal > 0 ? "warn" : "ok"}"></i>${f(s.temp_c, 0)}°C · load ${f(s.load_1m, 1)}`; chip.title = machineName(s); }
  const down = !ok && state.firstFail && Date.now() - state.firstFail > 25000;
  off.hidden = !down;
  if (down) off.innerHTML = `<b>The ${esc(machineName(s))} stopped answering</b>${state.lastOk ? " · last data " + new Date(state.lastOk).toLocaleTimeString() + " (" + dur((Date.now() - state.lastOk) / 1000) + " ago)" : ""}${s?.watchdog !== false ? " · if it froze, the watchdog reboots it and the runner resumes" : " · if it slept or rebooted, start the runner again"}`;
}

// ---------- routing and events ----------
function route() {
  const h = location.hash.replace(/^#\/?/, ""), [path, qs] = h.split("?"), parts = path.split("/"), params = new URLSearchParams(qs || "");
  if (parts[0] === "run" && parts[1]) return { view: "run", arg: decodeURIComponent(parts[1]), tab: parts[2], params };
  if (parts[0] === "dataset") return { view: "dataset", arg: parts[1] ? decodeURIComponent(parts[1]) : "", params };
  if (parts[0] === "docs") return { view: "docs", arg: parts[1] ? decodeURIComponent(parts[1]) : "", params };
  if (parts[0] === "game") return { view: "game", parts: parts.slice(1), params };
  return { view: ["runs", "compare", "machine", "live", "ranking"].includes(parts[0]) ? parts[0] : "now", params };
}
let lastHTML = "";
function render() {
  if (!window.Game) return;                      // web/game.js (an ES module) runs after these scripts; start() renders once it is there
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
  const html = r.view === "live" ? viewLive() : r.view === "runs" ? viewRuns() : r.view === "run" ? viewRun(r.arg, r.tab) : r.view === "compare" ? viewCompare(r.params) : r.view === "machine" ? viewMachine() : r.view === "docs" ? viewDocs(r.arg) : r.view === "dataset" ? viewDataset(r.arg) : r.view === "ranking" ? viewRanking() : viewNow();
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
  if (hrs) { state.healthHours = +hrs.dataset.hours; state.health = null; rerender(); return; }
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
function start() { render(); setInterval(poll, POLL_MS); }
if (window.Game) start(); else window.addEventListener("game-ready", start, { once: true });
// the kiosk keeps one page open for days: reload it when the dashboard's files changed on the Pi
let pageVersion = null;
setInterval(async () => {
  try { const v = (await (await fetch("/api/version")).json()).v; if (pageVersion === null) pageVersion = v; else if (v !== pageVersion) location.reload(); } catch (e) {}
}, 30000);
