// The Game (web/game.js has the overview): build a team. Five players in order (rule-based and net players can be mixed),
// colours, kit and crest. There is no tactic: every player plays its own style in any team. Saved on this machine only
// (POST /api/game/team -> local/my_teams/, game/api.py save_team); the teams of data/teams can be copied, never edited.
import { $, G, KIND_SHORT, api, catalog, esc, go, mount, prefs, savePrefs, shell, sizesText } from "./core.js";
import { badge } from "./players.js";

const SIZES = [1, 2, 3, 4, 5];
const PALETTE = ["e74c3c", "e67e22", "f1c40f", "2ecc71", "1abc9c", "3498db", "9b59b6", "e84393", "00cec9", "d35400", "16a085", "2c3e50", "f5f0e8", "1d1d1f"];
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];

function randomLook(opts) {
  const c1 = pick(PALETTE), c2 = pick(PALETTE.filter((c) => Draw.dist(Draw.rgb(c), Draw.rgb(c1)) > 0.45));
  return { colors: { primary: c1, secondary: c2 }, kit: pick(opts.kits),
           logo: { shape: pick(opts.crest.shape), pattern: pick(opts.crest.pattern), symbol: pick(opts.crest.symbol), c3: "ffffff" } };
}

// which players take the pitch at each size: the first N of the line-up who can play it, repeated from the top if fewer (soccer/teams.py)
export function fielded(lineup, n) {
  const pool = lineup.map((id) => G.playerById[id]).filter((p) => p && p.sizes.includes(n));
  return pool.length ? Array.from({ length: n }, (_, i) => pool[i % pool.length]) : [];
}

