// The Game (web/game.js has the overview): the match report.
import { $, G, esc, go, mount, playerLink, shell, table } from "./core.js";
import { match } from "./match.js";
import { text } from "./render.js";

// ---------- match report ----------
export function showReport(result, cont) { G.report = { result, cont }; G.pending = null; go("#/game/report"); }
export function report(res, cont) {
  const T = res.teams.map((id) => G.byId[id] || { id, name: id, colors: ["888888", "ffffff"], logo: {} });
  let note = "Full time";
  if (res.overtime) note = "Full time · golden goal in overtime";
  else if (res.winner === -1) note = "Full time · draw";
  const scorers = (t) => res.events.filter((e) => e.team === t).map((e) =>
    `<div>${Math.floor(e.clock / 60) + 1}' ${esc(e.scorer_name)}${e.own ? " (OG)" : ""}${e.assist_name ? ` <span>· ${esc(e.assist_name)}</span>` : ""}</div>`).join("") || '<div class="none">no goals</div>';
  const ts = res.team_stats;
  const stat = (label, a, b, x, y) => {                           // a bar per stat: each side's share in its colour
    const sum = Math.max(1e-9, x + y), pa = x + y > 0 ? (100 * x) / sum : 50;
    return `<div class="rp-stat"><b class="${x > y ? "lead" : ""}">${a}</b><span>${label}</span><b class="${y > x ? "lead" : ""}">${b}</b>
      <div class="rp-bar"><i style="width:${pa}%"></i><i style="width:${100 - pa}%"></i></div></div>`;
  };
  const stats = [["Possession", ts[0].possession.toFixed(0) + "%", ts[1].possession.toFixed(0) + "%", ts[0].possession, ts[1].possession],
    ["Shots", ts[0].shots, ts[1].shots, ts[0].shots, ts[1].shots], ["On target", ts[0].shots_on_target, ts[1].shots_on_target, ts[0].shots_on_target, ts[1].shots_on_target],
    ["Expected goals (xG)", ts[0].xg.toFixed(1), ts[1].xg.toFixed(1), ts[0].xg, ts[1].xg],
    ["Passes completed", `${ts[0].passes_ok} / ${ts[0].passes}`, `${ts[1].passes_ok} / ${ts[1].passes}`, ts[0].passes_ok, ts[1].passes_ok],
    ["Tackles and interceptions", ts[0].recoveries, ts[1].recoveries, ts[0].recoveries, ts[1].recoveries],
    ["Dribbles won", ts[0].dribbles, ts[1].dribbles, ts[0].dribbles, ts[1].dribbles], ["Shots blocked", ts[0].blocks, ts[1].blocks, ts[0].blocks, ts[1].blocks]]
    .map((r) => stat(...r)).join("");
  const cols = [{ t: "#", w: 40 }, { t: "Player" }, { t: "G", w: 40, a: "r" }, { t: "A", w: 40, a: "r" }, { t: "Shots", w: 64, a: "r" },
    { t: "Passes", w: 72, a: "r" }, { t: "Key", w: 46, a: "r" }, { t: "Tkl", w: 46, a: "r" }, { t: "Int", w: 46, a: "r" }, { t: "Drb", w: 46, a: "r" }, { t: "Blk", w: 46, a: "r" }];
  const ptable = (team) => table(cols, res.players.filter((p) => p.team === team).map((p) => ({
    cells: [{ text: p.slot + 1, color: "var(--g-muted)" }, playerLink(p.id, p.name), p.goals, p.assists, `${p.shots_on_target}/${p.shots}`, `${p.passes_ok}/${p.passes_ok + p.passes_failed}`,
      p.key_passes, p.tackles, p.interceptions, p.dribbles, p.blocks] })));
  const v = mount(shell(`<section class="rp-head" style="--c0:#${T[0].colors[0]};--c1:#${T[1].colors[0]}">
      <div class="rp-team"><span class="rp-crest"></span><div class="rp-name">${esc(T[0].name)}</div><div class="rp-goals">${scorers(0)}</div></div>
      <div class="rp-mid"><div class="rp-score">${res.scores[0]} – ${res.scores[1]}</div><div class="rp-note">${esc(note)}</div><button type="button" class="ks-go" id="r-go">Continue</button></div>
      <div class="rp-team"><span class="rp-crest"></span><div class="rp-name">${esc(T[1].name)}</div><div class="rp-goals">${scorers(1)}</div></div></section>
    <div class="rp-grid"><section class="gp-card rp-stats" style="--c0:#${T[0].colors[0]};--c1:#${T[1].colors[0]}"><h2>Match stats</h2>${stats}</section></div>
    ${[0, 1].map((t) => `<section class="gp-card"><h2 class="rp-th"><span class="rp-tcrest" data-t="${t}"></span>${esc(T[t].name)} · players</h2>${ptable(t)}</section>`).join("")}`,
    [["Enter", "continue"]], "rp"));
  v.querySelectorAll(".rp-crest").forEach((el, t) => el.append(Draw.logoCanvas(T[t].logo, 88)));
  v.querySelectorAll(".rp-tcrest").forEach((el) => el.append(Draw.logoCanvas(T[Number(el.dataset.t)].logo, 24)));
  $(".ks-links a", v).remove();                                      // the report always continues (a tournament result is already saved)
  const cont2 = () => { G.report = null; go(cont); };
  $("#r-go", v).onclick = cont2;
  window.scrollTo(0, 0);
  G.keyHandler = (e, down) => { if (down && !e.repeat && e.key === "Enter") { e.preventDefault(); cont2(); } };
}
