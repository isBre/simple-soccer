// The Lab (web/lab/core.js has the overview): the Compare page.
"use strict";

// ---------- COMPARE ----------
function viewCompare(params) {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  const names = o.runs.map((r) => r.name);
  let runs = (params.get("runs") || "").split(",").filter((n) => names.includes(n));
  if (!runs.length) runs = [names.find((n) => n.startsWith("start:")), o.status.runner.running?.run].filter(Boolean);
  const kind = params.get("kind") || "full";
  runs.forEach(ensureDetail);
  const ref = runs[0];
  const add = `<select data-addrun><option value="">+ add run…</option>${names.filter((n) => !runs.includes(n)).map((n) => `<option>${esc(n)}</option>`).join("")}</select>`;
  const chipsR = runs.map((n, i) => `<span class="rchip">${runLink(n)}${i === 0 ? ' <span class="muted small">reference</span>' : ""}<button data-rmrun="${esc(n)}" aria-label="remove">×</button></span>`).join("");
  const kinds = ["full", "fast"].map((k) => `<button class="pill ${kind === k ? "on" : ""}" data-kind="${k}">${k === "full" ? "full evaluations" : "fast checks"}</button>`).join("");
  const latestOf = (n) => (state.detail[n]?.evals || []).filter((e) => e.kind === kind).pop();
  const rows = [], warn = [];
  for (const n of runs.slice(1)) {
    const a = latestOf(n), b = latestOf(ref);
    if (!a || !b) { if (state.detail[n] && state.detail[ref]) warn.push(`${n}: no ${kind} evaluation`); continue; }
    if (a.protocol !== b.protocol) { warn.push(`${n}: protocol ${a.protocol} ≠ ${b.protocol}`); continue; }
    const key = `${n}|${a.update}|${kind}|${ref}`, c = state.cmpCache[key];
    if (!c) fetchCompare(n, a, ref, b.update, key);
    rows.push({ label: n, d: c && c.pts != null ? c.pts : a.pts - b.pts, se: c && c.pts != null ? c.pts_se : Math.hypot(a.se, b.se), sig: c && c.z != null ? Math.abs(c.z) > 1.96 : null, sub: c && c.z != null ? `z ${f(c.z, 1)}${c.paired ? " paired" : ""}` : "…" });
  }
  const metrics = [["League pts", (e) => e.pts, (e) => e.se], ["Goal difference", (e) => e.gd, (e) => e.gd_se], ["Conceded", (e) => e.ga], ["Best-move pts", (e) => e.greedy_pts], ["vs RL Team 4", (e) => e.h2h?.["RL Team 4"]?.pts], ["vs RL Team 5", (e) => e.h2h?.["RL Team 5"]?.pts], ["Direction changes/s", (e) => e.behaviour?.dir_changes_s], ["Idle %", (e) => e.behaviour?.idle_pct], ["Spacing px", (e) => e.behaviour?.spacing_px]];
  const r0 = latestOf(ref);
  const table = `<table><thead><tr><th>Latest ${kind}</th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${metrics.map(([lbl, g, s]) => `<tr><td>${lbl}</td>${runs.map((n, i) => { const e = latestOf(n), v = e ? g(e) : null, dv = i && v != null && r0 && g(r0) != null ? v - g(r0) : null; return `<td class="r">${f(v)}${s && e && s(e) != null ? `<span class="pm">±${f(s(e))}</span>` : ""}${dv != null ? `<div class="small ${dv > 0 ? "pos" : dv < 0 ? "neg" : "muted"}">${sgn(dv)}</div>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table>`;
  const styleTable = runs.some((n) => state.detail[n]?.scout) ? `<section class="card flush" style="margin-bottom:14px"><div class="card-h pad"><h2>Style</h2><span class="muted small">latest scouting data of each run</span></div><div class="tbl-wrap"><table><thead><tr><th></th>${runs.map((n) => `<th class="r">${runLink(n)}</th>`).join("")}</tr></thead><tbody>${STYLE.map(([k, l, dec]) => `<tr><td>${l}</td>${runs.map((n) => `<td class="r">${f(state.detail[n]?.scout?.[k], dec)}</td>`).join("")}</tr>`).join("")}<tr><td>Tags</td>${runs.map((n) => `<td class="r small">${state.detail[n]?.scout ? esc(styleTags(state.detail[n].scout).join(", ")) : "–"}</td>`).join("")}</tr></tbody></table></div></section>` : "";
  const tr = runs.map((n) => ({ name: n, color: runColor(n), points: ema((state.detail[n]?.training || []).map((r) => ({ x: r.upd, y: r.rules })), state.smooth) }));
  const ev = runs.map((n) => ({ name: n, color: runColor(n), points: (state.detail[n]?.evals || []).filter((e) => e.kind === kind).map((e) => ({ x: e.update, y: e.pts, err: 1.96 * e.se })), dots: true, noLine: true }));
  return `<div class="head"><div><h1>Compare</h1><p>Each run against the first, on the same evaluation protocol only; paired over identical matches when possible.</p></div><div class="pills">${kinds}</div></div>
    <div class="rchips">${chipsR}${add}</div>${warn.length ? `<div class="flag warn">${warn.map(esc).join(" · ")}</div>` : ""}
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Difference vs ${esc(ref || "")}</h2><span class="muted small">league pts, 95% interval</span></div>${forest(rows)}</section>
      <section class="card flush"><div class="tbl-wrap">${table}</div></section></div>
    ${styleTable}
    <div class="grid g2"><section class="card"><div class="card-h"><h2>Training points vs rule bots</h2>${smoothControl()}</div>${lineChart(tr, { yMin: 0, yMax: 3, height: 220, key: "cmp-tr" })}</section>
      <section class="card"><div class="card-h"><h2>${kind === "full" ? "Full evaluations" : "Fast checks"}</h2><span class="muted small">95% interval</span></div>${lineChart(ev, { yMin: 0, yMax: 3, height: 220, xMin: 0, key: "cmp-ev" })}</section></div>`;
}
