// The Game (web/game.js has the overview): the players. A player is a brain with a name (rule-based style + skill, Opus, or a
// trained net); teams are line-ups of players (data/players, data/teams; README "Players, teams and kickoff").
import { $, G, KIND_SHORT, eloSizes, esc, go, mount, shell, sizesText, table } from "./core.js";

const KINDS = [["", "All"], ["rules", "Rule-based"], ["net", "Nets"]];
const SIZE_F = [0, 1, 2, 3, 4, 5];
const PARAM_LABEL = { line_height: "Defensive line", press: "Pressing", marking: "Marking", directness: "Directness", pass_bias: "Passing", width: "Width" };
const state = { kind: "", size: 0, q: "" };

const styleOf = (id) => (G.cat.builder?.styles || []).find((s) => s.id === id);
const teamsOf = (p) => p.teams.map((id) => G.byId[id]).filter(Boolean);

// a small round badge with the player's initials, in a colour per kind (players have no crest)
const KIND_COL = { rules: "#4f8fd8", opus: "#d97757", net: "#5fb87a" };
export const badge = (p, px = 40) => `<span class="pl-badge" style="--bc:${KIND_COL[p.kind] || "#888"};width:${px}px;height:${px}px;font-size:${Math.round(px * 0.38)}px">${
  esc(p.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase())}</span>`;

// ---------- the list: every player, filtered by kind, team size and name ----------
export function playersList() {
  const v = mount(shell(`<section class="gp-hero row pl-head"><div class="gt-info"><div class="gp-pill">Players</div><h1 class="gt-name">Every player</h1>
      <p class="gt-plays">A player is a brain with a name: a rule-based style with a skill, or a trained net. Every player has the same body
      and sees the same public view of the match; teams are line-ups of five of them.</p></div><a class="ks-go gt-play pl-build" href="#/game/build">Build a team</a></section>
    <div class="pl-filters"><div class="pl-seg" id="pl-kind">${KINDS.map(([k, l]) => `<button type="button" data-k="${k}">${l}</button>`).join("")}</div>
      <div class="pl-seg" id="pl-size">${SIZE_F.map((n) => `<button type="button" data-n="${n}">${n ? n + "v" + n : "Any size"}</button>`).join("")}</div>
      <input id="pl-q" class="pl-q" type="search" placeholder="Search by name or style" aria-label="Search players" value="${esc(state.q)}"></div>
    <section class="gp-card" id="pl-table"></section>`, [["/", "search"], ["Esc", "menu"]]));
  const paint = () => {
    for (const b of v.querySelectorAll("#pl-kind button")) b.classList.toggle("on", b.dataset.k === state.kind);
    for (const b of v.querySelectorAll("#pl-size button")) b.classList.toggle("on", Number(b.dataset.n) === state.size);
    const q = state.q.trim().toLowerCase();
    const rows = G.cat.players.filter((p) => (!state.kind || p.kind === state.kind) && (!state.size || p.sizes.includes(state.size))
      && (!q || (p.name + " " + p.style_label + " " + p.kind_label).toLowerCase().includes(q)));
    const cols = [{ t: "", w: 46 }, { t: "Player" }, { t: "Type", w: 120 }, { t: "Style", w: 150 }, { t: "Skill", w: 60, a: "r" }, { t: "Sizes", w: 110, a: "r" }, { t: "Teams", w: 64, a: "r" }];
    $("#pl-table", v).innerHTML = rows.length ? `<h2>${rows.length} player${rows.length === 1 ? "" : "s"}</h2>` + table(cols, rows.map((p) => ({
      cells: [badge(p, 30), `<a class="pl-link" href="#/game/players/${encodeURIComponent(p.id)}">${esc(p.name)}</a>`, { text: KIND_SHORT[p.kind] || p.kind, color: "var(--g-muted)" },
        { text: p.style_label || "–", color: "var(--g-muted)" }, p.skill ?? "–", { text: sizesText(p.sizes), color: "var(--g-muted)" }, p.teams.length] })))
      : '<p class="gh-empty">No player matches.</p>';
  };
  v.querySelectorAll("#pl-kind button").forEach((b) => (b.onclick = () => { state.kind = b.dataset.k; paint(); }));
  v.querySelectorAll("#pl-size button").forEach((b) => (b.onclick = () => { state.size = Number(b.dataset.n); paint(); }));
  $("#pl-q", v).oninput = (e) => { state.q = e.target.value; paint(); };
  paint();
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    const inField = document.activeElement?.tagName === "INPUT";
    if (e.key === "Escape") { if (inField) document.activeElement.blur(); else go("#/game"); }
    else if (e.key === "/" && !inField) { e.preventDefault(); $("#pl-q", v).focus(); }
  };
}

