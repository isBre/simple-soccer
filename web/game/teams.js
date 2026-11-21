// The Game (web/game.js has the overview): teams & squads.
import { $, G, RAT, card, eloText, esc, go, leagueTeams, mount, playsText, prefs, savePrefs, shell, table, whoDrives } from "./core.js";
import { match, play } from "./match.js";
import { menu } from "./menu.js";
import { closeLists, listPick } from "./quick.js";
import { text } from "./render.js";

// ---------- teams & squads: one league at a time (strongest first), the picked team in its colours with its squad ----------
export function teams(id) {
  const L = G.cat.leagues;
  let team = G.byId[id] || G.cat.teams[0];
  let li = Math.max(0, L.findIndex((l) => l.id === team.league));
  const list = () => leagueTeams(L[li].id);
  const v = mount(shell(`<div class="gt"><div class="gt-side"><div class="gt-lgpick" id="t-lg"></div><nav class="gt-list" id="t-list" aria-label="Teams"></nav></div><div class="gt-detail" id="t-detail"></div></div>`,
    [["↑ ↓", "team"], ["← →", "league"], ["Enter", "quick match with it"], ["Esc", "menu"]]));
  const lg = listPick(L.map((l) => ({ label: l.name, count: l.count })), li, (k) => { li = k; fillList(); showTeam(list()[0]); });
  $("#t-lg", v).append(lg.el);
  function fillList() {
    const nav = $("#t-list", v);
    nav.innerHTML = list().map((t, i) => `<button type="button" class="gt-row" data-team="${esc(t.id)}" style="--kc:#${t.colors[0]}"><span class="k">${i + 1}</span>${Draw.logoTag(t.id, 26)}<span class="n">${esc(t.name)}</span><span class="e">${t.elo ?? "–"}</span></button>`).join("");
    Draw.fillLogos(nav, G.byId);
    for (const b of nav.querySelectorAll("[data-team]")) {
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("click", () => showTeam(G.byId[b.dataset.team]));
    }
  }
  const league = (d) => { li = (li + d + L.length) % L.length; lg.set(li); fillList(); showTeam(list()[0]); };
  const playWith = (t) => { prefs.sides = [t.id, (prefs.sides || [])[1] && prefs.sides[1] !== t.id ? prefs.sides[1] : G.cat.teams.find((x) => x.id !== t.id).id]; savePrefs(); go("#/game/quick"); };
  function showTeam(t) {
    if (!t) return;
    team = t;
    history.replaceState(null, "", "#/game/teams/" + encodeURIComponent(t.id));
    for (const b of v.querySelectorAll("[data-team]")) b.classList.toggle("on", b.dataset.team === t.id);
    v.querySelector(`[data-team="${CSS.escape(t.id)}"]`)?.scrollIntoView({ block: "nearest" });
    const order = { GK: 0, DEF: 1, MID: 2, FWD: 3 };
    const squad = t.players.slice().sort((a, b) => (order[a.pos] ?? 9) - (order[b.pos] ?? 9) || b.overall - a.overall);
    const cols = [{ t: "#", w: 44 }, { t: "Player" }, { t: "Pos", w: 60 }, { t: "OVR", w: 60, a: "r" }, { t: "Fin", w: 54, a: "r" }, { t: "Pas", w: 54, a: "r" },
      { t: "Def", w: 54, a: "r" }, { t: "Mov", w: 54, a: "r" }, { t: "Rea", w: 54, a: "r" }];
    const prow = squad.map((p) => ({ cells: [{ text: p.number, color: "var(--g-muted)" }, esc(p.name), { text: p.pos, color: "var(--g-muted)" },
      { text: p.overall, color: RAT(p.overall / 10), bold: true }, ...[p.finishing, p.passing, p.defending, p.positioning, p.reaction].map((x) => ({ text: x, color: RAT(x / 10) }))] }));
    const d = $("#t-detail", v);
    d.innerHTML = `<section class="gp-hero row" style="--kc:#${t.colors[0]}"><div class="ks-mark" aria-hidden="true"></div><span class="gt-crest"></span>
        <div class="gt-info"><div class="gp-pill">${esc(t.league_name)}</div><h1 class="gt-name">${esc(t.name)}</h1><div class="ks-elo">${esc(eloText(t))}</div>
        <p class="gt-plays">${esc(playsText(t))}</p><div class="gt-who">${esc(whoDrives(t))}</div></div>
        <button type="button" class="ks-go gt-play" id="t-play">Quick match</button></section>
      <section class="gp-card"><h2>Squad</h2>${table(cols, prow)}
        <div class="g-caption">Fin finishing, Pas passing, Def defending, Mov positioning, Rea reaction. Attributes change AI decisions, never the physics.</div></section>`;
    $(".ks-mark", d).append(Draw.logoCanvas(t.logo, 560));
    $(".gt-crest", d).append(Draw.logoCanvas(t.logo, 150));
    $("#t-play", d).onclick = () => playWith(t);
  }
  const stepTeam = (d) => { const l = list(), k = l.indexOf(team); showTeam(l[(k + d + l.length) % l.length]); };
  fillList(); showTeam(team);
  G.keyHandler = (e, down) => {
    if (!down) return;
    if (e.key === "Escape" && !e.repeat) go("#/game");
    else if (e.key === "Enter" && !e.repeat) { e.preventDefault(); playWith(team); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); stepTeam(e.key === "ArrowUp" ? -1 : 1); }
    else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !e.repeat) { e.preventDefault(); closeLists(); league(e.key === "ArrowLeft" ? -1 : 1); }
  };
}
