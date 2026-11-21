// The Game (web/game.js has the overview): new tournament and the tournament hub.
import { $, CHEV, CONTROLS, G, api, btn, card, eloText, esc, go, header, leagueTeams, loadT, mount, overlay, pitchOf, playsText, prefs, savePrefs, saveT, shell, table, teamCell, view } from "./core.js";
import { match, play } from "./match.js";
import { menu } from "./menu.js";
import { SIZES, drawReel, listPick, playControls, prefIdx, seg, youPill } from "./quick.js";
import { text } from "./render.js";
import { showReport } from "./report.js";
import { teams } from "./teams.js";

// ---------- new tournament: your team on the left (in its colours), the settings on the right ----------
export const FORMATS = ["League", "Knockout", "Groups + knockout"];
export function tourNew() {
  const C = G.cat, P = C.pitches, L = C.leagues;
  const pow2 = (n) => n >= 4 && (n & (n - 1)) === 0;
  const pools = L.map((l) => ({ label: l.name, id: l.id, teams: leagueTeams(l.id) })).concat([{ label: "All leagues", id: "all", teams: C.teams }]);
  let li = 0, fmt = 2, counts = [];
  const firstUser = G.byId[(prefs.sides || [])[0]];
  if (firstUser) li = Math.max(0, L.findIndex((l) => l.id === firstUser.league));
  let team = pools[li].teams.includes(firstUser) ? firstUser : pools[li].teams[0];
  let pi = Math.max(0, P.findIndex((p) => p.id === (prefs.pitch || "arena")));
  const v = mount(shell(`<div class="gn">
      <section class="gp-hero" id="n-hero"><div class="ks-mark" aria-hidden="true"></div><div class="ks-role"><span class="ks-who you">You</span><span>Your team</span></div>
        <div class="ks-pick"><button type="button" class="ks-chev" data-d="-1" aria-label="Previous team" tabindex="-1">${CHEV(-1)}</button><span class="ks-reel"></span><button type="button" class="ks-chev" data-d="1" aria-label="Next team" tabindex="-1">${CHEV(1)}</button></div>
        <div class="ks-name"></div><div class="ks-elo"></div><p class="ks-plays"></p></section>
      <section class="gp-card gn-form"><h2>New tournament</h2><div class="gn-fields" id="n-form"></div>
        <div class="gn-foot"><span class="g-caption" id="n-sum"></span><button type="button" class="ks-go" id="n-go">Start tournament</button></div></section></div>`,
    [["← →", "your team"], ["R", "random team"], ["Enter", "start"], ["Esc", "menu"]]));
  const hero = $("#n-hero", v), form = $("#n-form", v);
  const lg = listPick(pools.map((p) => ({ label: p.label, count: p.teams.length })), li, (k) => { li = k; team = pools[li].teams[0]; onPool(); });
  const fmtSeg = seg("Format", FORMATS, fmt, (i) => { fmt = i; summary(); });
  let countSeg = null;
  const countWrap = document.createElement("div");
  const pitchSeg = seg("Pitch", P.map((p) => p.name), pi, (i) => { pi = i; prefs.pitch = P[i].id; savePrefs(); sizeSeg.set(Math.max(1, Math.min(5, P[i].recommended)) - 1); summary(); });
  const sizeSeg = seg("Players", SIZES.map((n) => `${n}v${n}`), prefIdx("size", Math.max(1, Math.min(5, P[pi].recommended)) - 1, 5), () => summary());
  const minSeg = seg("Minutes", ["1", "2", "3"], Math.min(2, prefIdx("minutes", 2, 3)), () => summary());
  const row = (label, el) => { const r = document.createElement("div"); r.className = "gn-row"; r.innerHTML = `<span class="gn-l">${esc(label)}</span>`; r.append(el); return r; };
  form.append(row("League", lg.el), fmtSeg.el, countWrap, pitchSeg.el, sizeSeg.el, minSeg.el);
  const count = () => counts[countSeg.get()];
  function syncFormat() {
    const ok = pow2(count());
    if (!ok) { fmt = 0; fmtSeg.set(0); }
    fmtSeg.disable(ok ? new Set() : new Set([1, 2]));
    summary();
  }
  function summary() {
    $("#n-sum", v).textContent = `${count()} teams · ${FORMATS[fmt].toLowerCase()} · ${P[pi].name.replace(/ \(.*\)$/, "")} · ${SIZES[sizeSeg.get()]}v${SIZES[sizeSeg.get()]} · ${minSeg.get() + 1} min`;
  }
  function onPool() {
    const n = pools[li].teams.length;
    counts = [4, 8, 16].filter((c) => c < n).concat([n]);
    const def = Math.max(0, counts.indexOf(8)) || counts.length - 1;
    countSeg = seg("Teams", counts.map((c, i) => (i === counts.length - 1 ? `All ${c}` : String(c))), counts.includes(8) ? counts.indexOf(8) : def, () => syncFormat());
    countWrap.replaceChildren(countSeg.el);
    paint(0); syncFormat();
  }
  function paint(d) {
    const list = pools[li].teams;
    hero.style.setProperty("--kc", "#" + team.colors[0]);
    drawReel($(".ks-reel", hero), list, team, d, (off) => step(off));
    $(".ks-mark", hero).replaceChildren(Draw.logoCanvas(team.logo, 620));
    $(".ks-name", hero).textContent = team.name;
    $(".ks-elo", hero).textContent = eloText(team);
    $(".ks-plays", hero).textContent = playsText(team);
  }
  function step(d) { const list = pools[li].teams, k = list.indexOf(team); team = list[(k + d + list.length) % list.length]; paint(d); }
  function randomTeam() {                                           // R: a random team of the chosen league (or of every league)
    const list = pools[li].teams.filter((x) => x !== team);
    if (list.length) { team = list[Math.floor(Math.random() * list.length)]; paint(1); }
  }
  for (const b of hero.querySelectorAll(".ks-chev")) b.addEventListener("click", () => step(Number(b.dataset.d)));
  async function start() {
    if (G.busy) return;
    G.busy = true;
    try {
      const d = await api("/api/game/tournament", { action: "new", league: pools[li].id, user: team.id, count: count(), format: fmt, pitch: P[pi].id,
        size: SIZES[sizeSeg.get()], duration: (minSeg.get() + 1) * 60 });
      saveT(d.t); G.tab = 0; go("#/game/tournament");
    } catch (e) { alert("The tournament could not be created: " + e.message); }
    finally { G.busy = false; }
  }
  onPool();
  $("#n-go", v).onclick = start;
  G.keyHandler = (e, down) => {
    if (!down) return;
    const inForm = document.activeElement?.closest?.(".gn-form");
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !inForm) { e.preventDefault(); step(e.key === "ArrowLeft" ? -1 : 1); }
    else if (e.repeat) return;
    else if (e.key === "Escape") go("#/game");
    else if (e.key === "r" || e.key === "R") randomTeam();
    else if (e.key === "Enter" && !(inForm && document.activeElement.tagName === "BUTTON")) { e.preventDefault(); start(); }
  };
}

