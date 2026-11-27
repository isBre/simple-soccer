// The Lab (web/lab/core.js has the overview): the Ranking page: this machine's ratings of one team size (elo/, local/elo.db;
// lab/ladder.py ranking; docs/ratings.md). Three separate lists of one fit: players (each as five copies of itself), teams (line-ups;
// a team of one player five times has that player's numbers) and the Lab's training checkpoints.
"use strict";

const LEAGUES = [["all", "All leagues"], ["rules", "Rule based"], ["rl", "Reinforcement learning"], ["mixed", "Mixed"], ["mine", "My teams"]];
const LEAGUE_COLOR = { rules: "--c5", rl: "--c1", mixed: "--c3", mine: "--c4" };
const LEAGUE_SHORT = { rules: "Rules", rl: "RL", mixed: "Mixed", mine: "Mine" };
const WHAT = [["player", "Players", "Player"], ["team", "Teams", "Team"], ["net", "Checkpoints", "Checkpoint"]];
const rk = { data: null, t: 0, league: "all", size: 5, what: "player", q: "", placed: false };
function loadRanking(force) {
  if (pending._rk || (!force && rk.data && rk.data.size === rk.size && Date.now() - rk.t < POLL_MS)) return;
  pending._rk = true;
  getJSON("/api/ranking?size=" + rk.size).then((d) => { rk.data = d; rk.t = Date.now(); render(); })
    .catch(() => { rk.data = { error: true }; rk.t = Date.now(); render(); }).finally(() => { delete pending._rk; });
}
const leagueChip = (lg) => `<span class="chip" title="${esc((LEAGUES.find((l) => l[0] === lg) || [lg, lg])[1])} league" style="border-color:${css(LEAGUE_COLOR[lg] || "--muted")};color:${css(LEAGUE_COLOR[lg] || "--muted")}">${esc(LEAGUE_SHORT[lg] || lg)}</span>`;
const rkReset = () => { state.page.rank = 0; rerender(); };
onSeg.rksize = (v) => { rk.size = +v; state.page.rank = 0; loadRanking(true); };
onSeg.rkwhat = (v) => { rk.what = v; rk.league = "all"; rkReset(); };
onSeg.rkleague = (v) => { rk.league = v; rkReset(); };
onSeg.rkplaced = (v) => { rk.placed = v; rkReset(); };
onSeg.rksearch = (v) => { rk.q = v; rkReset(); };
function viewRanking() {
  loadRanking();
  const d = rk.data;
  const head = (extra = "") => `<div class="head"><div><h1>Ranking · ${rk.size}v${rk.size}</h1><p>This machine's ratings: the average rule-based player is 1500, 400 points more means 10:1 odds, ± is the 95% interval.
      <a href="#/docs/docs__ratings.md">About the ratings →</a></p></div>${seg("rksize", [1, 2, 3, 4, 5].map((n) => [n, `${n}v${n}`]), rk.size)}</div>${extra}`;
  if (!d) return head() + '<div class="empty">Loading…</div>';
  if (d.error) return head() + '<div class="empty">The ratings could not be computed (see the web app\'s log).</div>';
  if (!d.matches) return head() + '<div class="card"><h2>No matches yet</h2><p class="muted">Run <span class="mono">python3 -m elo init</span> once on this machine; after that the web app and the runner keep playing rounds whenever the machine is idle.</p></div>';
  if (!d.rows.some((r) => r.entry === rk.what)) rk.what = "player";
  const group = d.rows.filter((r) => r.entry === rk.what).map((r, i) => ({ ...r, rank: i + 1 }));     // ranked within its own list
  const q = rk.q.trim().toLowerCase();
  const rows = group.filter((r) => (rk.league === "all" || r.league === rk.league) && (!rk.placed || r.placed) && (!q || r.name.toLowerCase().includes(q)));
  const played = group.filter((r) => r.games), noun = WHAT.find((w) => w[0] === rk.what);
  const filters = `<div class="fbar">${seg("rkwhat", WHAT.map(([k, l]) => [k, l, d.rows.filter((r) => r.entry === k).length]), rk.what)}
      ${seg("rkleague", LEAGUES.filter(([k]) => k === "all" || group.some((r) => r.league === k)).map(([k, l]) => [k, l, group.filter((r) => k === "all" || r.league === k).length]), rk.league)}
      <input class="search" placeholder="Search a name…" value="${esc(rk.q)}" data-filter="rksearch">
      <label class="fchk ${rk.placed ? "on" : ""}"><input type="checkbox" data-sel="rkplaced" ${rk.placed ? "checked" : ""}> Placed only</label>
      <span class="fcount">${d.matches.toLocaleString()} matches${d.stale ? ` · ${d.stale} no longer count` : ""} · last ${d.last ? esc(ago(d.last)) : "–"}${d.off ? " · rounds off" : ""}</span></div>`;
  const pg = pager("rank", rows, 25);
  const lo = Math.min(...rows.map((r) => r.lo)), hi = Math.max(...rows.map((r) => r.hi)), W = 140;
  const X = (v) => 6 + ((v - lo) / (hi - lo || 1)) * (W - 12);
  const bar = (r) => `<svg width="${W}" height="14" viewBox="0 0 ${W} 14" class="rkbar"><line x1="${X(r.lo)}" x2="${X(r.hi)}" y1="7" y2="7" stroke="${css(LEAGUE_COLOR[r.league] || "--muted")}" stroke-width="3" stroke-linecap="round" opacity="${r.placed ? 0.55 : 0.25}"/><circle cx="${X(r.elo)}" cy="7" r="4" fill="${css(LEAGUE_COLOR[r.league] || "--muted")}" opacity="${r.placed ? 1 : 0.5}"><title>${f(r.lo, 0)} – ${f(r.hi, 0)}</title></circle></svg>`;
  const sub = (r) => ({ player: r.kind === "net" ? "net" : "rule-based", team: r.via ? "one player ×5" : r.sub === "mixed" ? "mixed" : "", net: "" }[r.entry] || "");
  const body = pg.rows.map((r) => `<tr class="${r.placed ? "" : "dim"}"><td class="r muted">${r.rank}</td><td title="${esc(r.kind === "rules" ? "handmade AI" : r.model || "")}"><b>${esc(r.name)}</b> <span class="muted small">${sub(r)}</span></td><td>${leagueChip(r.league)}</td>
    <td class="r">${eloText(r.elo, 1.96 * r.se)}</td><td>${bar(r)}</td><td class="r">${r.games}${r.placed ? "" : ' <span class="small muted">placing</span>'}</td>
    <td class="r nowrap">${r.w}–${r.d}–${r.l}</td><td class="r">${r.games && r.agf != null ? f(r.agf) : "–"}</td><td class="r">${r.games && r.aga != null ? f(r.aga) : "–"}</td><td class="r ${tone(r.agf - r.aga)}">${r.games && r.agf != null ? sgn(r.agf - r.aga) : "–"}</td></tr>`).join("");
  const table = `<section class="card flush s12 sticky"><table class="rank"><thead><tr><th class="r">#</th><th>${noun[2]} <span class="muted small">${played.length} rated · ${esc(eloKind(rk.what))}</span></th><th>League</th><th class="r">Elo</th><th><span class="small muted">${rows.length ? `${f(lo, 0)} … ${f(hi, 0)}` : ""}</span></th><th class="r">Games</th><th class="r">W–D–L</th>
    <th class="r" title="goals scored per 90 s match against the average entry (adjusted for who was played)">GF</th><th class="r" title="goals conceded per 90 s match against the average entry (adjusted)">GA</th><th class="r">GD</th></tr></thead>
    <tbody>${body || '<tr><td colspan="10" class="muted">nothing matches</td></tr>'}</tbody></table>${pg.html}</section>`;
  // history: the rating after each round, for the top 8 of the filtered list
  const top = rows.filter((r) => r.games).slice(0, 8);
  const series = top.map((r, i) => ({ name: r.name, color: css(PALETTE[i % PALETTE.length]), points: d.history.filter((h) => h.elo[r.id] != null).map((h) => ({ x: parseT(h.t), y: h.elo[r.id] })) }));
  const hist = `<section class="card s7">${cardHead("Rating history", `<span class="muted small">the top ${top.length} of the list, after every round</span>`)}${lineChart(series, { size: "m", time: true, key: "rkh", xTitle: "time", yTitle: "Elo", fmt: (v) => f(v, 0), emptyText: "The history starts with the next round" })}</section>`;
  const name = Object.fromEntries(d.rows.map((r) => [r.id, r.name]));
  const pr = pager("rkrecent", d.recent.slice().reverse(), 8);
  const rec = `<section class="card flush s5">${cardHead("Latest matches", '<span class="muted small">left side\'s goals first</span>')}<table class="mini"><tbody>${pr.rows.map((m) => `<tr><td class="muted small nowrap">${esc(ago(m.t))}</td><td class="r">${esc(name[m.a] || m.a)}</td><td class="r"><b>${m.ga}–${m.gb}</b></td><td>${esc(name[m.b] || m.b)}</td></tr>`).join("")}</tbody></table>${pr.html}</section>`;
  return head(filters) + `<div class="grid">${table}${hist}${rec}</div>`;
}
