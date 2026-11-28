// The Lab (web/lab/core.js has the overview): the Runs table.
"use strict";

// ---------- RUNS ----------
const TYPE_LABEL = { rl: ["RL", "reinforcement learning (PPO self-play)"], imitation: ["Imitation", "behaviour cloning on the recorded play (il/train.py)"] };
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
  const st = r.state === "evaluating" ? "evaluating" : r.state || "unknown";
  return `<span class="st ${esc(st)}">${esc(st)}</span>${sub ? `<div class="muted small">${sub}</div>` : ""}`;
}
function updateCell(r) {
  if (r.update == null && !r.target) return r.queued ? "" : "–";
  if (r.update_unit) return `${r.update}<span class="pm"> ${esc(r.update_unit)}</span>`;
  const pct = r.target ? Math.min(100, (100 * (r.update || 0)) / r.target) : 0;
  const cls = ["diverged", "regressed", "failed"].includes(r.state) ? "bad" : r.state === "cancelled" || r.queued ? "off" : "";
  return `${r.update ?? 0}${r.target ? `<span class="pm">/${r.target}</span><div class="upd-bar ${cls}"><i style="width:${pct}%"></i></div>` : ""}`;
}
// goals scored / conceded per 90 s match against the average ladder entry (lab/ladder.py goal model: adjusted for who was played);
// from the ladder when the run's best checkpoint is in it, else from the run's latest estimated Elo
const ladderGoals = (e, est) => (e && e.games && e.agf != null ? { gf: e.agf, ga: e.aga, gd: e.agf - e.aga, gf_se: e.agf_se, ga_se: e.aga_se, est: false }
  : est && est.gf != null ? { gf: est.gf, ga: est.ga, gd: est.gf - est.ga, gf_se: est.gf_se, ga_se: est.ga_se, est: true } : null);
