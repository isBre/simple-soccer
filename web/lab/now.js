// The Lab (web/lab/core.js has the overview): the Now page.
"use strict";

// ---------- NOW ----------
// One hero that always says something (running: progress; idle: the last finished run and its verdict), the Pi, the Elo top 8,
// the training curve of the running (or last) run and a readable event feed.
const lastFinished = (runs) => runs.filter((r) => r.finished && !r.hidden && !["imported", "reference"].includes(r.state)).sort((a, b) => (a.finished < b.finished ? 1 : -1))[0];
function queueLine(queued, running) {
  const q = queued.filter((s) => s.name !== running);
  if (!q.length) return `<div class="hero-next"><span class="muted">Queue empty</span> · add a spec with <span class="mono">python3 lab/lab.py queue add spec.json</span></div>`;
  return `<div class="hero-next"><span class="muted">Up next</span> ${q.slice(0, 3).map((s) => `<b>${esc(s.name)}</b>`).join(", ")}${q.length > 3 ? ` <span class="muted">+${q.length - 3} more</span>` : ""} <a href="#/runs">queue →</a></div>`;
}
function heroStat(value, label, cls = "") { return `<div><b class="${cls}">${value}</b><span>${label}</span></div>`; }
function viewNow() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const st = o.status, run = st.runner.running, pi = st.pi, last = run ? null : lastFinished(o.runs);
  let hero;
  if (run) {
    const row = o.runs.find((r) => r.name === run.run) || {};
    const spec = (o.queue.queued.find((q) => q.name === run.run) || {});
    const pct = run.target ? Math.min(100, (100 * (run.update || 0)) / run.target) : 0;
    const mode = run.evaluating ? "eval" : run.stalled ? "stale" : "";
    const lbl = run.evaluating ? badge("evaluating") : run.stalled ? `<span class="badge failed">no progress for ${dur(run.log_age_s)}</span>` : badge("running");
    const delta = run.train_pts_vs_rules != null && run.train_pts_at_start != null ? run.train_pts_vs_rules - run.train_pts_at_start : null;
    const lf = row.latest_fast;
    hero = `<section class="hero ${mode}"><div class="hero-top"><div class="min0"><div class="eyebrow">Running experiment${run.started ? " · since " + esc(ago(run.started).replace(" ago", "")) : ""}</div><h1>${runLink(run.run)}</h1>
        <div class="notes clamp" title="${esc(row.notes || "")}">${esc(row.notes || "")}</div><div class="chips">${chips({ net: row.net, rewards_changed_vs_minimal: row.rewards_changed_vs_minimal, args: (state.detail[run.run]?.status?.spec?.args) || spec.args || {} })}</div></div><div>${lbl}</div></div>
      <div class="progress"><i style="width:${pct}%"></i></div>
      <div class="hero-stats">${heroStat(`${run.update ?? 0}<small> / ${run.target ?? "?"}</small>`, "updates")}
        ${heroStat(run.eta_hours != null ? dur(run.eta_hours * 3600) : "–", "training left")}
        ${heroStat(run.sec_per_update ? f(run.sec_per_update, 0) + " s" : "–", "per update")}
        ${heroStat(`${f(run.train_pts_vs_rules)} <small class="${delta > 0 ? "pos" : delta < 0 ? "neg" : ""}">${delta != null ? sgn(delta) : ""}</small>`, "training pts vs rules")}
        ${heroStat(`${lf ? f(lf.pts) : "–"}<small>${lf ? " u" + lf.update : ""}</small>`, "last fast check")}
        ${heroStat(run.restarts.length, "restarts")}</div>${queueLine(o.queue.queued, run.run)}</section>`;
  } else if (last) {
    const v = last.verdict || {}, a = last.latest_full, h = a?.h2h || {}, cost = last.cost_hours ? (last.cost_hours.train || 0) + (last.cost_hours.eval || 0) : null;
    const h2h = (k) => heroStat(h[k] ? `${f(h[k].pts)}<small> GD ${sgn(h[k].gd)}</small>` : "–", "vs " + k);
    hero = `<section class="hero idle"><div class="hero-top"><div class="min0"><div class="eyebrow">Runner idle · last experiment finished ${esc(ago(last.finished))}</div>
        <h1>${runLink(last.name)}</h1><div class="notes clamp" title="${esc(last.notes || "")}">${esc(last.notes || "")}</div>
        <div class="chips">${chips({ net: last.net, rewards_changed_vs_minimal: last.rewards_changed_vs_minimal, args: last.spec_args || {} })}</div></div>
        <div class="hero-badges">${v.verdict ? badge(v.verdict) : badge(last.state)}${last.stop_reason && last.stop_reason !== "budget" ? `<span class="badge failed">${esc(last.stop_reason)}</span>` : ""}</div></div>
      <div class="hero-stats">${heroStat(v.verdict ? `${sgn(v.pts)}<small> ± ${f(v.pts_se)}</small>` : "–", v.reference ? "pts vs " + esc(v.reference) : "verdict pending", v.verdict === "better" ? "pos" : v.verdict === "worse" ? "neg" : "")}
        ${heroStat(a ? `${f(a.pts)}<small> ± ${f(a.se)}</small>` : "–", a ? "league pts u" + a.update : "league pts")}
        ${heroStat(a ? sgn(a.gd) : "–", "goal difference", a && a.gd > 0 ? "pos" : a && a.gd < 0 ? "neg" : "")}
        ${h2h("RL Team 4")}${h2h("RL Team 5")}
        ${heroStat(cost != null ? f(cost, 1) + " h" : "–", `${last.update ?? "–"} updates`)}</div>${queueLine(o.queue.queued)}</section>`;
  } else {
    hero = `<section class="hero idle"><div class="hero-top"><div><div class="eyebrow">Runner ${esc(st.runner.service || "")}</div><h1>Idle</h1></div>${badge("idle")}</div>${queueLine(o.queue.queued)}</section>`;
  }
  const th = throttle(pi.throttled), hasPi = pi.last_sample != null;
  const hl = (o.health || []).filter((r) => r.t && r.t.includes("T"));
  const vit = (k, color, lo, hi) => sparkline(hl.map((r) => [parseT(r.t), r[k]]).filter((p) => p[1] != null), color, 110, 26, lo, hi);
  const rb = st.last_reboot, mem = hasPi ? pi.mem_free_mb : null;
  const vitals = `<section class="card vitals"><div class="card-h"><h2>Raspberry Pi</h2><a href="#/pi">details →</a></div>
    <div class="vrow"><span>Temperature</span><b class="${pi.temp_c > 75 ? "neg" : ""}">${f(pi.temp_c, 1)} °C</b>${vit("temp", css("--c2"), 30, 85)}</div>
    <div class="vrow"><span>CPU load</span><b>${f(pi.load_1m, 1)} <small>/ 4</small></b>${vit("load", css("--c1"), 0, 12)}</div>
    <div class="vrow"><span>Free memory</span><b class="${mem != null && mem < 500 ? "neg" : ""}">${mem != null ? f(mem / 1024, 1) : "–"} GB</b>${vit("mem_mb", css("--c3"), 0, 3800)}</div>
    <div class="vrow"><span>Power</span><b class="${th.cls}">${esc(th.text)}</b><span class="muted small">${pi.uptime_hours != null ? "up " + dur(pi.uptime_hours * 3600) : ""}</span></div>
    ${!hasPi ? '<div class="muted small">No health samples (logs/pi_health.log): the health service is not running here.</div>' : ""}
    ${rb ? `<div class="vnote">Last reboot ${esc(ago(rb.back))} · last sample before it ${esc(rb.last_seen.replace("T", " "))}: load ${f(rb.last_sample.load, 1)}, ${f(rb.last_sample.mem_mb, 0)} MB free, ${f(rb.last_sample.temp, 0)} °C</div>` : ""}</section>`;
  const focus = run ? run.run : last?.name;
  let curve = '<div class="empty">Nothing trained yet</div>';
  if (focus) { const d = state.detail[focus]; ensureDetail(focus); curve = d && !d.error ? trainingChart(d, 200, "now") : '<div class="empty">Loading…</div>'; }
  const train = `<section class="card"><div class="card-h"><h2>${run ? "Training" : "Last run"}${focus ? " · " + esc(focus) : ""}</h2>${focus ? smoothControl() : ""}</div>${curve}</section>`;
  return `<div class="grid now-top">${hero}${vitals}</div>
    <div class="grid g2">${rankCard(focus, o.runs)}${train}</div>
    <section class="card"><div class="card-h"><h2>Events</h2><span class="muted small">last 24 h · newest first · fast checks grouped</span></div>${eventFeed(o.events)}</section>`;
}
// the top 8 of the Elo ranking (lab/ladder.py); the focus run's checkpoint is marked, and added below when it is not in the top 8
function rankCard(focus, runs) {
  loadRanking();
  const d = rk.data, head = (sub) => `<div class="card-h"><h2>Ranking</h2><span class="muted small">${sub} · <a href="#/ranking">full ranking →</a></span></div>`;
  if (!d) return `<section class="card">${head("Elo")}<div class="empty">Loading…</div></section>`;
  if (d.error || !d.matches) return `<section class="card">${head("Elo")}<div class="empty">${d.error ? "The ranking could not be computed" : "No ladder matches yet"}</div></section>`;
  // runs whose weights are not on this machine are missing from /api/ranking; the overview rates them from their stored ladder matches
  const have = new Set(d.rows.map((r) => r.id));
  const stored = runs.filter((r) => r.elo?.stored && r.elo.games && !have.has(r.elo.id)).map((r) => ({ ...r.elo, name: r.name, league: "rl", kind: "net" }));
  const played = d.rows.filter((r) => r.games).concat(stored).sort((x, y) => y.elo - x.elo).map((r, i) => ({ ...r, rank: i + 1 })), known = new Set(runs.map((r) => r.name));
  const runOf = (r) => { const m = /^net:x_(.+?)(?:_best)?$/.exec(r.id); return m && known.has(m[1]) ? m[1] : null; };
  const isFocus = (r) => focus && runOf(r) === focus;
  const top = played.slice(0, 8), extra = played.slice(8).filter(isFocus), shown = top.concat(extra);
  const lo = Math.min(...shown.map((r) => r.lo)), hi = Math.max(...shown.map((r) => r.hi)), W = 110, X = (v) => 5 + ((v - lo) / (hi - lo || 1)) * (W - 10);
  const row = (r) => {
    const c = css(LEAGUE_COLOR[r.league] || "--muted"), rn = runOf(r);
    const name = rn ? `${runLink(rn)}${/_best$/.test(r.id) ? ' <span class="muted small">best</span>' : ""}${r.stored ? ' <span class="muted" title="rated from the ladder matches the Pi already played; this machine has no copy of the weights">*</span>' : ""}` : `<b>${esc(r.name)}</b>`;
    return `<tr class="${isFocus(r) ? "focus" : ""}${r.placed ? "" : " dim"}"><td class="r muted">${r.rank}</td><td><div class="nm">${name}</div></td><td>${leagueChip(r.league)}</td>
      <td class="r"><b>${f(r.elo, 0)}</b><span class="pm">±${f(1.96 * r.se, 0)}</span></td>
      <td><svg width="${W}" height="14" viewBox="0 0 ${W} 14" class="rkbar"><line x1="${X(r.lo)}" x2="${X(r.hi)}" y1="7" y2="7" stroke="${c}" stroke-width="3" stroke-linecap="round" opacity=".5"/><circle cx="${X(r.elo)}" cy="7" r="4" fill="${c}"/></svg></td>
      <td class="r muted small k-hide" title="won–drawn–lost">${r.w}–${r.d}–${r.l}</td></tr>`;
  };
  const gap = extra.length ? `<tr class="gap"><td></td><td colspan="5" class="muted small">…</td></tr>` : "";
  return `<section class="card">${head(`Elo · ${d.matches.toLocaleString()} matches${d.last ? " · last " + esc(ago(d.last)) : ""}`)}
    <div class="tbl-wrap"><table class="mini now-rank"><tbody>${top.map(row).join("")}${gap}${extra.map(row).join("")}</tbody></table></div>
    ${focus && !shown.some(isFocus) ? `<div class="muted small">${esc(focus)} has no checkpoint in the ladder yet</div>` : ""}</section>`;
}
// events (lab.py cmd_events): runner log lines + recorded evaluations + reboots -> one readable line each, consecutive fast checks of a run
// grouped, the runner's own fast / full-eval-started lines dropped (the recorded evaluations say the same), day separators
function eventItem(e) {
  const t = e.text || "", run = (n) => runLink(n);
  let m;
  if (e.kind === "eval_recorded" && (m = /^(\S+) u(\d+) (\w+) \S+ pts (\S+)/.exec(t))) {
    const pts = parseFloat(m[4]);
    return m[3] === "fast" ? { cls: "fast", group: "fast:" + m[1], run: m[1], u: +m[2], pts } : { cls: "full", html: `${run(m[1])} full evaluation at u${m[2]}: <b>${Number.isNaN(pts) ? "–" : f(pts)}</b> pts` };
  }
  if (e.kind === "fast_check" || e.kind === "full_eval") return null;
  if (e.kind === "started" && (m = /^started (\S+)/.exec(t))) return { cls: "started", html: `${run(m[1])} started` };
  if (e.kind === "resumed" && (m = /^resuming (\S+) from update (\d+) \((.*)\)$/.exec(t))) return { cls: "started", html: `${run(m[1])} resumed at u${m[2]} <span class="muted">${esc(m[3])}</span>` };
  if (e.kind === "finished" && (m = /^(\S+) finished: (\S+)\s*(.*)$/.exec(t))) {
    let v = null; try { v = m[3] ? JSON.parse(m[3]) : null; } catch (err) {}
    const ver = v && v.verdict ? ` · ${badge(v.verdict)} <span class="muted">${sgn(v.pts)} ± ${f(v.pts_se)} vs ${esc(v.reference || "")}</span>` : "";
    return { cls: m[2] === "done" ? "finished" : "stopped", html: `${run(m[1])} finished: ${esc(m[2])}${ver}` };
  }
  if (e.kind === "stopped" && (m = /^(\S+): (\S+) at update (\d+)/.exec(t))) return { cls: "stopped", html: `${run(m[1])} stopped at u${m[3]}: ${esc(m[2])}` };
  if (e.kind === "reboot") return { cls: "reboot", html: `Pi rebooted <span class="muted">${esc(t.replace(/^Pi rebooted\s*/, ""))}</span>` };
  if (/^ladder: /.test(t)) return { cls: "info", group: "ladder", html: "ladder round" };
  if (/^viewer closed/.test(t)) return { cls: "info", group: "viewer", html: "Live viewer restarted" };
  return { cls: e.kind === "error" ? "error" : "info", html: esc(t) };
}
function eventFeed(events) {
  const items = [];
  for (const e of events) {                                   // newest first
    const it = eventItem(e); if (!it) continue;
    const prev = items[items.length - 1];
    if (it.group && prev && prev.group === it.group && prev.t.slice(0, 10) === (e.t || "").slice(0, 10)) { prev.n++; prev.t0 = e.t; if (it.u != null) { prev.us.push(it.u); prev.pts.push(it.pts); } continue; }
    items.push({ ...it, t: e.t || "", t0: e.t || "", n: 1, us: it.u != null ? [it.u] : [], pts: it.pts != null ? [it.pts] : [] });
  }
  if (!items.length) return '<ul class="events"><li class="muted">nothing in the last 24 h</li></ul>';
  const day = (iso) => { const d = new Date(iso.slice(0, 10) + "T12:00:00"), today = new Date(); today.setHours(12, 0, 0, 0); const k = Math.round((today - d) / 86400000); return k === 0 ? "Today" : k === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" }); };
  let out = "", lastDay = "";
  for (const it of items.slice(0, 14)) {
    const dd = it.t.slice(0, 10);
    if (dd && dd !== lastDay) { out += `<li class="day">${esc(day(it.t))}</li>`; lastDay = dd; }
    let html = it.html;
    if (it.cls === "fast") {
      const ok = it.pts.filter((p) => !Number.isNaN(p)), us = [...it.us].sort((a, b) => a - b);
      const rng = ok.length ? (Math.min(...ok) === Math.max(...ok) ? f(ok[0]) : `${f(Math.min(...ok))}–${f(Math.max(...ok))}`) : "–";
      html = it.n === 1 ? `${runLink(it.run)} fast check at u${us[0]}: <b>${rng}</b> pts` : `${runLink(it.run)} ${it.n} fast checks, u${us[0]}–u${us[us.length - 1]}: <b>${rng}</b> pts`;
    } else if (it.n > 1) html += ` <span class="muted">×${it.n}</span>`;
    const time = it.n > 1 && it.t0 !== it.t ? `${it.t0.slice(11, 16)}–${it.t.slice(11, 16)}` : it.t.slice(11, 16);
    out += `<li class="ev ${esc(it.cls)}"><time>${esc(time)}</time><span>${html}</span></li>`;
  }
  return `<ul class="events">${out}</ul>`;
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
