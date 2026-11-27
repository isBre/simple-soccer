// The Lab (web/lab/core.js has the overview): the Ranking page.
"use strict";

// ---------- RANKING: this machine's ratings of one team size (elo/, local/elo.db; lab/ladder.py ranking) ----------
const LEAGUES = [["all", "All"], ["rules", "Rule Based"], ["rl", "Reinforcement Learning"], ["mixed", "Mixed"], ["mine", "My Teams"]];
const LEAGUE_COLOR = { rules: "--c5", rl: "--c1", mixed: "--c3", mine: "--c4" };
const rk = { data: null, t: 0, league: "all", size: 5 };
function loadRanking(force) {
  if (pending._rk || (!force && rk.data && rk.data.size === rk.size && Date.now() - rk.t < POLL_MS)) return;
  pending._rk = true;
  getJSON("/api/ranking?size=" + rk.size).then((d) => { rk.data = d; rk.t = Date.now(); render(); })
    .catch(() => { rk.data = { error: true }; rk.t = Date.now(); render(); }).finally(() => { delete pending._rk; });
}
const LEAGUE_SHORT = { rules: "Rules", rl: "RL", mixed: "Mixed", mine: "Mine" };
const leagueChip = (lg) => `<span class="chip" title="${esc((LEAGUES.find((l) => l[0] === lg) || [lg, lg])[1])} League" style="border-color:${css(LEAGUE_COLOR[lg] || "--muted")};color:${css(LEAGUE_COLOR[lg] || "--muted")}">${esc(LEAGUE_SHORT[lg] || lg)}</span>`;
function viewRanking() {
  loadRanking();
  const d = rk.data;
  if (!d) return '<div class="empty">Loading…</div>';
  if (d.error) return '<div class="empty">The ranking could not be computed (see the web app\'s log).</div>';
  const head = `<div class="head"><div><h1>Ranking · ${d.size}v${d.size}</h1><p>This machine's ratings (elo/, docs/ratings.md): every player (as five copies of itself), every team (the average of its players on the pitch plus a small bonus) and every training checkpoint, from matches between them (${d.size}v${d.size} on the arena, 90 s, every pair from both sides with the same seed). The average rule-based player is 1500; 400 points more means 10:1 odds. The bar is the 95% interval (relative to that average). GF / GA: goals scored and conceded per match against the average team, adjusted for who each team played. New teams play ${6} placement games first.</p></div>
    <div class="pills">${[1, 2, 3, 4, 5].map((n) => `<button class="pill ${rk.size === n ? "on" : ""}" data-rksize="${n}">${n}v${n}</button>`).join("")}</div>
    <div class="pills">${LEAGUES.map(([k, l]) => { const n = k === "all" ? d.rows.length : d.rows.filter((r) => r.league === k).length; return n || k === "all" ? `<button class="pill ${rk.league === k ? "on" : ""}" data-league="${k}">${esc(l)} <span class="muted">${n}</span></button>` : ""; }).join("")}</div></div>`;
  const rows = d.rows.filter((r) => rk.league === "all" || r.league === rk.league);
  const played = d.rows.filter((r) => r.games), lead = played[0];
  const kpis = `<div class="kpis">${kpi("Matches", d.matches.toLocaleString(), d.stale ? `${d.stale} no longer count (a file changed)` : "all count")}${kpi("Teams ranked", `${played.length}<small>/ ${d.rows.length}</small>`, `${d.rows.filter((r) => r.placed).length} placed`)}${kpi("Top", lead ? esc(lead.name) : "–", lead ? `${f(lead.elo, 0)} · ${esc(lead.league)}` : "")}${kpi("Last match", d.last ? ago(d.last) : "–", d.off ? "ladder off (exp/ladder_off)" : "the Pi plays rounds when the queue is empty")}</div>`;
  if (!d.matches) return head + kpis + '<div class="card"><h2>No matches yet</h2><p class="muted">Run <span class="mono">python3 -m elo init</span> once on this machine; after that the web app and the runner keep playing rounds whenever the machine is idle.</p></div>';
  const lo = Math.min(...rows.map((r) => r.lo)), hi = Math.max(...rows.map((r) => r.hi)), W = 200;
  const X = (v) => 6 + ((v - lo) / (hi - lo || 1)) * (W - 12);
  const axis = niceTicks(lo, hi, 5);
  const bar = (r) => `<svg width="${W}" height="16" viewBox="0 0 ${W} 16" class="rkbar">${axis.map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="0" y2="16" stroke="var(--grid)"/>`).join("")}<line x1="${X(r.lo)}" x2="${X(r.hi)}" y1="8" y2="8" stroke="${css(LEAGUE_COLOR[r.league] || "--muted")}" stroke-width="3" stroke-linecap="round" opacity="${r.placed ? 0.55 : 0.25}"/><circle cx="${X(r.elo)}" cy="8" r="4.5" fill="${css(LEAGUE_COLOR[r.league] || "--muted")}" opacity="${r.placed ? 1 : 0.5}"><title>${f(r.lo, 0)} – ${f(r.hi, 0)}</title></circle></svg>`;
  const body = rows.map((r) => `<tr class="${r.placed ? "" : "dim"}"><td class="r muted">${r.rank}</td><td title="${esc(r.kind === "rules" ? "handmade AI" : r.model || "")}"><b>${esc(r.name)}</b>${' <span class="muted small">' + ({ player: r.kind === "net" ? "net player" : "player", team: r.via ? "team of one player" : "team", net: "checkpoint" }[r.entry] || "") + "</span>"}</td><td>${leagueChip(r.league)}</td>
    <td class="r"><b>${f(r.elo, 0)}</b><span class="pm">±${f(1.96 * r.se, 0)}</span></td><td>${bar(r)}</td><td class="r">${r.games}${r.placed ? "" : ' <span class="small muted">placing</span>'}</td>
    <td class="r nowrap">${r.w}–${r.d}–${r.l}</td><td class="r">${r.games && r.agf != null ? f(r.agf) : "–"}</td><td class="r">${r.games && r.aga != null ? f(r.aga) : "–"}</td><td class="r ${r.agf - r.aga > 0 ? "pos" : r.agf - r.aga < 0 ? "neg" : ""}">${r.games && r.agf != null ? sgn(r.agf - r.aga) : "–"}</td></tr>`).join("");
  const table = `<section class="card flush"><div class="tbl-wrap"><table class="rank"><thead><tr><th class="r">#</th><th>Team</th><th>League</th><th class="r">Elo</th><th><span class="small muted">${f(lo, 0)} … ${f(hi, 0)}</span></th><th class="r">Games</th><th class="r">W–D–L</th><th class="r" title="goals scored per 90 s match against the average team of the ladder (Poisson attack / defence model of all matches: adjusted for who was played)">GF</th><th class="r" title="goals conceded per 90 s match against the average team of the ladder (adjusted)">GA</th><th class="r">GD</th></tr></thead><tbody>${body}</tbody></table></div></section>`;
  // history: the rating after each round, for the top teams of the filter
  const top = rows.filter((r) => r.games).slice(0, 8);
  const series = top.map((r, i) => ({ name: r.name, color: css(PALETTE[i % PALETTE.length]), points: d.history.filter((h) => h.elo[r.id] != null).map((h) => ({ x: parseT(h.t), y: h.elo[r.id] })) }));
  const hist = `<section class="card"><div class="card-h"><h2>Rating history</h2><span class="muted small">top ${top.length} of the list above, after every round</span></div>${lineChart(series, { height: 220, time: true, key: "rkh", fmt: (v) => f(v, 0), emptyText: "the history starts with the next round" })}</section>`;
  const name = Object.fromEntries(d.rows.map((r) => [r.id, r.name]));
  const recent = d.recent.slice(-15).reverse().map((m) => `<tr><td class="muted small nowrap">${esc(ago(m.t))}</td><td class="r">${esc(name[m.a] || m.a)}</td><td class="r"><b>${m.ga}–${m.gb}</b></td><td>${esc(name[m.b] || m.b)}</td></tr>`).join("");
  const rec = `<section class="card flush"><div class="card-h pad"><h2>Latest matches</h2><span class="muted small">left team's goals first</span></div><div class="tbl-wrap"><table class="mini"><tbody>${recent}</tbody></table></div></section>`;
  return head + kpis + table + `<div class="grid g2">${hist}${rec}</div>`;
}