const estTip = "estimated Elo: the checkpoint played mixed ladder entries during training and only its own rating was fitted (lab/ladder.py estimate); the ladder rating replaces it once the run's best checkpoint is placed";
function eloCell(e, top, est) {
  if (!e && est) return `<b class="est" title="${esc(estTip)}">~${Math.round(est.elo)}</b><span class="pm">±${Math.round(1.96 * est.se)}</span><div class="muted small">estimate · u${est.update} · ${est.games} games</div>`;
  if (!e) return '<span class="muted" title="not in the Elo ladder (no exported best checkpoint)">–</span>';
  const pm = e.hi != null ? Math.round((e.hi - e.lo) / 2) : null;
  return `<b class="${e.id === top ? "pos" : ""}">${Math.round(e.elo)}</b>${pm != null ? `<span class="pm">±${pm}</span>` : ""}<div class="muted small" title="${e.w}-${e.d}-${e.l} (won-drawn-lost) in ${e.games} ladder matches">${e.placed ? `#${e.rank}` : "placing"} · ${e.games} games${e.stored ? ' <span class="stored" title="rated from ladder matches played before; this machine has no copy of the weights (out_5v5/ckpt/)">*</span>' : ""}</div>`;
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
  state.page.runs = 0;
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
  const val = (r) => { const e = ladderGoals(r.elo, r.elo_estimate); return { name: r.name, type: r.type, state: r.state, elo: r.elo?.elo ?? r.elo_estimate?.elo ?? -1, gf: e ? e.gf : -99, gd: e ? e.gd : -99, ga: e ? e.ga : 99, cost: r.cost_hours ? (r.cost_hours.train || 0) + (r.cost_hours.eval || 0) : -1, fin: r.finished || r.started || "" }[k]; };
  rows.sort((x, y) => (val(x) > val(y) ? 1 : val(x) < val(y) ? -1 : 0) * dir);
  const th = (key, l, cls = "", tip = "") => `<th class="sort ${cls}" data-sort="${key}"${tip ? ` title="${esc(tip)}"` : ""}>${l}${k === key ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`;
  // each choice shows how many runs it would leave, given the other filters
  const fseg = (key, list) => `<div class="rseg">${list.map(([v, l]) => { const c = all.filter((r) => pass(r, key) && (v === "all" || (key === "state" ? stateOf(r) : r[key]) === v)).length; return `<button class="${rf[key] === v ? "on" : ""}" data-rf="${key}" data-rv="${v}" ${c || v === "all" ? "" : "disabled"}>${l}<span>${c}</span></button>`; }).join("")}</div>`;
  const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
  const sel = (key, label, opts, tip = "") => `<label class="fsel ${rf[key] ? "on" : ""}" title="${esc(tip)}"><span>${label}</span><select data-rf="${key}"><option value="">any</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${rf[key] === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  const nets = uniq(all.map((r) => r.net)).map((n) => [n, n]);
  const keys = uniq(all.flatMap((r) => (r.changes || []).map((c) => c.k))).map((x) => [x, x === "start" ? "start net" : x]);
  const ctrls = uniq(all.map((r) => r.vs)).map((x) => [x, x]);
  const active = rf.state !== "all" || rf.type !== "all" || rf.net || rf.change || rf.vs || rf.ranked || rf.hidden || state.filter;
  const filters = `<div class="fbar">
      <input class="search" placeholder="Search name, notes, settings…" value="${esc(state.filter)}" data-filter>
      ${fseg("state", [["all", "All"], ["running", "Running"], ["queued", "Queued"], ["done", "Done"], ["stopped", "Stopped"], ["imported", "Imported"], ["reference", "Reference"]])}
    </div>
    <div class="fbar">
      ${fseg("type", [["all", "All types"], ["rl", "RL"], ["imitation", "Imitation"]])}${sel("net", "Net", nets)}${sel("change", "Changes", keys)}${sel("vs", "Experiment", ctrls, "a control run and the runs judged against it")}
      <label class="fchk ${rf.ranked ? "on" : ""}"><input type="checkbox" data-rf="ranked" ${rf.ranked ? "checked" : ""}> Has Elo</label>
      <label class="fchk ${rf.hidden ? "on" : ""}" title="failed, empty and leftover runs listed in exp/hidden_runs.json"><input type="checkbox" data-rf="hidden" ${rf.hidden ? "checked" : ""}> Show hidden <span class="muted">${all.filter((r) => r.hidden).length}</span></label>
      <span class="fcount">${rows.length} of ${all.length} runs</span>${active ? '<button class="linkbtn" data-rf="reset">Clear filters</button>' : ""}
    </div>`;
  const ladder = o.runs.concat(o.imitation || []).filter((r) => r.elo?.placed).sort((x, y) => y.elo.elo - x.elo.elo);
  const top = ladder[0]?.elo.id;
  const pg = pager("runs", rows, 25);
  const body = pg.rows.map((r) => {
    const g = ladderGoals(r.elo, r.elo_estimate), sel = state.selected.has(r.name), link = !r.queued && r.type !== "imitation";
    const [tl, tt] = TYPE_LABEL[r.type] || [r.type || "", ""];
    return `<tr class="${link ? "link" : "queued"}" data-run="${link ? esc(r.name) : ""}"><td>${link ? `<input type="checkbox" data-pick="${esc(r.name)}" ${sel ? "checked" : ""} aria-label="select ${esc(r.name)}">` : ""}</td>
      <td title="${esc(r.notes || "")}" class="${r.hidden ? "hid" : ""}">${link ? runLink(r.name) : `<span class="rl"><i class="dot" style="background:${r.queued ? "var(--line)" : runColor(r.name)}"></i>${esc(r.name)}</span>`}</td>
      <td class="r small">${r.cost_hours ? f((r.cost_hours.train || 0) + (r.cost_hours.eval || 0), 1) + " h" : ""}</td><td class="small muted nowrap">${r.finished ? ago(r.finished) : r.started ? "since " + ago(r.started).replace(" ago", "") : ""}</td>
      <td><span class="type ${esc(r.type || "")}" title="${esc(tt)}">${esc(tl)}</span></td>
      <td>${stateCell(r, o)}</td>
      <td>${changesCell(r)}</td>
      <td class="r">${updateCell(r)}</td>
      <td class="r elo">${r.queued ? "" : eloCell(r.elo, top, r.elo_estimate)}</td>
      <td class="r ${g?.est ? "est" : ""}">${g ? f(g.gf) : "–"}</td><td class="r ${g?.est ? "est" : ""}">${g ? f(g.ga) : "–"}</td><td class="r ${g && g.gd > 0 ? "pos" : g && g.gd < 0 ? "neg" : ""}">${g ? sgn(g.gd) : "–"}</td></tr>`;
  }).join("");
  const n = state.selected.size;
  return `<div class="head"><div><h1>Runs</h1><p>Experiments, imitation trainings, imported runs and the queue, the latest first (click a column to sort, e.g. by Elo), with goals scored and conceded against the average rated team (grey ~ = estimated during training). Tick runs to compare them; click a row for details.</p></div>
      <div class="tools"><a class="btn ${n ? "" : "disabled"}" href="#/compare?runs=${[...state.selected].map(encodeURIComponent).join(",")}">Compare ${n ? "(" + n + ")" : ""}</a></div></div>
    ${filters}
    <div class="card flush"><div class="tbl-wrap"><table class="runs"><thead><tr><th></th>${th("name", "Run")}${th("cost", "Cost", "r", "machine hours: training + evaluation")}${th("fin", "When")}${th("type", "Type", "", "how the net was trained")}${th("state", "State")}<th title="what this run changes against its control (vs …), or against the default recipe (from = the net it starts from)">Changes</th><th class="r">Update</th>${th("elo", "Elo", "r", "rating of the run's best checkpoint in the Elo ladder (lab/ladder.py: every team and net against each other), ±95%; the number to pick the best model by. ~ = estimated during training, until the ladder has placed it")}${th("gf", "GF", "r", "goals scored per 90 s match against the average ladder team (opponent-adjusted, from the same matches as the Elo)")}${th("ga", "GA", "r", "goals conceded per 90 s match against the average ladder team (opponent-adjusted)")}${th("gd", "GD", "r", "GF - GA")}</tr></thead><tbody>${body || '<tr><td colspan="12" class="muted">No runs match</td></tr>'}</tbody></table></div>${pg.html}</div>`;
}
