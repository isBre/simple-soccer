// The Lab (web/lab/core.js has the overview): the Dataset page and the replay of a recorded match.
"use strict";

// ---------- DATASET: the user's recorded play (data/human/, game/recorder.py), analysed by il/analysis.py ----------
const MOVE_NAMES = ["stand", "up", "up + forward", "forward", "down + forward", "down", "down + back", "back", "up + back"];
const MOVE_VEC = [[0, 0], [0, -1], [0.707, -0.707], [1, 0], [0.707, 0.707], [0, 1], [-0.707, 0.707], [-1, 0], [-0.707, -0.707]];
const ds = { data: null, t: 0, replay: null };
function loadDataset(force) {
  if (pending._ds || (!force && ds.data && Date.now() - ds.t < POLL_MS)) return;
  pending._ds = true;
  getJSON("/api/dataset").then((d) => { ds.data = d; ds.t = Date.now(); render(); })
    .catch(() => { ds.data = { error: true }; ds.t = Date.now(); render(); }).finally(() => { delete pending._ds; });
}
// the 9 moves as a radar in the player's own frame (right = towards the opponent goal): an octagon whose corners sit at each
// direction's share of the decisions (rings at 25 / 50 / 75 / 100% of the most used direction); the centre dot = standing still
function compass(moves, color, size = 220, labels = true) {
  const c = size / 2, R = c - (labels ? 34 : 4), mx = Math.max(...moves.slice(1), 1), pt = (i, r) => [c + MOVE_VEC[i][0] * r, c + MOVE_VEC[i][1] * r];
  const ring = (k) => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => pt(i, R * k).map((v) => v.toFixed(1)).join(",")).join(" ");
  let g = "";
  for (const k of [0.25, 0.5, 0.75, 1]) g += `<polygon points="${ring(k)}" fill="${k === 1 ? "var(--panel-2)" : "none"}" stroke="var(--line)" stroke-width="1"/>`;
  for (let i = 1; i < 9; i++) { const [x, y] = pt(i, R); g += `<line x1="${c}" y1="${c}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--line)"/>`; }
  const shape = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => pt(i, R * Math.max(0.04, moves[i] / mx)).map((v) => v.toFixed(1)).join(",")).join(" ");
  g += `<polygon points="${shape}" fill="${color}" fill-opacity=".35" stroke="${color}" stroke-width="${labels ? 2.5 : 1.5}" stroke-linejoin="round"/>`;
  for (let i = 1; i < 9; i++) {
    const [x, y] = pt(i, R * Math.max(0.04, moves[i] / mx));
    if (labels) g += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="${color}"><title>${MOVE_NAMES[i]}: ${f(moves[i], 1)}%</title></circle>`;
    if (labels) { const [lx, ly] = pt(i, R + 18); g += `<text x="${lx.toFixed(1)}" y="${(ly + 4).toFixed(1)}" text-anchor="middle" class="ax">${f(moves[i], 0)}%</text>`; }
  }
  g += `<circle cx="${c}" cy="${c}" r="${(labels ? 3 : 2) + (labels ? 12 : 6) * Math.sqrt(moves[0] / 100)}" fill="var(--panel)" stroke="${color}" stroke-width="1.5"><title>stand: ${f(moves[0], 1)}%</title></circle>`;
  if (labels) g += `<text x="${size - 2}" y="${size - 4}" text-anchor="end" class="ax">→ goal</text>`;
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" style="max-width:100%">${g}</svg>`;
}
function vsBar(label, v, net, rules, dec, unit = "") {
  const mx = Math.max(v || 0, net || 0, rules || 0) * 1.12 || 1, col = css("--c3");
  const tick = (x, name, cl) => (x == null ? "" : `<span class="rf" style="left:${(100 * x) / mx}%;background:${cl}" title="${name} ${f(x, dec)}${unit}"></span>`);
  return `<div class="bh vs"><div class="bl">${label}</div><div class="bt"><i style="width:${(100 * (v || 0)) / mx}%;background:${col}"></i>${tick(net, "net", "var(--c2)")}${tick(rules, "rule bots", "var(--ink)")}</div>
    <div class="bv"><b>${f(v, dec)}</b>${unit}<span class="pm"> net ${f(net, dec)} · rules ${f(rules, dec)}</span></div></div>`;
}
function viewDataset(id) {
  if (id) return viewReplay(id);
  loadDataset();
  const d = ds.data;
  if (!d) return '<div class="empty">Loading…</div>';
  if (d.error) return '<div class="empty">The dataset could not be read (see the web app\'s log).</div>';
  const head = `<div class="head"><div><h1>Dataset</h1><p>Your play, recorded in the Game with "Record my play" on: every decision (30 per second) of the player you control, as the nets see it. This is what the ML and DL leagues will learn from. Files: <span class="mono">${esc(d.folder)}/</span></p></div></div>`;
  if (d.empty) return head + `<div class="card"><h2>Nothing recorded yet</h2><p class="muted">Play a match in the Game (Quick Match or a tournament) with <b>Dataset: Record my play</b>. It is saved at the final whistle, or when you quit after 10 s of play.</p></div>`;
  const b = d.behaviour, ref = d.reference || {}, net = ref.net || {}, rules = ref.rules || {}, rec = d.record;
  const mins = (k) => d.minutes_by[k] || 0;
  const kpis = `<div class="kpis">${kpi("Matches", `${d.files}`, `${rec.W}W ${rec.D}D ${rec.L}L${rec.left ? ` · ${rec.left} left early` : ""}`)}${kpi("Play recorded", `${f(d.minutes, 1)}<small>min</small>`, `${d.rows.toLocaleString()} decisions`)}${kpi("Goals", `${d.goals[0]}<small>–</small>${d.goals[1]}`, "for – against, finished matches")}${kpi("Direction changes", `${f(b.dir_changes_s, 1)}<small>/ s</small>`, `net ${f(net.dir_changes_s, 1)} · rules ${f(rules.dir_changes_s, 1)}`)}${kpi("Kick presses", `${f(b.kick_presses_s * 60, 1)}<small>/ min</small>`, `kick held ${f(b.kick_held_pct, 1)}% of the time`)}${kpi("One player / whole team", `${f(mins("control:single"), 1)}<small>min</small> · ${f(mins("control:team"), 1)}<small>min</small>`, "minutes of each control mode")}</div>`;
  const behaviour = `<section class="card"><div class="card-h"><h2>How you move</h2><span class="muted small">your player's frame · → = towards the opponent goal</span></div>
    <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap"><div>${compass(d.moves, css("--c3"))}</div><div style="flex:1;min-width:220px">
      <dl class="kv"><dt>180° turns / s</dt><dd>${f(b.turn180_s, 2)}</dd><dt>Kick held</dt><dd>${f(b.kick_held_pct, 1)}%</dd><dt>Moving towards the ball</dt><dd>${f(b.toward_ball_pct, 0)}% of moving decisions</dd><dt>Nearest team to the ball</dt><dd>yours ${f(d.phase.ours_pct, 0)}% of the time</dd><dt>Ball in your half</dt><dd>${f(d.phase.ball_own_half_pct, 0)}%</dd></dl></div></div>
      <div style="margin-top:12px">${vsBar("Direction changes / s", b.dir_changes_s, net.dir_changes_s, rules.dir_changes_s, 1)}${vsBar("Standing still %", b.idle_pct, net.idle_pct, rules.idle_pct, 0)}
      <p class="muted small">Ticks: <i class="lgd" style="background:var(--c2)"></i>net ${esc(ref.run || "–")}${ref.update != null ? " u" + ref.update : ""} · <i class="lgd" style="background:var(--ink)"></i>the rule bots it played (newest full evaluation, same definitions).</p></div></section>`;
  const where = `<section class="card"><div class="card-h"><h2>Where</h2><span class="muted small">share of time · you always attack right</span></div><div class="heats">${heatmap({ ...d.heat.player, role: "-" }, "Your player")}${heatmap({ ...d.heat.ball, role: "-" }, "The ball")}${heatmap({ ...d.heat.kicks, role: "-" }, `Your kicks (${d.heat.kicks.n})`)}</div><div class="hlegend"><span>rare</span><i></i><span>often</span></div></section>`;
  const secs = (n) => (n >= 1800 ? f(n / 1800, 1) + " min" : Math.round(n / 30) + " s");
  const distRows = d.distance.map((x) => `<div class="bh"><div class="bl">${esc(x.label)}</div><div class="bt"><i style="width:${x.pct}%;background:var(--c1)"></i></div><div class="bv">${f(x.pct, 0)}%</div></div>`).join("");
  const rankRows = d.ranks.map((r) => `<tr class="${r.rows < 1800 ? "thin" : ""}"><td>${esc(r.label)}</td><td class="r">${f(r.pct, 0)}%</td><td class="r">${secs(r.ours_rows)}</td><td class="r">${secs(r.theirs_rows)}</td><td class="r">${r.rows ? f(r.toward_pct, 0) + "%" : "–"}</td><td class="r">${r.rows ? f(r.idle_pct, 0) + "%" : "–"}</td><td class="r">${r.rows ? f(r.dist_px, 0) : "–"}</td></tr>`).join("");
  const coverage = `<section class="card flush"><div class="card-h pad"><h2>Coverage: which situations you have played</h2><span class="muted small">no fixed roles: the net must learn the role from the situation, so it needs examples of each</span></div>
    <div class="pad" style="padding:4px 16px 0">${distRows}</div>
    <div class="tbl-wrap"><table class="mini"><thead><tr><th>Your depth among your 5 (keeper counts)</th><th class="r">time</th><th class="r" title="time with your team nearest the ball">yours</th><th class="r" title="time with theirs nearest the ball">theirs</th><th class="r">to ball</th><th class="r">still</th><th class="r">dist px</th></tr></thead><tbody>${rankRows}</tbody></table></div>
    ${d.thin.length ? `<p class="small pad" style="padding:8px 16px 14px"><b>Under a minute of examples:</b> ${d.thin.map(esc).join(" · ")}. Play these (e.g. one player as a defender or the keeper) so the models see them.</p>` : `<p class="muted small pad" style="padding:8px 16px 14px">Every situation has at least a minute of examples.</p>`}</section>`;
  const sit = d.situations.map((s) => `<tr><td>${esc(s.label)}</td><td class="r">${secs(s.rows)}</td><td>${s.rows ? compass(s.moves, css("--c3"), 64, false) : '<span class="muted">none</span>'}</td><td class="r">${s.rows ? f(s.toward_pct, 0) + "%" : "–"}</td><td class="r">${s.rows ? f(s.idle_pct, 0) + "%" : "–"}</td></tr>`).join("");
  const situations = `<section class="card flush"><div class="card-h pad"><h2>What you do, by situation</h2><span class="muted small">"possession" = your team has the player nearest the ball</span></div><div class="tbl-wrap"><table class="mini"><thead><tr><th>Situation</th><th class="r">time</th><th>moves (→ goal)</th><th class="r">towards ball</th><th class="r">standing</th></tr></thead><tbody>${sit}</tbody></table></div></section>`;
  const oc = { W: "pos", L: "neg", D: "", left: "muted" };
  // puzzle rounds (game: Puzzle) are grouped by session: one row per session, its rounds in a fold-out
  const groups = [];
  for (const m of d.matches) {
    const g = m.puzzle && m.session ? groups.find((x) => x.session === m.session) : null;
    if (g) g.rounds.push(m); else groups.push(m.puzzle && m.session ? { session: m.session, rounds: [m], started: m.started } : m);
  }
  const roundLine = (m) => `<a href="#/dataset/${encodeURIComponent(m.id)}">${m.round || "?"}: ${esc(m.team.name)} ${m.gf}–${m.ga} ${esc(m.opponent.name)}</a>`;
  const sessionRow = (g) => { const R = g.rounds, cnt = (o) => R.filter((r) => r.outcome === o).length, mins = R.reduce((s, r) => s + r.minutes, 0), pts = 3 * cnt("W") + cnt("D");
    return `<tr><td class="nowrap">${esc(new Date(g.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))}</td><td><b>Puzzle</b> <span class="muted">${R.length} rounds, random teams</span>
      <details><summary class="small muted">rounds</summary><div class="small" style="display:grid;gap:2px">${R.map(roundLine).join("")}</div></details></td>
      <td class="r"><b>${pts} pts</b> <span class="small">${cnt("W")}W ${cnt("D")}D ${cnt("L")}L</span></td><td>${esc(R[0].control)} <span class="muted small">${esc([...new Set(R.flatMap((r) => Object.keys(r.roles)))].join(" "))}</span></td>
      <td class="r">${f(mins, 1)}</td><td class="r">${f(R.reduce((s, r) => s + r.dir_changes_s * r.minutes, 0) / mins, 1)}</td><td class="r">${f(R.reduce((s, r) => s + r.kick_presses_min * r.minutes, 0) / mins, 1)}</td>
      <td class="r">${f(R.reduce((s, r) => s + r.on_ball_pct * r.minutes, 0) / mins, 0)}%</td><td></td></tr>`; };
  const rows = groups.slice().reverse().map((m) => m.rounds ? sessionRow(m) : m.error ? `<tr><td colspan="9" class="neg">${esc(m.id)}: ${esc(m.error)}</td></tr>` :
    `<tr><td class="nowrap">${esc(new Date(m.started).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))}</td><td>${esc(m.team.name)} <span class="muted">vs</span> ${esc(m.opponent.name)} <span class="muted small">${esc(m.opponent.league)}</span></td>
     <td class="r"><b class="${oc[m.outcome]}">${m.gf}–${m.ga}${m.shootout?.length ? ` (p ${m.shootout.join("–")})` : ""}</b> <span class="small ${oc[m.outcome]}">${m.outcome === "left" ? "left early" : m.outcome}</span></td>
     <td>${esc(m.control)}${m.picked ? ` · ${esc(m.picked)}` : ""} <span class="muted small">${esc(Object.keys(m.roles).join(" "))}</span></td><td class="r">${f(m.minutes, 1)}</td><td class="r">${f(m.dir_changes_s, 1)}</td><td class="r">${f(m.kick_presses_min, 1)}</td><td class="r">${f(m.on_ball_pct, 0)}%</td><td><a href="#/dataset/${encodeURIComponent(m.id)}">replay ▶</a></td></tr>`).join("");
  const table = `<section class="card flush"><div class="card-h pad"><h2>Recorded matches</h2><span class="muted small">newest first</span></div><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Match</th><th class="r">Score</th><th>Control · roles played</th><th class="r">min</th><th class="r">changes/s</th><th class="r">kicks/min</th><th class="r">on ball</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  return head + kpis + `<div class="grid g2">${behaviour}${where}</div>` + `<div class="grid g2">${coverage}${situations}</div>` + table;
}

// ---------- replay of one recorded match (drawn from the stored states; the arrow is your key direction) ----------
function viewReplay(id) {
  return `<div class="head"><div><h1><a class="rl" href="#/dataset">Dataset</a> · replay</h1><p class="mono small">${esc(id)}</p></div></div>
    <section class="card"><canvas id="rp-cv" style="width:100%;display:block;border-radius:8px;background:var(--panel-2)"></canvas>
    <div class="rp-ctl" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px">
      <button class="pill" id="rp-play">⏸ pause</button><span class="pills" style="margin:0">${[0.5, 1, 2, 4].map((s) => `<button class="pill${s === 1 ? " on" : ""}" data-rpspeed="${s}">${s}×</button>`).join("")}</span>
      <input type="range" id="rp-seek" min="0" max="0" value="0" style="flex:1;min-width:200px"><span id="rp-info" class="mono small"></span></div>
    <p class="muted small" style="margin-top:6px">Ringed: the player you controlled. Arrow: the direction you held at that decision (none = standing); the ring turns red while you hold kick. Space = play / pause, ← → = 1 s.</p></section>`;
}
function startReplay(id) {
  stopReplay();
  const R = ds.replay = { id, d: null, i: 0, playing: true, speed: 1, last: 0, raf: 0 };
  getJSON("/api/dataset/match/" + encodeURIComponent(id)).then((d) => {
    if (ds.replay !== R) return;
    R.d = d; const seek = $("#rp-seek"); if (seek) seek.max = d.tick.length - 1;
    R.raf = requestAnimationFrame((t) => replayFrame(R, t));
  }).catch(() => { const i = $("#rp-info"); if (i) i.textContent = "this match could not be loaded"; });
}
function stopReplay() { if (ds.replay) cancelAnimationFrame(ds.replay.raf); ds.replay = null; }
function replayFrame(R, ts) {
  if (ds.replay !== R) return;
  R.raf = requestAnimationFrame((t) => replayFrame(R, t));
  const d = R.d, n = d.tick.length, dt = R.last ? Math.min(0.1, (ts - R.last) / 1000) : 0;
  R.last = ts;
  if (R.playing) { R.i += dt * 30 * R.speed; if (R.i >= n - 1) { R.i = n - 1; R.playing = false; } }
  const i = Math.max(0, Math.min(n - 1, Math.floor(R.i)));
  const cv = $("#rp-cv"); if (!cv) return;
  const pd = d.meta.pitch, W = cv.clientWidth, H = Math.round(W * (pd.out_y / pd.out_x));
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.height = H + "px"; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const s = W / (2 * pd.out_x), X = (x) => W / 2 + x * s, Y = (y) => H / 2 + y * s;
  ctx.fillStyle = "#5f7d4c"; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#6f8f5a"; ctx.fillRect(X(-pd.half_w), Y(-pd.half_h), 2 * pd.half_w * s, 2 * pd.half_h * s);
  ctx.strokeStyle = "rgba(230,245,225,.8)"; ctx.lineWidth = 2;
  ctx.strokeRect(X(-pd.half_w), Y(-pd.half_h), 2 * pd.half_w * s, 2 * pd.half_h * s);
  ctx.beginPath(); ctx.moveTo(X(0), Y(-pd.half_h)); ctx.lineTo(X(0), Y(pd.half_h)); ctx.stroke();
  ctx.beginPath(); ctx.arc(X(0), Y(0), 80 * s, 0, 2 * Math.PI); ctx.stroke();
  ctx.lineWidth = 4; ctx.strokeStyle = "#fff";
  for (const gx of [-pd.half_w, pd.half_w]) { ctx.beginPath(); ctx.moveTo(X(gx), Y(-pd.goal_half)); ctx.lineTo(X(gx), Y(pd.goal_half)); ctx.stroke(); }
  const P = d.p[i], ctrl = d.ctrl[i];
  d.meta.players.forEach((pl, k) => {
    const x = X(P[2 * k]), y = Y(P[2 * k + 1]), me = pl.uid === ctrl;
    disc(ctx, x, y, 15 * s, d.colors[pl.team], "rgba(0,0,0,.6)", 1.5);
    if (me) { ctx.beginPath(); ctx.arc(x, y, 15 * s + 5, 0, 2 * Math.PI); ctx.lineWidth = 3; ctx.strokeStyle = d.kick[i] ? "#ef6a5b" : "#fff"; ctx.stroke(); }
    if (me && d.move[i] > 0) {
      const [vx, vy] = MOVE_VEC[d.move[i]], ax = vx * d.attack, L = 34 + 15 * s;
      const ex = x + ax * L, ey = y + vy * L, a = Math.atan2(vy, ax);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x + ax * (15 * s + 6), y + vy * (15 * s + 6)); ctx.lineTo(ex, ey); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.moveTo(ex + Math.cos(a) * 8, ey + Math.sin(a) * 8); ctx.lineTo(ex + Math.cos(a + 2.5) * 9, ey + Math.sin(a + 2.5) * 9); ctx.lineTo(ex + Math.cos(a - 2.5) * 9, ey + Math.sin(a - 2.5) * 9); ctx.fill();
    }
  });
  disc(ctx, X(d.b[i][0]), Y(d.b[i][1]), 10 * s, "#fff", "#000", 1.5);
  const sc = d.score[i], tl = d.time_left[i], tm = d.meta.teams;
  ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(0, 0, W, 28);
  ctx.fillStyle = "#fff"; ctx.font = "600 14px system-ui, sans-serif"; ctx.textAlign = "center";
  ctx.fillText(`${tm[0].name}  ${sc[0]} – ${sc[1]}  ${tm[1].name}     ${clockText(tl)}`, W / 2, 19);
  const seek = $("#rp-seek"); if (seek && document.activeElement !== seek) seek.value = i;
  const info = $("#rp-info"); if (info) info.textContent = `${i + 1} / ${n} · ${MOVE_NAMES[d.move[i]]}${d.kick[i] ? " + kick" : ""}`;
  const pb = $("#rp-play"); if (pb) pb.textContent = R.playing ? "⏸ pause" : "▶ play";
}
