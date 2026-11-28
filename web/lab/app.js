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
    if (r.view === "events") loadEvents(true);
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
  if (chip && s) { chip.innerHTML = `<i class="${s.temp_c > tempWarn(s) || s.thermal > 0 ? "warn" : "ok"}"></i>${f(s.temp_c, 0)}°C · load ${f(s.load_1m, 1)}`; chip.title = machineName(s); }
  const down = !ok && state.firstFail && Date.now() - state.firstFail > 25000;
  off.hidden = !down;
  if (down) off.innerHTML = `<b>The ${esc(machineName(s))} stopped answering</b>${state.lastOk ? " · last data " + new Date(state.lastOk).toLocaleTimeString() + " (" + dur((Date.now() - state.lastOk) / 1000) + " ago)" : ""} · if it slept or rebooted, start the runner again (lab/run.sh)`;
}

// ---------- routing ----------
const VIEWS = { now: () => viewNow(), live: () => viewLive(), runs: () => viewRuns(), run: (r) => viewRun(r.arg, r.tab), compare: (r) => viewCompare(r.params),
  ranking: () => viewRanking(), events: () => viewEvents(), dataset: (r) => viewDataset(r.arg), machine: () => viewMachine(), docs: (r) => viewDocs(r.arg) };
function route() {
  const h = location.hash.replace(/^#\/?/, ""), [path, qs] = h.split("?"), parts = path.split("/"), params = new URLSearchParams(qs || "");
  if (parts[0] === "run" && parts[1]) return { view: "run", arg: decodeURIComponent(parts[1]), tab: parts[2], params };
  if (parts[0] === "dataset" || parts[0] === "docs") return { view: parts[0], arg: parts[1] ? decodeURIComponent(parts[1]) : "", params };
  if (parts[0] === "game") return { view: "game", parts: parts.slice(1), params };
  return { view: VIEWS[parts[0]] && parts[0] !== "run" ? parts[0] : "now", params };
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
  Game.stopMatch(); Music.stop(0.6);                       // the Lab makes no sound
  if (!state.ov && !state.firstFail && !pending._ov) { pending._ov = true; poll().finally(() => { delete pending._ov; }); }
  for (const a of document.querySelectorAll("[data-v]")) a.classList.toggle("on", a.dataset.v === (r.view === "run" ? "runs" : r.view));
  document.body.dataset.view = r.view;
  if (!(r.view === "dataset" && r.arg)) stopReplay();
  const before = new Set(Object.keys(chartData));
  const html = VIEWS[r.view](r);
  const cleaned = html.replace(/data-chart="c[a-z0-9]+"/g, "");
  const drop = (keep) => { for (const k of Object.keys(chartData)) if (before.has(k) !== keep) delete chartData[k]; };
  if (cleaned === lastHTML) { drop(true); return; }
  drop(false);
  lastHTML = cleaned;
  const view = $("#view"), active = document.activeElement, focus = active && active.dataset && active.dataset.filter !== undefined, caret = focus ? active.selectionStart : 0;
  view.innerHTML = html;
  attachCharts(view);
  mountLive(view);
  if (focus) { const i = $(`[data-filter="${active.dataset.filter}"]`) || $("[data-filter]"); if (i) { i.focus(); i.setSelectionRange(caret, caret); } }
  if (r.view === "dataset" && r.arg) startReplay(r.arg);
  document.title = (r.view === "run" ? r.arg + " · " : "") + "Soccer Lab · Simple Soccer";
  const dl = $("#runlist");
  if (dl && state.ov) dl.innerHTML = state.ov.runs.map((x) => `<option value="${esc(x.name)}">`).join("");
}
function rerender() { lastHTML = ""; render(); }

// ---------- events ----------
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("[data-fs]")) { toggleFullscreen(); return; }
  const sg = t.closest("button[data-seg]");
  if (sg) { onSeg[sg.dataset.seg]?.(sg.dataset.val); return; }
  const pg = t.closest("button[data-page]");
  if (pg) { state.page[pg.dataset.page] = +pg.dataset.val; rerender(); return; }
  const op = t.closest("[data-open]");
  if (op) { state.open[op.dataset.open] = !state.open[op.dataset.open]; rerender(); return; }
  const lg = t.closest("button.lg");
  if (lg) { const k = lg.dataset.key, s = lg.dataset.series; state.hidden[k] = state.hidden[k] || new Set(); if (state.hidden[k].has(s)) state.hidden[k].delete(s); else state.hidden[k].add(s); rerender(); return; }
  const th = t.closest("th[data-sort]");
  if (th) { const k = th.dataset.sort; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : k === "name" || k === "state" ? 1 : -1 }; rerender(); return; }
  const rfb = t.closest("button[data-rf]");
  if (rfb) { setRunsFilter(rfb.dataset.rf, rfb.dataset.rv); return; }
  const rm = t.closest("[data-rmrun]");
  if (rm) { setCompareRuns(compareRuns().filter((n) => n !== rm.dataset.rmrun)); return; }
  const cmp = t.closest("[data-cmpset]");
  if (cmp) { setCompareRuns(cmp.dataset.cmpset.split(",")); return; }
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
  if (t.dataset.addrun !== undefined && t.value) { setCompareRuns(compareRuns().concat(t.value)); t.value = ""; }
  if (t.dataset.estpick !== undefined) { state.estPick[t.dataset.estpick] = +t.value; rerender(); }
  if (t.dataset.sel !== undefined) { onSeg[t.dataset.sel]?.(t.type === "checkbox" ? t.checked : t.value); return; }
  if (t.id === "picker" && t.value) { location.hash = "#/run/" + encodeURIComponent(t.value); t.value = ""; t.blur(); }
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.filter !== undefined) { if (t.dataset.filter) onSeg[t.dataset.filter]?.(t.value); else { state.filter = t.value; state.page.runs = 0; rerender(); } }
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
    const d = await getJSON("/api/v1/run/" + encodeURIComponent(name) + "?tail=5"), r = d.data;
    const e = r.elo || {}, est = r.elo_estimate || {};
    const md = `**${r.name}** (${r.state}${r.stop_reason ? ", " + r.stop_reason : ""}) · update ${r.update}/${r.target}\nchanges: ${JSON.stringify(r.rewards_changed_vs_minimal)}\n` +
      (e.elo != null ? `Elo ${Math.round(e.elo)} (rated), ` : est.elo != null ? `estimated Elo ${Math.round(est.elo)} at u${est.update}, ` : "") + (est.gf != null ? `GF ${f(est.gf)} GA ${f(est.ga)}\n` : "\n");
    await navigator.clipboard.writeText(md);
    btn.textContent = "copied";
  } catch (err) { btn.textContent = "copy failed"; }
  setTimeout(() => (btn.textContent = "copy summary"), 1500);
}
window.addEventListener("hashchange", () => { if (document.body.classList.contains("live-fs") && route().view !== "live") toggleFullscreen(false); lastHTML = ""; window.scrollTo(0, 0); render(); });

// ---------- start-up; theme: dark unless the user picked light ----------
function setThemeButton() { $("#theme").textContent = document.documentElement.dataset.theme === "light" ? "☾" : "☀"; }
$("#theme").addEventListener("click", () => {
  const light = document.documentElement.dataset.theme !== "light";
  if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("theme", light ? "light" : "dark"); } catch (e) {}
  setThemeButton(); rerender();
});
setThemeButton();
try { if (!location.hash && localStorage.getItem("area") === "game") history.replaceState(null, "", "#/game"); } catch (e) {}
function start() { render(); setInterval(poll, POLL_MS); }
if (window.Game) start(); else window.addEventListener("game-ready", start, { once: true });
