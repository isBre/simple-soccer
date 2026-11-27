// The Game (web/game.js has the overview): the Rankings, one page per team size (#/game/rankings/<size>), players and teams.
// The ratings are this machine's (elo/, local/elo.db: python3 -m elo init after cloning; the web server keeps refining them).
import { $, G, api, esc, go, mount, playerLink, shell, table } from "./core.js";
import { badge } from "./players.js";

const SIZES = [1, 2, 3, 4, 5];
const st = { tab: "players" };

export async function rankingsPage(size) {
  size = SIZES.includes(size) ? size : 5;
  history.replaceState(null, "", "#/game/rankings/" + size);
  const v = mount(shell(`<section class="gp-hero row rk-head"><div class="gt-info"><div class="gp-pill">Rankings</div><h1 class="gt-name">${size}v${size}</h1>
      <p class="gt-plays">Elo from matches played on this computer (${size} per side, arena, 90 s). The average rule-based player is 1500;
      ± is the 95% range. A player is rated as five copies of itself; a team as the average of the players on the pitch plus a small bonus.</p></div></section>
    <div class="pl-filters"><div class="pl-seg" id="rk-size">${SIZES.map((n) => `<button type="button" data-n="${n}" class="${n === size ? "on" : ""}">${n}v${n}</button>`).join("")}</div>
      <div class="pl-seg" id="rk-tab"><button type="button" data-t="players">Players</button><button type="button" data-t="teams">Teams</button></div>
      <span class="g-caption" id="rk-meta"></span></div>
    <section class="gp-card" id="rk-table"><p class="gh-empty">Loading…</p></section>`, [["1-5", "size"], ["Tab", "players / teams"], ["Esc", "menu"]]));
  v.querySelectorAll("#rk-size button").forEach((b) => (b.onclick = () => go("#/game/rankings/" + b.dataset.n)));
  v.querySelectorAll("#rk-tab button").forEach((b) => (b.onclick = () => { st.tab = b.dataset.t; paint(); }));
  let d = null;
  try { d = await api("/api/game/rankings?size=" + size); }
  catch (e) { $("#rk-table", v).innerHTML = `<p class="g-bad">The ratings could not be read: ${esc(e.message)}</p>`; return; }
  function paint() {
    for (const b of v.querySelectorAll("#rk-tab button")) b.classList.toggle("on", b.dataset.t === st.tab);
    $("#rk-meta", v).textContent = d.matches ? `${d.matches.toLocaleString()} matches · last ${d.last ? d.last.replace("T", " ") : "–"}` : "No matches yet: run python3 -m elo init";
    const rows = st.tab === "players" ? d.players : d.teams;
    const cols = [{ t: "#", w: 40 }, { t: "", w: 40 }, { t: st.tab === "players" ? "Player" : "Team" }, { t: "Elo", w: 110, a: "r" }, { t: "Games", w: 70, a: "r" },
      { t: "W-D-L", w: 100, a: "r" }, { t: "Scored", w: 70, a: "r" }, { t: "Conceded", w: 80, a: "r" }].concat(st.tab === "teams" ? [{ t: "Bonus", w: 70, a: "r" }] : []);
    const elo = (r) => `<b>${r.elo}</b> <span class="g-caption">±${r.pm}</span>${r.placed ? "" : ' <span class="g-caption" title="fewer than 6 games">prov.</span>'}`;
    $("#rk-table", v).innerHTML = rows.length ? table(cols, rows.map((r) => ({
      hl: !r.games ? false : undefined,
      cells: [{ text: r.rank, color: "var(--g-muted)" },
        st.tab === "players" ? (G.playerById[r.player] ? badge(G.playerById[r.player], 28) : "") : Draw.logoTag(r.team, 28),
        st.tab === "players" ? playerLink(r.player, r.name) : `<a class="pl-link" href="#/game/teams/${encodeURIComponent(r.team)}">${esc(r.name)}</a>`,
        r.games ? elo(r) : { text: "unrated", color: "var(--g-muted)" }, r.games, r.games ? `${r.w}-${r.d}-${r.l}` : "–",
        r.agf ?? "–", r.aga ?? "–"].concat(st.tab === "teams" ? [r.bonus == null ? { text: "–", color: "var(--g-muted)" } : (r.bonus > 0 ? "+" : "") + r.bonus] : []) })))
      : `<p class="gh-empty">Nobody here can play ${size}v${size}.</p>`;
    Draw.fillLogos($("#rk-table", v), G.byId);
  }
  paint();
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    if (e.key === "Escape") go("#/game");
    else if (e.key >= "1" && e.key <= "5") go("#/game/rankings/" + e.key);
    else if (e.key === "Tab") { e.preventDefault(); st.tab = st.tab === "players" ? "teams" : "players"; paint(); }
  };
}