// ---------- one player: who it is, how it was made, how it plays, where it plays ----------
const ORIGIN_LABEL = { made: "Added", from: "Made from", run: "Training run", line: "Line", team: "Was the net of", legacy_elo: "Old 5v5 Elo (team ladder)", checkpoint: "Checkpoint" };

export function playerPage(id) {
  const p = G.playerById[id];
  if (!p) { go("#/game/players"); return; }
  const st = styleOf(p.style);
  const origin = Object.entries(p.origin || {}).map(([k, val]) => `<div class="pl-kv"><span>${esc(ORIGIN_LABEL[k] || k)}</span><b>${esc(String(val))}</b></div>`).join("");
  const bars = st ? Object.entries(st.params).map(([k, val]) => `<div class="pl-bar"><span>${esc(PARAM_LABEL[k] || k)}</span><i><b style="width:${Math.round(100 * Math.max(0, Math.min(1, val)))}%"></b></i></div>`).join("") : "";
  const teams = teamsOf(p);
  const v = mount(shell(`<section class="gp-hero row pl-hero" style="--kc:${{ rules: "#4f8fd8", opus: "#d97757", net: "#5fb87a" }[p.kind] || "#888"}">${badge(p, 120)}
      <div class="gt-info"><div class="gp-pill">${esc(p.kind_label)}${p.style_label ? " · " + esc(p.style_label) : ""}</div><h1 class="gt-name">${esc(p.name)}</h1>
        <p class="gt-plays">${esc(p.description)}</p>
        <div class="gt-who">${p.skill != null ? `Skill ${p.skill} · ` : ""}plays ${esc(sizesText(p.sizes))}${p.kind === "net" && p.sizes.length < 5 ? " (its observation only fits 5 per side)" : ""}</div>
        <div class="elo-sizes">${eloSizes(p)}</div></div>
      <button type="button" class="ks-go gt-play" id="pl-build">Build a team with ${esc(p.name.split(" ")[0])}</button></section>
    <div class="gh-grid">
      <section class="gp-card"><h2>How it was made</h2>${origin || '<p class="gh-empty">No notes.</p>'}</section>
      <section class="gp-card"><h2>${st ? "Style: " + esc(st.name) : "Style"}</h2>${st ? `<p class="g-caption">${esc(st.description)}</p>${bars}` : '<p class="gh-empty">A net has no hand-written style: it plays as it was trained.</p>'}</section>
    </div>
    <section class="gp-card"><h2>Plays for</h2>${teams.length ? `<div class="pl-teams">${teams.map((t) => `<a class="pl-team" href="#/game/teams/${encodeURIComponent(t.id)}">${Draw.logoTag(t.id, 34)}<span>${esc(t.name)}<small>${esc(t.league_name)} · ×${t.lineup.filter((x) => x === p.id).length}</small></span></a>`).join("")}</div>`
      : '<p class="gh-empty">No team fields this player yet: build one.</p>'}</section>`, [["Enter", "build a team with this player"], ["Esc", "back"]]));
  Draw.fillLogos(v, G.byId);
  $("#pl-build", v).onclick = () => { G.builderSeed = p.id; go("#/game/build"); };
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    if (e.key === "Escape") history.length > 1 ? history.back() : go("#/game/players");
    else if (e.key === "Enter" && document.activeElement?.tagName !== "A") { e.preventDefault(); G.builderSeed = p.id; go("#/game/build"); }
  };
}
