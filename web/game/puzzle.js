// The Game (web/game.js has the overview): puzzle mode.
import { $, G, btn, card, go, header, mount, prefs, savePrefs, shell, table, teamCell } from "./core.js";
import { match, play, stopMatch } from "./match.js";
import { menu } from "./menu.js";
import { recToggle, seg } from "./quick.js";
import { ACC, FONT, clockText, roundRect, text } from "./render.js";
import { teams } from "./teams.js";

// ---------- puzzle: rounds of at most 1 minute from a random layout, random teams every round, until the session time is used ----------
// Every round: two random teams (any league), random sides, every player and the ball at random places (game/session.py), over at
// the first goal. Points: you score first 3, nobody scores in 60 s 1, they score first 0. Recorded for the dataset when "Record my
// play" is on (one file per round, grouped by session on the Lab's Dataset page).
export const PZ_LENGTHS = [300, 600, 900];
export const PZ_BEST = "soccer.puzzleBest";
export const pzBest = () => { try { return JSON.parse(localStorage.getItem(PZ_BEST) || "{}"); } catch (e) { return {}; } };
export const pzPlayed = (pz) => pz.rounds.reduce((s, r) => s + r.secs, 0);
export function puzzlePage() {
  const pz = G.pz;
  if (pz && pz.done) return puzzleSummary(pz);
  const best = pzBest();
  const st = { control: prefs.pzControl ?? 0, len: prefs.pzLen ?? 1 };
  const v = mount(shell(`<div class="gn pz">
      <section class="gp-card"><h2>Puzzle</h2><p class="pz-intro">Rounds of at most one minute: two random teams, every player and the ball at a random place, over at the first goal. Keep going until the time is up.</p>
        <div class="pz-pts"><div><b>3</b>you score first</div><div><b>1</b>nobody scores in 60 s</div><div><b>0</b>they score first</div></div>
        <p class="g-caption">Each round starts from a different situation (attacking, defending, or the last one back), which makes it good data for the models: keep "Record" on.</p>
        <p class="g-caption">Best: ${PZ_LENGTHS.map((l) => `${l / 60} min <b>${best[l] != null ? best[l] : "–"}</b>`).join(" &nbsp;·&nbsp; ")}</p></section>
      <section class="gp-card gn-form"><h2>Session</h2><div class="gn-fields" id="pz-left"></div>
        <div class="gn-foot"><span class="g-caption">One player is picked at random each round</span><button type="button" class="ks-go" id="pz-go">Start</button></div></section></div>`,
    [["Enter", "start"], ["Esc", "menu"]]));
  const ctl = seg("Control", ["One player", "Whole team"], Math.min(1, st.control), (i) => { st.control = i; prefs.pzControl = i; savePrefs(); });
  const len = seg("Length (minutes)", PZ_LENGTHS.map((l) => String(l / 60)), st.len, (i) => { st.len = i; prefs.pzLen = i; savePrefs(); });
  $("#pz-left", v).append(ctl.el, len.el, recToggle());
  const start = () => {
    G.pz = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), total: PZ_LENGTHS[st.len], control: ["single", "team"][st.control], rounds: [], done: false };
    nextRound();
  };
  $("#pz-go", v).onclick = start;
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    if (e.key === "Escape") go("#/game");
    else if (e.key === "Enter" && document.activeElement?.tagName !== "BUTTON") { e.preventDefault(); start(); }
  };
}
export function nextRound() {
  const pz = G.pz, all = G.cat.teams;
  const a = Math.floor(Math.random() * all.length); let b = Math.floor(Math.random() * (all.length - 1)); if (b >= a) b += 1;
  const setup = { home: all[a].id, away: all[b].id, pitch: "arena", size: 5, duration: 60, seed: Math.floor(Math.random() * 2147483647), control: pz.control,
    human_team: Math.random() < 0.5 ? 0 : 1, allow_draw: true, player: "random", record: prefs.record, session: pz.id, round: pz.rounds.length + 1 };
  const p = { setup, puzzle: Math.floor(Math.random() * 2147483647), session: pz, done: (res) => roundOver(res, setup), quit: () => { pz.done = true; pz.quit = true; finishPuzzle(); } };
  if (location.hash === "#/game/match") { stopMatch(); G.pending = p; match(p); }
  else play(p);
}
export function roundOver(res, setup) {
  const pz = G.pz; if (!pz || pz.done) return;
  const h = setup.human_team, gf = res.scores[h], ga = res.scores[1 - h], goal = res.puzzle?.end === "goal";
  const outcome = goal ? (gf > ga ? "W" : "L") : "D";
  pz.rounds.push({ home: setup.home, away: setup.away, h, gf, ga, outcome, secs: Math.min(60, res.puzzle?.seconds ?? 60), pts: { W: 3, D: 1, L: 0 }[outcome] });
  if (pzPlayed(pz) >= pz.total) { pz.done = true; finishPuzzle(); } else nextRound();
}
export function finishPuzzle() {
  const pz = G.pz;
  if (!pz.quit) { const best = pzBest(), score = pz.rounds.reduce((s, r) => s + r.pts, 0); if (best[pz.total] == null || score > best[pz.total]) { best[pz.total] = score; pz.newBest = true; try { localStorage.setItem(PZ_BEST, JSON.stringify(best)); } catch (e) {} } }
  stopMatch();
  G.pending = null;
  if (location.hash === "#/game/puzzle") puzzlePage(); else go("#/game/puzzle");
}
export function puzzleSummary(pz) {
  const R = pz.rounds, score = R.reduce((s, r) => s + r.pts, 0), n = R.length, cnt = (o) => R.filter((r) => r.outcome === o).length;
  const wins = R.filter((r) => r.outcome === "W"), avgWin = wins.length ? wins.reduce((s, r) => s + r.secs, 0) / wins.length : null;
  const team = (id) => G.byId[id] || { id, name: id };
  const rows = R.map((r, i) => { const me = team(r.h === 0 ? r.home : r.away), them = team(r.h === 0 ? r.away : r.home);
    return { cells: [{ text: i + 1, color: "var(--g-muted)" }, teamCell(me, me.name), teamCell(them, them.name), { text: r.outcome === "W" ? "you scored" : r.outcome === "L" ? "they scored" : "no goal", color: r.outcome === "W" ? "var(--g-good)" : r.outcome === "L" ? "var(--g-bad)" : "var(--g-muted)" }, `${r.secs.toFixed(1)} s`, { text: `+${r.pts}`, color: "var(--g-accent)" }] }; });
  const v = mount(`<div class="g-page">${header(pz.quit ? "Puzzle - stopped early" : "Puzzle - final score", `${pz.total / 60} minute session · ${n} rounds · ${Math.round(pzPlayed(pz))} s played`)}
    <div class="g-card g-center" style="padding:24px"><div style="font-size:84px;line-height:1;color:var(--g-accent);font-weight:600">${score}</div><div style="font-size:20px;margin-top:6px">points${pz.newBest ? ' &nbsp;<span class="g-accent">NEW BEST</span>' : ""}</div>
      <div class="g-row" style="justify-content:center;gap:36px;margin-top:18px;font-size:20px"><span><b>${cnt("W")}</b> won</span><span><b>${cnt("D")}</b> no goal</span><span><b>${cnt("L")}</b> lost</span>
      <span>goals <b>${R.reduce((s, r) => s + r.gf, 0)}–${R.reduce((s, r) => s + r.ga, 0)}</b></span><span>points / round <b>${n ? (score / n).toFixed(2) : "–"}</b></span><span>time to score <b>${avgWin != null ? avgWin.toFixed(1) + " s" : "–"}</b></span></div></div>
    ${n ? table([{ t: "#", w: 44 }, { t: "You" }, { t: "Opponent" }, { t: "Round" }, { t: "Time", w: 90, a: "r" }, { t: "Pts", w: 70, a: "r" }], rows) : ""}
    <div class="g-buttons">${btn("Menu", 'id="pz-menu" style="width:140px"', "ghost big")}<span class="g-spacer"></span>${btn("Play again&nbsp;&nbsp;(Enter)", 'id="pz-again" style="width:260px"', "primary big")}</div></div>`);
  const again = () => { G.pz = null; puzzlePage(); };
  $("#pz-menu", v).onclick = () => { G.pz = null; go("#/game"); };
  $("#pz-again", v).onclick = again;
  window.scrollTo(0, 0);
  G.keyHandler = (e, down) => { if (!down || e.repeat) return; if (e.key === "Enter") { e.preventDefault(); again(); } else if (e.key === "Escape") { G.pz = null; go("#/game"); } };
}
export function drawPuzzleHud(ctx, M, f, W, H, intro) {
  const n = M.p.session.rounds.length + 1;
  drawPuzzleCard(ctx, M, f, W);
  if (intro > 0) {
    const a = Math.min(1, intro / 20);
    ctx.fillStyle = `rgba(0,0,0,${0.45 * a})`; ctx.fillRect(0, H / 2 - 190, W, 96);
    text(ctx, `ROUND ${n}`, 0, H / 2 - 132, "c", W, 46, `rgba(255,255,255,${a})`, 6, `rgba(0,0,0,${a})`);
    text(ctx, M.meta.control === 1 ? "GET READY - FIND YOUR PLAYER" : "GET READY", 0, H / 2 - 104, "c", W, 18, Draw.css(ACC, a));
  }
  if (M.result) {
    const h = M.meta.human_team, sc = M.result.scores, goal = M.result.puzzle?.end === "goal";
    const [msg, col] = !goal ? ["TIME UP - NO GOAL   +1", "#fff"] : sc[h] > sc[1 - h] ? ["YOU SCORED   +3", "#46c98d"] : ["THEY SCORED   +0", "#ef6a5b"];
    ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(0, H - 120, W, 64);
    text(ctx, msg, 0, H - 76, "c", W, 34, col);
  }
}