export async function builder(teamId, copy) {
  const opts = G.cat.builder;
  const src = G.byId[teamId];
  const edit = src && src.custom && !copy;
  const d = src ? { id: edit ? src.id : "", name: edit ? src.name : src.name.slice(0, 24) + " (mine)", short: edit ? src.short : "",
                    colors: { primary: src.colors[0], secondary: src.colors[1] }, kit: src.kit, logo: { ...src.logo },
                    lineup: src.lineup.slice() }
    : { id: "", name: "My Team", short: "", ...randomLook(opts), lineup: [G.builderSeed || "", "", "", "", ""] };
  G.builderSeed = null;
  let slot = d.lineup.findIndex((x) => !x);
  if (slot < 0) slot = 0;
  const filt = { kind: "", q: "" };

  const v = mount(shell(`<div class="bd">
    <section class="gp-hero row bd-head" id="bd-head"><div class="ks-mark" aria-hidden="true"></div><span class="bd-crest"></span>
      <div class="gt-info"><div class="gp-pill">${edit ? "Your team" : src ? "Copy of " + esc(src.name) : "New team"} · My Teams</div>
        <input class="bd-name" id="bd-name" maxlength="30" value="${esc(d.name)}" aria-label="Team name">
        <div class="gt-who" id="bd-sizes"></div></div>
      <div class="bd-actions"><button type="button" class="ks-go" id="bd-save">Save</button>
        ${edit ? '<button type="button" class="ks-btn2" id="bd-play">Quick match</button><button type="button" class="ks-btn2 bd-del" id="bd-del">Delete</button>' : ""}</div></section>
    <p class="g-bad bd-err" id="bd-err" hidden></p>
    <div class="bd-grid">
      <section class="gp-card"><h2>Line-up</h2><p class="g-caption">A match of N per side fields the first N players below who can play that size. Click a slot, then a player.</p>
        <div class="bd-slots" id="bd-slots"></div>
        <p class="g-caption">There are no tactics: every player plays its own style in any team.</p></section>
      <section class="gp-card"><h2>Pick a player for slot <span id="bd-slotno"></span></h2>
        <div class="pl-filters bd-pf"><div class="pl-seg" id="bd-kind">${[["", "All"], ["rules", "Rule-based"], ["net", "Nets"]].map(([k, l]) => `<button type="button" data-k="${k}">${l}</button>`).join("")}</div>
          <input id="bd-q" class="pl-q" type="search" placeholder="Search" aria-label="Search players"></div>
        <div class="bd-pool" id="bd-pool"></div></section>
      <section class="gp-card"><h2>Colours and crest</h2>
        <div class="bd-row"><label class="bd-field"><span>Short name</span><input id="bd-short" maxlength="4" value="${esc(d.short)}" placeholder="${esc(d.name.slice(0, 3).toUpperCase())}"></label>
          <label class="bd-field"><span>Main colour</span><input type="color" id="bd-c1" value="#${d.colors.primary}"></label>
          <label class="bd-field"><span>Second colour</span><input type="color" id="bd-c2" value="#${d.colors.secondary}"></label>
          <label class="bd-field"><span>Crest symbol</span><input type="color" id="bd-c3" value="#${d.logo.c3 || "ffffff"}"></label>
          <button type="button" class="ks-btn2" id="bd-random">Random look</button></div>
        ${[["kit", "Kit", opts.kits], ["shape", "Crest shape", opts.crest.shape], ["pattern", "Crest pattern", opts.crest.pattern], ["symbol", "Crest symbol", opts.crest.symbol]]
          .map(([k, l, xs]) => `<div class="bd-opt"><span>${l}</span><div class="pl-seg" data-opt="${k}">${xs.map((x) => `<button type="button" data-v="${x}">${x}</button>`).join("")}</div></div>`).join("")}</section>
    </div></div>`, [["1-5", "slot"], ["Enter", "save"], ["Esc", "back"]]));

  const look = () => ({ ...d.logo, c1: d.colors.primary, c2: d.colors.secondary });
  function paintLook() {
    $(".bd-crest", v).replaceChildren(Draw.logoCanvas(look(), 130));
    $(".ks-mark", v).replaceChildren(Draw.logoCanvas(look(), 520));
    $("#bd-head", v).style.setProperty("--kc", "#" + d.colors.primary);
    for (const seg of v.querySelectorAll("[data-opt]")) {
      const k = seg.dataset.opt, cur = k === "kit" ? d.kit : d.logo[k];
      for (const b of seg.children) b.classList.toggle("on", b.dataset.v === cur);
    }
    $("#bd-c1", v).value = "#" + d.colors.primary; $("#bd-c2", v).value = "#" + d.colors.secondary; $("#bd-c3", v).value = "#" + (d.logo.c3 || "ffffff");
  }
  function paintSlots() {
    $("#bd-slots", v).innerHTML = d.lineup.map((id, i) => {
      const p = G.playerById[id];
      return `<div class="bd-slot${i === slot ? " on" : ""}" data-i="${i}"><span class="k">${i + 1}</span>${p ? badge(p, 30) : '<span class="pl-badge empty" style="width:30px;height:30px"></span>'}
        <span class="n">${p ? esc(p.name) + `<small>${esc(KIND_SHORT[p.kind])}${p.style_label ? " · " + esc(p.style_label) : ""} · ${esc(sizesText(p.sizes))}</small>` : '<em>empty: pick a player</em>'}</span>
        <button type="button" class="bd-mini" data-up="${i}" title="Move up" ${i === 0 ? "disabled" : ""}>↑</button><button type="button" class="bd-mini" data-down="${i}" title="Move down" ${i === 4 ? "disabled" : ""}>↓</button>
        <button type="button" class="bd-mini" data-clear="${i}" title="Empty the slot" ${p ? "" : "disabled"}>×</button></div>`;
    }).join("");
    $("#bd-slotno", v).textContent = slot + 1;
    // which sizes the team can play, and who takes the pitch at each
    const can = SIZES.filter((n) => fielded(d.lineup, n).length);
    $("#bd-sizes", v).innerHTML = d.lineup.every(Boolean)
      ? `Plays ${esc(sizesText(can))}. ` + (can.length < 5 ? `<span class="g-accent">The nets in the line-up only play 5v5: smaller sizes field the others.</span>` : "")
        + SIZES.filter((n) => can.includes(n) && n < 5).map((n) => `<br><span class="g-caption">${n}v${n}: ${fielded(d.lineup, n).map((p) => esc(p.name)).join(", ")}</span>`).join("")
      : "Fill all five slots to save the team.";
    $("#bd-save", v).disabled = !d.lineup.every(Boolean) || !can.length;
  }
  function paintPool() {
    for (const b of v.querySelectorAll("#bd-kind button")) b.classList.toggle("on", b.dataset.k === filt.kind);
    const q = filt.q.trim().toLowerCase();
    const list = G.cat.players.filter((p) => (!filt.kind || p.kind === filt.kind) && (!q || (p.name + " " + p.style_label).toLowerCase().includes(q)));
    $("#bd-pool", v).innerHTML = list.map((p) => `<button type="button" class="bd-pick${d.lineup[slot] === p.id ? " on" : ""}" data-p="${esc(p.id)}" title="${esc(p.description)}">${badge(p, 28)}
      <span class="n">${esc(p.name)}<small>${esc(KIND_SHORT[p.kind])}${p.skill != null ? " " + p.skill : ""}${p.style_label ? " · " + esc(p.style_label) : ""}${p.sizes.length < 5 ? " · 5v5 only" : ""}</small></span>
      <a class="bd-info" href="#/game/players/${encodeURIComponent(p.id)}" title="About ${esc(p.name)}" tabindex="-1">i</a></button>`).join("") || '<p class="gh-empty">No player matches.</p>';
  }
  const err = (msg) => { const e = $("#bd-err", v); e.hidden = !msg; e.textContent = msg || ""; };

  // ---------- events ----------
  $("#bd-slots", v).onclick = (e) => {
    const b = e.target.closest("button"), row = e.target.closest(".bd-slot");
    if (b?.dataset.up) { const i = +b.dataset.up; [d.lineup[i - 1], d.lineup[i]] = [d.lineup[i], d.lineup[i - 1]]; slot = i - 1; }
    else if (b?.dataset.down) { const i = +b.dataset.down; [d.lineup[i + 1], d.lineup[i]] = [d.lineup[i], d.lineup[i + 1]]; slot = i + 1; }
    else if (b?.dataset.clear) { d.lineup[+b.dataset.clear] = ""; slot = +b.dataset.clear; }
    else if (row) slot = +row.dataset.i;
    paintSlots(); paintPool();
  };
  $("#bd-pool", v).onclick = (e) => {
    if (e.target.closest(".bd-info")) return;                       // the "i" opens the player's page
    const b = e.target.closest("[data-p]"); if (!b) return;
    d.lineup[slot] = b.dataset.p;
    const next = d.lineup.findIndex((x) => !x);
    if (next >= 0) slot = next;
    paintSlots(); paintPool();
  };
  v.querySelectorAll("#bd-kind button").forEach((b) => (b.onclick = () => { filt.kind = b.dataset.k; paintPool(); }));
  $("#bd-q", v).oninput = (e) => { filt.q = e.target.value; paintPool(); };
  $("#bd-name", v).oninput = (e) => { d.name = e.target.value; $("#bd-short", v).placeholder = d.name.slice(0, 3).toUpperCase(); };
  $("#bd-short", v).oninput = (e) => { d.short = e.target.value; };
  $("#bd-c1", v).oninput = (e) => { d.colors.primary = e.target.value.slice(1); paintLook(); };
  $("#bd-c2", v).oninput = (e) => { d.colors.secondary = e.target.value.slice(1); paintLook(); };
  $("#bd-c3", v).oninput = (e) => { d.logo.c3 = e.target.value.slice(1); paintLook(); };
  $("#bd-random", v).onclick = () => { const r = randomLook(opts); Object.assign(d, { colors: r.colors, kit: r.kit, logo: r.logo }); paintLook(); };
  for (const seg of v.querySelectorAll("[data-opt]")) seg.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (seg.dataset.opt === "kit") d.kit = b.dataset.v; else d.logo[seg.dataset.opt] = b.dataset.v;
    paintLook();
  };
  async function save() {
    if (!d.lineup.every(Boolean)) return err("Fill all five slots first.");
    err("");
    try {
      const r = await api("/api/game/team", { action: "save", team: { ...d, logo: look() } });
      await catalog(true);
      go("#/game/teams/" + encodeURIComponent(r.team.id));
    } catch (e) { err(e.message); }
  }
  $("#bd-save", v).onclick = save;
  if (edit) {
    $("#bd-del", v).onclick = async () => {
      if (!confirm(`Delete ${d.name}? It cannot be undone.`)) return;
      try { await api("/api/game/team", { action: "delete", id: d.id }); await catalog(true); go("#/game/teams"); } catch (e) { err(e.message); }
    };
    $("#bd-play", v).onclick = () => {
      prefs.sides = [d.id, (prefs.sides || [])[1] && prefs.sides[1] !== d.id ? prefs.sides[1] : G.cat.teams.find((x) => x.id !== d.id).id];
      savePrefs(); go("#/game/quick");
    };
  }
  paintLook(); paintSlots(); paintPool();
  G.keyHandler = (e, down) => {
    if (!down || e.repeat) return;
    const tag = document.activeElement?.tagName, typing = tag === "INPUT" || tag === "SELECT";
    if (e.key === "Escape") { if (typing) document.activeElement.blur(); else history.length > 1 ? history.back() : go("#/game/teams"); }
    else if (!typing && e.key >= "1" && e.key <= "5") { slot = Number(e.key) - 1; paintSlots(); paintPool(); }
    else if (e.key === "Enter" && tag !== "BUTTON" && tag !== "A" && tag !== "SELECT") { e.preventDefault(); save(); }
  };
}
