// The Lab (web/lab/core.js has the overview): the Now page, the Lab's home (docs/lab_design.md "Now"). A dashboard that fills the window, no scrolling:
// the run strip (running experiment, or the last finished one), then its Elo chart, the live match and the machine, then the ratings
// (players, teams and checkpoints kept apart) and the timeline of the last 24 h.
"use strict";

const lastFinished = (runs) => runs.filter((r) => r.finished && !r.hidden && !["imported", "reference"].includes(r.state)).sort((a, b) => (a.finished < b.finished ? 1 : -1))[0];
function viewNow() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const run = o.status.runner.running, focus = run ? run.run : lastFinished(o.runs)?.name;
  const d = focus ? (ensureDetail(focus), state.detail[focus]) : null;
  return `<div class="now">
    ${runStrip(o, run, focus, d)}
    <div class="grid">
      <section class="card s5">${cardHead("Estimated Elo" + (focus ? " · " + esc(focus) : ""), focus ? `<a href="#/run/${encodeURIComponent(focus)}">run →</a>` : "")}
        ${d && !d.error ? estChart(d, "fill", "now") : '<div class="empty chart-empty fill">Nothing trained yet</div>'}</section>
      ${liveCard()}
      ${machineCard(o)}
    </div>
    <div class="grid">${ratingsCard(focus)}${timelineCard(o)}</div></div>`;
}

// ---------- the run strip ----------
function runStrip(o, run, focus, d) {
  if (!focus) return `<section class="card strip">${stripHead("Runner idle", "Nothing trained yet", "")}${queueLine(o.queue.queued)}</section>`;
  const row = o.runs.find((r) => r.name === focus) || {}, est = row.elo_estimate, e = row.elo?.games ? row.elo : null, se = row.start_elo;
  const elo = e ? e.elo : est?.elo, dStart = elo != null && se ? elo - se.elo : null, g = ladderGoals(e, est);
  let eyebrow, badgeHtml, mode = "";
  if (run) {
    mode = run.evaluating ? "eval" : run.stalled || run.thermal_pause ? "stale" : "";
    eyebrow = `Running experiment · since ${esc(ago(run.started).replace(" ago", ""))}`;
    badgeHtml = run.thermal_pause ? `<span class="badge evaluating" title="lab/thermal_guard.py: resumes at ${f(run.thermal_pause.resume, 1)} °C">paused to cool · ${f(run.thermal_pause.temp, 1)} °C</span>`
      : run.evaluating ? badge("evaluating") : run.stalled ? `<span class="badge failed">no progress for ${dur(run.log_age_s)}</span>` : badge("running");
  } else {
    eyebrow = `Runner idle · last experiment finished ${esc(ago(row.finished))}`;
    badgeHtml = badge(row.state) + (row.stop_reason && !["budget", row.state].includes(row.stop_reason) ? ` <span class="badge failed">${esc(row.stop_reason)}</span>` : "");
  }
  const spec = d?.status?.spec || o.queue.queued.find((q) => q.name === focus) || {};
  const kp = [
    kpi("Checkpoint Elo", e ? eloText(e.elo, (e.hi - e.lo) / 2) : eloText(est?.elo, est ? 1.96 * est.se : null, true),
      `${e ? "rated" : est ? "u" + est.update : "comes with every check"}${dStart != null ? ` · <span class="${tone(dStart)}">${sgn(dStart, 0)}</span> vs start` : ""}`),
    kpi("Goals for", g ? f(g.gf) : "–", "per match"), kpi("Goals against", g ? f(g.ga) : "–", "per match"),
    run ? kpi("Training left", run.eta_hours != null ? dur(run.eta_hours * 3600) : "–", run.sec_per_update ? f(run.sec_per_update, 1) + " s / update" : "")
      : kpi("Cost", row.cost_hours ? f((row.cost_hours.train || 0) + (row.cost_hours.eval || 0), 1) + " h" : "–", `${row.update ?? "–"} updates`),
  ].join("");
  const upd = run ? run.update || 0 : row.update || 0, target = (run ? run.target : row.target) || upd || 1;
  const ticks = (d?.estimates || []).filter((x) => x.update > 0 && x.update <= target).map((x) => `<u style="left:${(100 * x.update) / target}%" title="check at u${x.update}: ~${f(x.elo, 0)}"></u>`).join("");
  return `<section class="card strip ${mode}">
      <div class="strip-top"><div class="min0">${stripHead(eyebrow, runLink(focus), badgeHtml)}
        <div class="chips">${chips({ net: row.net, stage: row.stage, curriculum: row.curriculum, rewards_changed_vs_minimal: row.rewards_changed_vs_minimal, args: spec.args || {} })}</div>
        ${notes("now:" + focus, row.notes, 1)}</div>
        <div class="kpis strip-kpis">${kp}</div></div>
      <div class="progress"><i style="width:${Math.min(100, (100 * upd) / target)}%"></i>${ticks}</div>
      <div class="strip-foot"><span class="muted">update <b>${upd}</b> / ${target} · ticks = Elo checks</span>${stagesLine(o, row)}${queueLine(o.queue.queued, focus)}</div></section>`;
}
const stripHead = (eyebrow, title, side) => `<div class="eyebrow">${eyebrow}</div><div class="strip-title"><h1>${title}</h1>${side}</div>`;
function queueLine(queued, running) {
  const q = queued.filter((s) => s.name !== running);
  if (!q.length) return '<span class="muted">queue empty</span>';
  return `<span><span class="muted">up next</span> ${q.slice(0, 2).map((s) => `<b>${esc(s.name)}</b>`).join(", ")}${q.length > 2 ? ` <span class="muted">+${q.length - 2}</span>` : ""} <a href="#/runs">queue →</a></span>`;
}
// a curriculum's stages (one run per stage, lab/tracker.py expand): the latest attempt of each, with its result
function stagesLine(o, row) {
  if (!row.curriculum) return "";
  const byStage = {};
  for (const r of o.runs) if (r.curriculum === row.curriculum && r.stage && (!byStage[r.stage] || r.started > byStage[r.stage].started)) byStage[r.stage] = r;
  const mark = (r) => (r.state === "running" ? "●" : r.state === "done" ? "✓" : STOPPED.includes(r.state) ? "✗" : "○");
  const items = Object.values(byStage).sort((a, b) => (a.size - b.size) || a.stage.localeCompare(b.stage)).map((r) => {
    const elo = r.elo?.games ? f(r.elo.elo, 0) : r.elo_estimate ? "~" + f(r.elo_estimate.elo, 0) : "";
    return `<a class="stage ${esc(r.state)}${r.name === row.name ? " on" : ""}" href="#/run/${encodeURIComponent(r.name)}" title="${esc(r.name)}: ${esc(r.state)}${elo ? " · " + elo : ""}">${mark(r)} ${esc(r.stage)}</a>`;
  });
  return `<span class="stages"><span class="muted">${esc(row.curriculum)}</span>${items.join("")}</span>`;
}