// ---------- tournament hub: header in your team's colours, tabs (match day, table, results, players) ----------
export async function tourHub() {
  const t0 = loadT();
  if (!t0) { history.replaceState(null, "", "#/game"); return menu(); }
  let d;
  try { d = await api("/api/game/tournament", { action: "view", t: t0 }); }
  catch (e) { mount(shell(`<p class="g-error">${esc(e.message)}</p>`)); return; }
  renderHub(d.t, d.view);
  const vw = d.view;
  if (!vw.finished && vw.user_fixture === null && !vw.eliminated && vw.pending > 0) simulateRound(d.t);   // the rest of the round after the player's match
}
export const TABS = ["Match day", "Table", "Results", "Players"];
export function renderHub(t, vw) {
  const ut = G.byId[t.user_team] || { id: t.user_team, name: t.user_team, colors: ["888888", "ffffff"], logo: {} }, pitch = pitchOf(t.pitch_id);
  const v = mount(shell(`<section class="gp-hero row gh-head" style="--kc:#${ut.colors[0]}"><div class="ks-mark" aria-hidden="true"></div><span class="gh-crest"></span>
      <div class="gt-info"><h1 class="gh-title">${esc(t.title)}</h1><div class="gh-sub">${youPill}${esc(ut.name)} · ${esc(pitch.name.replace(/ \(.*\)$/, ""))} · ${t.team_size}v${t.team_size} · ${Math.round(t.duration / 60)} min matches</div></div></section>
    <nav class="gp-tabs" role="tablist">${TABS.map((x, i) => `<button type="button" role="tab" data-tab="${i}" class="${i === G.tab ? "on" : ""}" aria-selected="${i === G.tab}">${x}</button>`).join("")}</nav>
    <div id="h-body" class="gh-body"></div>`, [["← →", "tab"], ["Esc", "menu (saved)"]]));
  $(".ks-mark", v).append(Draw.logoCanvas(ut.logo, 420));
  $(".gh-crest", v).append(Draw.logoCanvas(ut.logo, 72));
  const tab = (i) => { G.tab = (i + TABS.length) % TABS.length; renderHub(t, vw); };
  for (const b of v.querySelectorAll("[data-tab]")) { b.addEventListener("mousedown", (e) => e.preventDefault()); b.onclick = () => tab(Number(b.dataset.tab)); }
  const body = $("#h-body", v);
  body.innerHTML = G.tab === 1 ? tablesTab(t, vw) : G.tab === 2 ? resultsTab(t) : G.tab === 3 ? playersTab(t, vw) : matchDayTab(t, vw);
  Draw.fillLogos(body, G.byId);
  if (G.tab === 0) {
    const opts = $("#h-opts", v);
    if (opts && vw.user_fixture !== null) { const pc = playControls(); opts.append(...pc.els); pc.sync(); }
    $("#h-play", v)?.addEventListener("click", () => playUser(t));
    $("#h-sim", v)?.addEventListener("click", () => simulateRound(t));
    $("#h-done", v)?.addEventListener("click", () => go("#/game"));
    const champ = $(".gh-champ-crest", v);
    if (champ) champ.append(Draw.logoCanvas((G.byId[t.champion] || {}).logo, 150));
  }
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    if (e.key === "Escape") go("#/game");
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); tab(G.tab + (e.key === "ArrowLeft" ? -1 : 1)); }
  };
}
export const nameOf = (id) => esc(G.byId[id]?.name || id);
export function fixtureRow(t, f, detail) {
  const you = (id) => (id === t.user_team ? youPill : "");
  const score = f.played ? `${f.hg} – ${f.ag}${f.pens && f.pens.length ? `<small>pens ${f.pens[0]}–${f.pens[1]}</small>` : ""}` : '<span class="vs">vs</span>';
  let out = `<div class="gf${f.home === t.user_team || f.away === t.user_team ? " mine" : ""}"><span class="h">${you(f.home)}${nameOf(f.home)}</span>${Draw.logoTag(f.home, 30)}
    <span class="sc">${score}</span>${Draw.logoTag(f.away, 30)}<span class="a">${nameOf(f.away)}${you(f.away)}</span></div>`;
  if (detail && f.played) {
    let txt = f.goals.map((g) => `${Math.floor(g.clock / 60) + 1}' ${g.scorer}${g.own ? " (OG)" : ""}`).join(", ");
    if (f.mom) txt += (txt ? "  ·  " : "") + "Player of the match: " + f.mom;
    if (txt) out += `<div class="gf-d">${esc(txt)}</div>`;
  }
  return out;
}
export function matchDayTab(t, vw) {
  if (vw.finished) {
    const c = G.byId[t.champion], won = t.champion === t.user_team;
    return `<section class="gp-hero gh-champ" style="--kc:#${c?.colors?.[0] || "888888"}"><div class="ks-role"><span>Champions</span></div><span class="gh-champ-crest"></span>
      <div class="ks-name">${esc(c?.name || t.champion)}</div><p class="ks-plays">${won ? "You won the tournament." : "Better luck next time."}</p>
      <button type="button" class="ks-go" id="h-done">Back to the menu</button></section>`;
  }
  const r = t.rounds[Math.min(t.round_index, t.rounds.length - 1)];
  const acts = vw.user_fixture !== null
    ? '<button type="button" class="ks-btn2" id="h-sim">Simulate round</button><button type="button" class="ks-go" id="h-play">Play my match</button>'
    : (vw.eliminated ? '<span class="g-bad">You are out of the tournament.</span>' : "") + '<button type="button" class="ks-go" id="h-sim">Simulate round</button>';
  return `<section class="gp-card"><h2>${esc(vw.round_name)}</h2><div class="gf-list">${r.fixtures.map((f) => fixtureRow(t, f, false)).join("")}</div></section>
    <div class="gh-acts"><div class="ks-opts" id="h-opts"></div>${acts}</div>`;
}
export function standingsTable(t, rows, qualify) {
  const cols = [{ t: "#", w: 40 }, { t: "Team" }, { t: "P", w: 48, a: "r" }, { t: "W", w: 48, a: "r" }, { t: "D", w: 48, a: "r" }, { t: "L", w: 48, a: "r" },
    { t: "GF", w: 52, a: "r" }, { t: "GA", w: 52, a: "r" }, { t: "GD", w: 56, a: "r" }, { t: "Pts", w: 60, a: "r" }];
  return table(cols, rows.map((r, i) => {
    const mine = r.id === t.user_team, gd = r.gd;
    return { hl: mine, zone: i < qualify, cells: [{ text: i + 1, color: "var(--g-muted)" }, teamCell(G.byId[r.id] || { id: r.id }, G.byId[r.id]?.name || r.id, "", 24, mine),
      r.p, r.w, r.d, r.l, r.gf, r.ga, { text: gd > 0 ? "+" + gd : gd, color: gd > 0 ? "var(--g-good)" : gd < 0 ? "var(--g-bad)" : "var(--g-muted)" },
      { text: r.pts, bold: true }] };
  }));
}
export function tablesTab(t, vw) {
  if (!vw.tables.length) return '<p class="gh-empty">A knockout cup has no table: the Results tab shows every round.</p>';
  let out = "";
  for (const tb of vw.tables) out += `<section class="gp-card">${tb.title ? `<h2>${esc(tb.title)}</h2>` : ""}${standingsTable(t, tb.rows, vw.tables.length > 1 ? tb.qualify : 0)}</section>`;
  if (vw.tables.length > 1) out += '<div class="g-caption">Green bar: goes through to the knockout stage.</div>';
  return out;
}
export function resultsTab(t) {
  let out = "";
  for (let i = t.rounds.length - 1; i >= 0; i--) {
    const r = t.rounds[i], played = r.fixtures.filter((f) => f.played);
    if (played.length) out += `<section class="gp-card"><h2>${esc(r.name)}</h2><div class="gf-list">${played.map((f) => fixtureRow(t, f, true)).join("")}</div></section>`;
  }
  return out || '<p class="gh-empty">No matches played yet.</p>';
}
export function playersTab(t, vw) {
  const lists = [["Top scorers", "goals", "Goals"], ["Top assists", "assists", "Assists"], ["Best average grade", "rating", "Grade"], ["Player of the match awards", "motm", "Awards"]];
  return `<div class="gh-grid">${lists.map(([title, kind, col]) => {
    const rows = vw.top[kind] || [];
    const body = rows.length ? table([{ t: "#", w: 36 }, { t: "Player" }, { t: col, w: 76, a: "r" }], rows.map((ps, i) => {
      const mine = ps.team === t.user_team;
      const val = kind === "rating" ? (ps.rating_sum / Math.max(1, ps.apps)).toFixed(2) : String(ps[kind]);
      return { hl: mine, cells: [{ text: i + 1, color: "var(--g-muted)" }, teamCell(G.byId[ps.team] || { id: ps.team }, ps.name, "", 22), { text: val, bold: true }] };
    })) : '<p class="gh-empty">No matches played yet.</p>';
    return `<section class="gp-card"><h2>${esc(title)}</h2>${body}</section>`;
  }).join("")}</div>`;
}
export async function simulateRound(t) {
  if (G.busy) return;
  G.busy = true;
  const o = overlay('<div>Simulating matches...</div><div class="bar2"><i></i></div>');
  try {
    const d = await api("/api/game/tournament", { action: "simulate", t });
    saveT(d.t); o.remove();
    if (document.body.dataset.area === "game" && location.hash.startsWith("#/game/tournament")) renderHub(d.t, d.view);
  } catch (e) {
    o.innerHTML = `<div>The matches could not be played:<br><span style="font-size:18px">${esc(e.message)}</span></div>${btn("Close", "", "primary")}`;
    $(".g-btn", o).onclick = () => o.remove();
  } finally { G.busy = false; }
}
export async function playUser(t) {
  if (G.busy) return;
  let fx;
  try { fx = await api("/api/game/tournament", { action: "fixture", t }); } catch (e) { alert(e.message); return; }
  const control = CONTROLS[prefIdx("control", 0, 3)];
  const setup = { ...fx.setup, control, record: control !== "none" && !!prefs.record };
  play({ setup, quit: () => go("#/game/tournament"), done: async (res) => {
    try { const d = await api("/api/game/tournament", { action: "record", t, index: fx.index, result: res }); saveT(d.t); }
    catch (e) { alert("The result could not be recorded: " + e.message); }
    showReport(res, "#/game/tournament");
  } });
}
