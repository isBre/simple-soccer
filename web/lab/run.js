// The Lab (web/lab/core.js has the overview): one run's page (summary, training, evaluation, behaviour, scouting, config).
"use strict";

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
// the run's Elo: the ladder rating of its best checkpoint once placed, the estimates of its checkpoints during training, the start net
function runElo(d) {
  const row = (state.ov?.runs || []).find((r) => r.name === d.run) || {}, e = row.elo, es = d.estimates || [], est = es[es.length - 1];
  return { e: e && e.games ? e : null, est, se: d.start_elo, g: ladderGoals(e && e.games ? e : null, est) };
}
function runSummary(d) {
  const { e, est, se, g } = runElo(d);
  const cur = e ? e.elo : est ? est.elo : null, dStart = cur != null && se ? cur - se.elo : null;
  const kp = `<div class="kpis">
    ${kpi("Elo", e ? `${f(e.elo, 0)}<small>± ${f((e.hi - e.lo) / 2, 0)}</small>` : "–", e ? (e.placed ? `#${e.rank} · ${e.games} ladder games · ${e.w}–${e.d}–${e.l}` : `placing: ${e.games}/6 games`) : "best checkpoint not in the ladder yet")}
    ${kpi(`Estimated Elo <span class="muted">${est ? "u" + est.update : ""}</span>`, est ? `~${f(est.elo, 0)}<small>± ${f(1.96 * est.se, 0)}</small>` : "–", est ? `${est.games} games · ${est.w}–${est.d}–${est.l}` : "comes with every check")}
    ${kpi("vs start net", dStart != null ? sgn(dStart, 0) : "–", se ? `${esc(se.name)} ${se.estimate ? "~" : ""}${f(se.elo, 0)}${se.estimate ? " (estimate u0)" : ""}` : "start net not rated", dStart > 0 ? "pos" : dStart < 0 ? "neg" : "")}
    ${kpi("Goals scored", g ? f(g.gf) : "–", g ? `per match vs the average ladder team${g.gf_se != null ? " · ±" + f(1.96 * g.gf_se) : ""}${g.est ? " · estimate" : ""}` : "")}
    ${kpi("Goals conceded", g ? f(g.ga) : "–", g ? `per match vs the average ladder team${g.ga_se != null ? " · ±" + f(1.96 * g.ga_se) : ""}${g.est ? " · estimate" : ""}` : "")}
    ${kpi("Goal difference", g ? sgn(g.gd) : "–", g ? "scored − conceded" : "", g && g.gd > 0 ? "pos" : g && g.gd < 0 ? "neg" : "")}</div>`;
  return `${kp}<div class="grid g2"><section class="card"><div class="card-h"><h2>Estimated Elo</h2><span class="muted small">each check · 95% interval</span></div>${estChart(d, 220, "sum")}</section>
    <section class="card"><div class="card-h"><h2>Goals per match</h2><span class="muted small">estimates · vs the average ladder team</span></div>${estGoalsChart(d, 220, "sum")}</section></div>
    <section class="card"><div class="card-h"><h2>Training points</h2><span class="muted small">sampled play during training, a trend signal</span>${smoothControl()}</div>${trainingChart(d, 250, "run", 1240)}</section>`;
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
  loadRanking();
  const { e, se } = runElo(d), es = d.estimates || [];
  const name = Object.fromEntries((rk.data?.rows || []).map((r) => [r.id, r.name]));
  const pick = es.find((x) => x.update === state.estPick[d.run]) || es[es.length - 1];
  const rowsE = es.slice().reverse().map((x) => `<tr class="${x === pick ? "focus" : ""}"><td>u${x.update}${x.update === 0 ? ' <span class="muted small">start net</span>' : ""}</td><td class="r"><b>${f(x.elo, 0)}</b><span class="pm">±${f(1.96 * x.se, 0)}</span></td>
    <td class="r">${f(x.gf)}</td><td class="r">${f(x.ga)}</td><td class="r ${x.gf - x.ga > 0 ? "pos" : x.gf - x.ga < 0 ? "neg" : ""}">${sgn(x.gf - x.ga)}</td><td class="r nowrap">${x.w}–${x.d}–${x.l}</td><td class="r muted small">${f(x.raw_gf)} – ${f(x.raw_ga)}</td><td class="r">${x.games}</td></tr>`).join("");
  const ladderRow = e ? `<tr class="lad"><td><b>ladder</b> <span class="muted small">best checkpoint</span></td><td class="r"><b>${f(e.elo, 0)}</b><span class="pm">±${f((e.hi - e.lo) / 2, 0)}</span></td><td class="r">${f(e.agf)}</td><td class="r">${f(e.aga)}</td><td class="r ${e.agf - e.aga > 0 ? "pos" : "neg"}">${sgn(e.agf - e.aga)}</td><td class="r nowrap">${e.w}–${e.d}–${e.l}</td><td class="r muted small">${f(e.gf / e.games)} – ${f(e.ga / e.games)}</td><td class="r">${e.games}${e.placed ? "" : ' <span class="muted small">placing</span>'}</td></tr>` : "";
  const startRow = se && se.games && !se.estimate ? `<tr class="dim"><td>start net <span class="muted small">${esc(se.name)}</span></td><td class="r">${f(se.elo, 0)}<span class="pm">±${f((se.hi - se.lo) / 2, 0)}</span></td><td class="r">${f(se.agf)}</td><td class="r">${f(se.aga)}</td><td class="r">${se.agf != null ? sgn(se.agf - se.aga) : "–"}</td><td></td><td></td><td class="r">${se.games}</td></tr>` : "";
  const table = `<section class="card flush"><div class="card-h pad"><h2>Elo and goals</h2><span class="muted small">goals per 90 s match vs the average ladder team (opponent-adjusted) · raw = as played</span></div><div class="tbl-wrap"><table><thead><tr><th>Checkpoint</th><th class="r">Elo</th><th class="r">GF</th><th class="r">GA</th><th class="r">GD</th><th class="r">W–D–L</th><th class="r">raw GF – GA</th><th class="r">Games</th></tr></thead>
    <tbody>${ladderRow}${rowsE || (ladderRow ? "" : '<tr><td colspan="8" class="muted">No estimate yet: one comes with every check (every 50 updates).</td></tr>')}${startRow}</tbody></table></div></section>`;
  const sel = es.length ? `<select data-estpick="${esc(d.run)}">${es.map((x) => `<option value="${x.update}" ${x === pick ? "selected" : ""}>u${x.update}</option>`).join("")}</select>` : "";
  const matches = pick ? `<section class="card flush"><div class="card-h pad"><h2>Matches of the estimate ${sel}</h2><span class="muted small">${pick.games} games · ${pick.seconds ? "took " + dur(pick.seconds) : ""} · opponents mixed: half spread over the ranking, half near its level</span></div><div class="tbl-wrap"><table class="mini"><thead><tr><th>Opponent</th><th class="r">Their Elo</th><th class="r">Score</th><th class="r">Side</th></tr></thead><tbody>${(pick.matches || []).slice().sort((a, b) => b.opp_elo - a.opp_elo || a.side - b.side).map((m) => `<tr><td>${esc(name[m.opp] || m.opp)}</td><td class="r">${m.opp_elo}</td><td class="r ${m.gf > m.ga ? "pos" : m.gf < m.ga ? "neg" : ""}"><b>${m.gf}–${m.ga}</b></td><td class="r muted small">${m.side ? "away" : "home"}</td></tr>`).join("")}</tbody></table></div></section>` : "";
  return `<div class="grid g2"><section class="card"><div class="card-h"><h2>Estimated Elo</h2><span class="muted small">each check · 95% interval</span></div>${estChart(d, 220, "ev")}</section>
    <section class="card"><div class="card-h"><h2>Goals per match</h2><span class="muted small">estimates · vs the average ladder team</span></div>${estGoalsChart(d, 220, "ev")}</section></div>
    ${table}${matches}`;
}
// behaviour of the run's newest full evaluation next to the strongest rated teams (dashboard.behaviour_refs: RL Team 4 / 5, jit8,
// the best checkpoint of the top runs); the bar = the range of those teams, the dot = this run
const refName = (n) => n.replace(/^team:/, "").replace(/^old_/, "");
function runBehaviour(d) {
  const e = d.evals.filter((x) => x.kind === "full").pop();
  if (!e) return '<div class="empty">Behaviour is measured in full evaluations: none yet</div>';
  const b = e.behaviour || {}, refs = d.behaviour_refs || [];
  const rows = BEHAVIOUR.filter(([k]) => b[k] != null).map(([k, label, , dec]) => {
    const vals = refs.map((r) => r.behaviour?.[k]).filter((v) => v != null), v = b[k];
    let bar = "";
    if (vals.length) {
      const lo = Math.min(...vals), hi = Math.max(...vals), a = Math.min(lo, v), z = Math.max(hi, v), X = (x) => 4 + ((x - a) / (z - a || 1)) * 112;
      bar = `<svg width="120" height="14" viewBox="0 0 120 14" class="rkbar"><line x1="${X(lo)}" x2="${X(hi)}" y1="7" y2="7" stroke="var(--muted)" stroke-width="5" stroke-linecap="round" opacity=".35"/><circle cx="${X(v)}" cy="7" r="4.5" fill="${runColor(d.run)}"/></svg>`;
    }
    return `<tr><td>${label}</td><td class="r"><b>${f(v, dec)}</b></td><td>${bar}</td>${refs.map((r) => `<td class="r muted">${f(r.behaviour?.[k], dec)}</td>`).join("")}</tr>`;
  }).join("");
  const head = `<tr><th>Behaviour</th><th class="r">${esc(d.run)} <span class="muted small">u${e.update}</span></th><th><span class="muted small">range of the teams on the right</span></th>${refs.map((r) => `<th class="r" title="${esc(r.kind)} evaluation u${r.update} (${esc(r.protocol || "")})">${runLink(r.name).replace(esc(r.name) + "</a>", esc(refName(r.name)) + "</a>")}<div class="muted small">Elo ${f(r.elo, 0)}</div></th>`).join("")}</tr>`;
  const heats = (d.heat || []).map((hm) => heatmap(hm, hm.slot === "ball" ? "Ball" : "Player slot " + (Number(hm.slot) + 1))).join("");
  return `<section class="card flush"><div class="card-h pad"><h2>Behaviour next to the strongest teams</h2><span class="muted small">the ${refs.length} highest rated teams in the Elo ladder with measured behaviour · all measured in matches against the same rule teams, sampled moves</span></div>
    <div class="tbl-wrap"><table><thead>${head}</thead><tbody>${rows || `<tr><td colspan="${3 + refs.length}" class="muted">no behaviour data</td></tr>`}</tbody></table></div></section>
    <section class="card"><div class="card-h"><h2>Where the players are</h2><span class="muted small">share of time · attacking right</span></div><div class="heats">${heats || '<div class="empty">no heatmaps</div>'}</div>
    <div class="hlegend"><span>rare</span><i></i><span>often</span></div><p class="muted small">Per player slot: with no fixed roles a slot is not a position. Role-based views come with the scouting page.</p></section>`;
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