// the puzzle card, top right, one row as tall as the scorebug: ROUND n | one dot per round played | points | session time left
// (a thin bar along its bottom edge fills as the session goes)
export function drawPuzzleCard(ctx, M, f, W) {
  const pz = M.p.session, R = pz.rounds, n = R.length + 1, pts = R.reduce((s, r) => s + r.pts, 0);
  const left = Math.max(0, pz.total - pzPlayed(pz) - (60 - f.tl)), used = Math.min(1, 1 - left / pz.total), low = left < 30;
  const h = 38, pad = 12, y0 = 14, MUTED = "#8d98ab", step = 12, r = 4, MAXD = 8;
  const round = `ROUND ${n}`, clock = clockText(left), shown = R.slice(-MAXD);
  ctx.font = FONT(15, 700); const rw = ctx.measureText(round).width;
  ctx.font = FONT(20, 800); const pw = ctx.measureText(String(pts)).width;
  ctx.font = FONT(11, 700); const uw = ctx.measureText("PTS").width;
  ctx.font = FONT(15, 700); const kw = ctx.measureText(clock).width;
  const segR = rw + 2 * pad, segD = (shown.length + 1) * step - (step - 2 * r) + 2 * pad - 2, segP = pw + 5 + uw + 2 * pad, segK = kw + 2 * pad;
  const w = segR + segD + segP + segK, x0 = W - 16 - w;
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.35)"; ctx.shadowBlur = 14; ctx.shadowOffsetY = 4;
  roundRect(ctx, x0, y0, w, h, 9, "#12161d");
  ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.roundRect(x0, y0, w, h, 9); ctx.clip();
  let x = x0;
  text(ctx, round, x, y0 + 25, "c", segR, 15, "#fff", 0, "", 700); x += segR;
  // dots: green = you scored, grey = no goal, red = they scored; the current round hollow (the newest MAXD rounds)
  const col = { W: "#46c98d", D: "#5b6577", L: "#ef6a5b" }, cy = y0 + h / 2 - 1;
  let dx = x + pad - 1 + r;
  for (const rd of shown) { ctx.beginPath(); ctx.arc(dx, cy, r, 0, 2 * Math.PI); ctx.fillStyle = col[rd.outcome]; ctx.fill(); dx += step; }
  const pulse = 0.55 + 0.45 * Math.abs(Math.sin(performance.now() / 400));
  ctx.beginPath(); ctx.arc(dx, cy, r - 0.75, 0, 2 * Math.PI); ctx.lineWidth = 1.5; ctx.strokeStyle = Draw.css(ACC, pulse); ctx.stroke();
  x += segD;
  ctx.fillStyle = "#0b0e13"; ctx.fillRect(x, y0, segP, h);
  text(ctx, String(pts), x + pad, y0 + 27, "l", 0, 20, "#ffd54a", 0, "", 800);
  text(ctx, "PTS", x + pad + pw + 5, y0 + 26, "l", 0, 11, MUTED, 0, "", 700); x += segP;
  ctx.fillStyle = low ? "#ef6a5b" : "#ffd54a"; ctx.fillRect(x, y0, segK, h);
  text(ctx, clock, x, y0 + 25, "c", segK, 15, "#12161d", 0, "", 700);
  // session progress along the bottom edge
  ctx.fillStyle = "rgba(255,255,255,0.08)"; ctx.fillRect(x0, y0 + h - 3, w, 3);
  ctx.fillStyle = low ? "#ef6a5b" : "#ffd54a"; ctx.fillRect(x0, y0 + h - 3, w * used, 3);
  ctx.restore();
  M.pzCard = { x: x0, y: y0, w, h };
}
