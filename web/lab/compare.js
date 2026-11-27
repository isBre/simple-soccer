// The Lab (web/lab/core.js has the overview): the Compare page. Up to 4 runs side by side, judged as AGENTS.md says: by the Elo of
// the run's checkpoint (rated, else estimated) and its goals scored and conceded; two Elos differ only when their 95% intervals do not
// overlap. The full evaluations (league points against the rule teams, behaviour) are folded away below, compared within one protocol.
"use strict";

const MAX_CMP = 4;
function compareRuns() {
  const o = state.ov, names = new Set((o?.runs || []).map((r) => r.name));
  const runs = (route().params.get("runs") || "").split(",").filter((n) => names.has(n));
  if (runs.length || !o) return runs;
  const run = o.status.runner.running?.run || lastFinished(o.runs)?.name, row = o.runs.find((r) => r.name === run);
  return [run, row?.control].filter((n) => n && names.has(n));
}
function setCompareRuns(list) {
  const p = route().params;
  p.set("runs", [...new Set(list.filter(Boolean))].slice(0, MAX_CMP).join(","));
  location.hash = "#/compare?" + p.toString();
}
// a run's Elo for comparing: the rated best checkpoint, else its newest estimate, with the 95% interval
function cmpElo(r) {
  if (r?.elo?.games) return { elo: r.elo.elo, lo: r.elo.lo, hi: r.elo.hi, est: false };
  const e = r?.elo_estimate; return e ? { elo: e.elo, lo: e.elo - 1.96 * e.se, hi: e.elo + 1.96 * e.se, est: true, u: e.update } : null;
}
function viewCompare(params) {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const runs = compareRuns(), rows = runs.map((n) => o.runs.find((r) => r.name === n));
  runs.forEach(ensureDetail);
  const first = rows[0], names = o.runs.map((r) => r.name);
  // quick picks for the first run: its control, the run it started from, the best rated run
  const best = o.runs.filter((r) => r.elo?.placed).sort((a, b) => b.elo.elo - a.elo.elo)[0];
  const from = first?.start && /^best:/.test(first.start) ? first.start.slice(5) : first?.start ? "start:" + shortVal(first.start) : "";
  const presets = first ? [["its control", first.control], ["its start", names.includes(from) ? from : ""], ["the best rated run", best?.name]]
    .filter(([, n]) => n && n !== first.name).map(([l, n]) => `<button class="pill" data-cmpset="${esc(first.name + "," + n)}" title="${esc(first.name)} vs ${esc(n)}">vs ${l}</button>`).join("") : "";
  const picker = `<div class="rchips">${runs.map((n, i) => `<span class="rchip">${runLink(n)}${i === 0 ? ' <span class="muted small">reference</span>' : ""}<button data-rmrun="${esc(n)}" aria-label="remove ${esc(n)}">×</button></span>`).join("")}
    ${runs.length < MAX_CMP ? '<input class="search add" list="runlist" placeholder="Add a run…" data-addrun aria-label="Add a run">' : ""}${presets ? `<span class="muted small">quick:</span>${presets}` : ""}</div>`;
  const head = `<div class="head"><div><h1>Compare</h1><p>Runs are judged by the Elo of their checkpoint and its goals scored and conceded; two Elos differ when their 95% intervals do not overlap.</p></div></div>`;
  if (!runs.length) return head + picker + '<div class="empty">Add a run to compare.</div>';
  return head + picker + `<div class="grid">${compareTable(rows)}
    <section class="card s6">${cardHead("Checkpoint Elo during training", '<span class="muted small">estimates · 95% interval</span>')}${compareChart(runs, "elo")}</section>
    <section class="card s6">${cardHead("Goals per match", '<span class="muted small">estimates · solid = scored, dashed = conceded</span>')}${compareChart(runs, "goals")}</section>
    ${compareFull(runs, params)}</div>`;
}
function compareTable(rows) {
  const ref = cmpElo(rows[0]);
  const verdict = (e) => (!e || !ref ? "" : e.lo > ref.hi ? '<span class="pos">higher</span>' : e.hi < ref.lo ? '<span class="neg">lower</span>' : '<span class="muted">intervals overlap</span>');
  const tr = (r, i) => {
    const e = cmpElo(r), g = ladderGoals(r.elo, r.elo_estimate), cost = r.cost_hours ? (r.cost_hours.train || 0) + (r.cost_hours.eval || 0) : null;
    return `<tr class="${i ? "" : "focus"}"><td>${runLink(r.name)}<div class="muted small">${esc(r.stage || "")}${r.net ? " · net " + esc(r.net) : ""}</div></td><td><span class="st ${esc(r.state)}">${esc(r.state)}</span></td>
      <td class="r">${e ? eloText(e.elo, (e.hi - e.lo) / 2, e.est) : "–"}<div class="muted small">${e ? (e.est ? `estimate u${e.u}` : "rated") : ""}</div></td>
      <td class="r">${i && e && ref ? `<b class="${tone(e.elo - ref.elo)}">${sgn(e.elo - ref.elo, 0)}</b><div class="small">${verdict(e)}</div>` : '<span class="muted small">reference</span>'}</td>
      <td class="r ${g?.est ? "est" : ""}">${g ? f(g.gf) : "–"}</td><td class="r ${g?.est ? "est" : ""}">${g ? f(g.ga) : "–"}</td><td class="r ${tone(g?.gd)}">${g ? sgn(g.gd) : "–"}</td>
      <td class="r">${r.update ?? "–"}${r.target ? `<span class="pm">/${r.target}</span>` : ""}</td><td class="r">${cost != null ? f(cost, 1) + " h" : "–"}</td></tr>`;
  };
  return `<section class="card flush s12"><table><thead><tr><th>Run</th><th>State</th><th class="r">Checkpoint Elo</th><th class="r">vs reference</th><th class="r">GF</th><th class="r">GA</th><th class="r">GD</th><th class="r">Updates</th><th class="r">Cost</th></tr></thead>
    <tbody>${rows.map(tr).join("")}</tbody></table><p class="muted small pad">GF / GA: goals per 90 s match against the average rated team (grey = estimated during training).</p></section>`;
}
function compareChart(runs, what) {
  const es = (n) => state.detail[n]?.estimates || [];
  const series = what === "elo"
    ? runs.map((n) => ({ name: n, color: runColor(n), points: es(n).map((e) => ({ x: e.update, y: e.elo, err: 1.96 * e.se })), dots: true }))
    : runs.flatMap((n) => [{ name: n + " scored", color: runColor(n), points: es(n).map((e) => ({ x: e.update, y: e.gf })), dots: true },
      { name: n + " conceded", color: runColor(n), points: es(n).map((e) => ({ x: e.update, y: e.ga })), dashed: true }]);
  return lineChart(series, what === "elo" ? { size: "m", xMin: 0, key: "cmp-elo", xTitle: "update", yTitle: "checkpoint Elo", fmt: (v) => f(v, 0), legend: true, emptyText: "No estimates yet" }
    : { size: "m", xMin: 0, yMin: 0, key: "cmp-g", xTitle: "update", yTitle: "goals / match", legend: true, emptyText: "No estimates yet" });
}
// folded away: the latest full evaluation (or fast check) of each run against the first, same protocol only, paired when possible
onSeg.cmpkind = (v) => { const p = route().params; p.set("kind", v); location.hash = "#/compare?" + p.toString(); };
function compareFull(runs, params) {
  const kind = params.get("kind") || "full", ref = runs[0], latestOf = (n) => (state.detail[n]?.evals || []).filter((e) => e.kind === kind).pop();
  const rows = [], warn = [];
  for (const n of runs.slice(1)) {
    const a = latestOf(n), b = latestOf(ref);
    if (!a || !b) { if (state.detail[n] && state.detail[ref]) warn.push(`${n}: no ${kind} evaluation`); continue; }
    if (a.protocol !== b.protocol) { warn.push(`${n}: protocol ${a.protocol} ≠ ${b.protocol}`); continue; }
    const key = `${n}|${a.update}|${kind}|${ref}`, c = state.cmpCache[key];
    if (!c) fetchCompare(n, a, ref, b.update, key);
    rows.push({ label: n, d: c && c.pts != null ? c.pts : a.pts - b.pts, se: c && c.pts != null ? c.pts_se : Math.hypot(a.se, b.se), sig: c && c.z != null ? Math.abs(c.z) > 1.96 : null, sub: c && c.z != null ? `z ${f(c.z, 1)}${c.paired ? " paired" : ""}` : "…" });
  }
  const metrics = [["League pts", (e) => e.pts, (e) => e.se], ["Goal difference", (e) => e.gd, (e) => e.gd_se], ["Conceded", (e) => e.ga], ["vs RL Team 4", (e) => e.h2h?.["RL Team 4"]?.pts], ["vs RL Team 5", (e) => e.h2h?.["RL Team 5"]?.pts],
    ["Direction changes/s", (e) => e.behaviour?.dir_changes_s], ["Idle %", (e) => e.behaviour?.idle_pct], ["Spacing px", (e) => e.behaviour?.spacing_px]];
  const r0 = latestOf(ref);
  const cell = (n, i, g, s) => { const e = latestOf(n), v = e ? g(e) : null, dv = i && v != null && r0 && g(r0) != null ? v - g(r0) : null; return `<td class="r">${f(v)}${s && e && s(e) != null ? `<span class="pm">±${f(s(e))}</span>` : ""}${dv != null ? `<div class="small ${tone(dv) || "muted"}">${sgn(dv)}</div>` : ""}</td>`; };
  const table = `<table><thead><tr><th>Latest ${kind}</th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${metrics.map(([lbl, g, s]) => `<tr><td>${lbl}</td>${runs.map((n, i) => cell(n, i, g, s)).join("")}</tr>`).join("")}</tbody></table>`;
  const style = runs.some((n) => state.detail[n]?.scout) ? `<table><thead><tr><th>Style</th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${STYLE.map(([k, l, dec]) => `<tr><td>${l}</td>${runs.map((n) => `<td class="r">${f(state.detail[n]?.scout?.[k], dec)}</td>`).join("")}</tr>`).join("")}</tbody></table>` : "";
  return `<details class="card s12" ${state.open.cmpfull ? "open" : ""}><summary data-open="cmpfull">Full evaluations against the rule teams: league points, behaviour, style</summary>
    <div class="toolbar">${seg("cmpkind", [["full", "Full evaluations"], ["fast", "Fast checks"]], kind)}<span class="muted small">same protocol only · not used to judge runs</span></div>
    ${warn.length ? `<div class="flag warn">${warn.map(esc).join(" · ")}</div>` : ""}
    <div class="grid"><div class="s6">${forest(rows)}</div><div class="s6 tbl-wrap">${table}</div><div class="s12 tbl-wrap">${style}</div></div></details>`;
}