// ---------- the live match (drawn by web/lab/live.js) and the machine ----------
const liveCard = () => `<a class="card s4 live-card" href="#/live" title="Open the live match">${cardHead("Live", '<span class="muted small">open →</span>')}
  <div class="lc-view"><canvas data-live="card"></canvas></div><div id="lc-foot" class="lc-foot"></div></a>`;
function machineCard(o) {
  const mc = o.status.machine, th = powerState(mc), cores = mc.cores || 4, rb = o.status.last_reboot, mem = mc.last_sample != null ? mc.mem_free_mb : null;
  const hl = (o.health || []).filter((r) => r.t && r.t.includes("T"));
  const spark = (k, color, lo, hi) => sparkline(hl.map((r) => [parseT(r.t), r[k]]).filter((p) => p[1] != null), color, 96, 22, lo, hi);
  const row = (label, value, sp) => `<div class="vrow"><span>${label}</span><b>${value}</b>${sp}</div>`;
  return `<section class="card s3 vitals">${cardHead(esc(machineName(mc)), '<a href="#/machine">details →</a>')}
    <div class="vtop"><div><div class="big ${mc.temp_c > tempWarn(mc) ? "neg" : ""}">${f(mc.temp_c, 0)}<small> °C</small></div><div class="muted small">${esc(mc.temp_label || "temperature")}</div></div>
      ${spark("temp", css("--c2"), 20, 50)}</div>
    ${row("CPU load", `${f(mc.load_1m, 1)} <small>/ ${cores}</small>`, spark("load", css("--c1"), 0, cores * 3))}
    ${row("Free memory", `<span class="${mem != null && mem < 500 ? "neg" : ""}">${mem != null ? f(mem / 1024, 1) : "–"}</span> <small>GB</small>`, spark("mem_mb", css("--c3"), 0, mc.mem_total_mb || 16384))}
    ${row("Thermal", `<span class="${th.cls}">${esc(th.text)}</span>`, `<span class="muted small">${mc.uptime_hours != null ? "up " + dur(mc.uptime_hours * 3600) : ""}</span>`)}
    ${rb ? `<div class="vnote">Rebooted ${esc(ago(rb.back))}</div>` : ""}</section>`;
}

// ---------- ratings: the top 5 of one list (players, teams or checkpoints; never mixed) ----------
state.nowRk = state.nowRk || "player";
onSeg.nowrk = (v) => { state.nowRk = v; rerender(); };
function ratingsCard(focus) {
  loadRanking();
  const d = rk.data, what = state.nowRk;
  const head = cardHead("Ratings · 5v5", `${seg("nowrk", [["player", "Players"], ["team", "Teams"], ["net", "Checkpoints"]], what)}<a href="#/ranking">all →</a>`);
  if (!d) return `<section class="card s5">${head}<div class="empty">Loading…</div></section>`;
  if (d.error || !d.matches) return `<section class="card s5">${head}<div class="empty">${d.error ? "The ratings could not be computed" : "No rated matches yet"}</div></section>`;
  const list = d.rows.filter((r) => r.entry === what && r.games).sort((a, b) => b.elo - a.elo).map((r, i) => ({ ...r, rank: i + 1 }));
  const mine = (r) => focus && (r.id === `net:x_${focus}_best` || r.id === `net:x_${focus}`);
  const rows = list.slice(0, 10).concat(list.slice(10).filter(mine));
  // the focus run before its checkpoint is rated: its estimate, placed where it would rank
  const run = (state.ov?.runs || []).find((r) => r.name === focus), est = run?.elo_estimate;
  if (what === "net" && est && !list.some(mine)) rows.push({ name: focus + " · estimate", est: true, elo: est.elo, se: est.se, rank: "≈" + (list.filter((r) => r.elo > est.elo).length + 1), focus: true });
  const tr = (r) => `<tr class="${mine(r) || r.focus ? "focus" : ""}${r.placed === false ? " dim" : ""}"><td class="r muted">${r.rank}</td>
    <td><div class="nm">${r.est ? runLink(focus) + ' <span class="muted small">estimate</span>' : esc(r.name)}</div></td><td>${r.league ? leagueChip(r.league) : ""}</td>
    <td class="r">${eloText(r.elo, 1.96 * r.se, r.est)}</td><td class="r muted small">${r.est ? "" : `${r.w}–${r.d}–${r.l}`}</td></tr>`;
  return `<section class="card s5">${head}<div class="fade"><table class="mini"><tbody>${rows.map(tr).join("")}</tbody></table></div>
    <div class="muted small foot">${esc(eloKind(what))}: ${{ player: "a player as five copies of itself", team: "a line-up of players", net: "a training checkpoint, rated like a player" }[what]} · ${d.matches.toLocaleString()} matches</div></section>`;
}

// ---------- timeline of the last 24 h and the latest events ----------
function timelineCard(o) {
  const items = eventList(o.events);
  return `<section class="card s7">${cardHead("Last 24 hours", '<a href="#/events">all events →</a>')}${timeline(o)}
    <div class="fade"><ul class="events">${items.slice(0, 14).map(eventLi).join("") || '<li class="muted">nothing in the last 24 h</li>'}</ul></div></section>`;
}
// one track: the runs one after another (the runner trains one at a time) in their colours; above it the checks (dots), stops (✗),
// finishes (✓) and reboots (red line); positions in % of the window, so it needs no drawing code
function timeline(o) {
  const now = Date.now() / 1000, t0 = now - 86400, X = (t) => Math.max(0, Math.min(100, (100 * (t - t0)) / 86400));
  let bars = "", marks = "";
  for (const r of o.runs) {
    const a = parseT(r.started), b = r.finished ? parseT(r.finished) : r.state === "running" ? now : null;
    if (!a || !b || b < t0) continue;
    bars += `<i class="seg" style="left:${X(a)}%;width:${Math.max(0.3, X(b) - X(a))}%;background:${runColor(r.name)}" title="${esc(r.name)} · ${esc(r.state)} · ${hhmm(a)}–${r.finished ? hhmm(b) : "now"}"></i>`;
  }
  for (const e of o.events) {
    const t = parseT(e.t), run = eventRun(e); if (!t || t < t0) continue;
    const k = e.kind === "estimate" ? "chk" : e.kind === "finished" ? (/ finished: done/.test(e.text) ? "ok" : "bad") : e.kind === "stopped" ? "bad" : e.kind === "reboot" ? "reboot" : null;
    if (k) marks += `<i class="mk ${k}" style="left:${X(t)}%;${k === "chk" && run ? "background:" + runColor(run) : ""}" title="${esc(e.t.slice(11, 16))} ${esc(e.text)}"></i>`;
  }
  const ticks = [0, 6, 12, 18, 24].map((h) => `<span style="left:${(100 * h) / 24}%">${h === 24 ? "now" : hhmm(t0 + h * 3600)}</span>`).join("");
  return `<div class="timeline"><div class="tl-marks">${marks}</div><div class="tl-track">${bars}</div><div class="tl-axis">${ticks}</div></div>`;
}
