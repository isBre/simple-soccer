// The Game (web/game.js has the overview): the quick match team select.
import { $, CHEV, CONTROLS, G, btn, esc, go, leagueTeams, loadT, mount, playsText, prefs, savePrefs } from "./core.js";
import { match, play } from "./match.js";
import { menu } from "./menu.js";
import { showReport } from "./report.js";
import { teams } from "./teams.js";

// ---------- team select: the quick match screen (kit split). Each half is one side: its league, its team (crest, Elo, how it plays);
// the bar underneath holds the match settings. Keys: Tab / click picks the side, Left / Right its team, Up / Down its league,
// R random teams, Enter kick off, Esc back to the menu. Every choice is remembered in this browser (prefs).
export const SIZES = [1, 2, 3, 4, 5], MINUTES = [1, 2, 3, 5];
export function seg(name, items, sel, onPick, hint = "") {
  const el = document.createElement("div");
  el.className = "ks-seg";
  el.innerHTML = `<span class="ks-seg-l">${esc(name)}</span><span class="ks-seg-b" role="radiogroup" aria-label="${esc(name)}">${items.map((x, i) =>
    `<button type="button" role="radio" data-i="${i}"${hint ? ` title="${esc(hint)}"` : ""}>${esc(x)}</button>`).join("")}</span>`;
  const set = (i) => { sel = i; for (const b of el.querySelectorAll("button")) { const on = Number(b.dataset.i) === i; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); } };
  for (const b of el.querySelectorAll("button")) {
    b.addEventListener("mousedown", (e) => e.preventDefault());        // a click does not keep the focus: Enter still kicks off
    b.addEventListener("click", () => { set(Number(b.dataset.i)); onPick(sel); });
  }
  set(sel);
  const disable = (idx) => { for (const b of el.querySelectorAll("button")) b.disabled = idx.has(Number(b.dataset.i)); };
  return { el, set, get: () => sel, disable };
}
export const prefIdx = (k, d, n) => (Number.isInteger(prefs[k]) && prefs[k] >= 0 && prefs[k] < n ? prefs[k] : d);
export const DOWN = '<svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true"><polyline points="1,1 5,5 9,1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
export const closeLists = () => { for (const m of document.querySelectorAll(".ks-lg-menu")) m.hidden = true; for (const b of document.querySelectorAll(".ks-lg-btn")) b.setAttribute("aria-expanded", "false"); };
document.addEventListener("click", closeLists);
// a league (or any short list) as a pill with its name; a click opens the whole list. items: [{label, count}]
export function listPick(items, sel, onPick, title = "League") {
  const el = document.createElement("div");
  el.className = "ks-league";
  el.innerHTML = `<button type="button" class="ks-lg-btn" aria-haspopup="listbox" aria-expanded="false" title="${esc(title)}"><span></span>${DOWN}</button>
    <div class="ks-lg-menu" role="listbox" aria-label="${esc(title)}" hidden>${items.map((x, k) => `<button type="button" role="option" data-lg="${k}"><span>${esc(x.label)}</span><small>${x.count ?? ""}</small></button>`).join("")}</div>`;
  const b = $(".ks-lg-btn", el), m = $(".ks-lg-menu", el);
  const set = (k) => {
    sel = k; $("span", b).textContent = items[k].label;
    for (const o of m.querySelectorAll("[data-lg]")) { const on = Number(o.dataset.lg) === k; o.classList.toggle("on", on); o.setAttribute("aria-selected", on); }
  };
  b.addEventListener("mousedown", (e) => e.preventDefault());
  b.addEventListener("click", (e) => { e.stopPropagation(); const open = m.hidden; closeLists(); if (open) { m.hidden = false; b.setAttribute("aria-expanded", "true"); } });
  for (const o of m.querySelectorAll("[data-lg]")) {
    o.addEventListener("mousedown", (e) => e.preventDefault());
    o.addEventListener("click", (e) => { e.stopPropagation(); closeLists(); set(Number(o.dataset.lg)); onPick(sel); });
  }
  set(sel);
  return { el, set, get: () => sel };
}
// the crest carousel: the team in the middle, its neighbours in the list smaller and fainter (click one: onStep(offset))
export function drawReel(box, list, team, d, onStep, big = 200, small = 88) {
  const k = Math.max(0, list.indexOf(team)), n = list.length, reach = Math.floor((n - 1) / 2);
  box.replaceChildren(...[[-1, small, 0.45], [0, big, 1], [1, small, 0.45]].map(([off, px, op]) => {
    const slot = document.createElement("span");
    slot.className = "ks-slot" + (off ? "" : " mid");
    slot.style.width = slot.style.height = px + "px";
    const ok = off === 0 || (n > 1 && (off < 0 ? -off <= reach : off <= n - 1 - reach));
    if (ok) {
      const t = off ? list[(k + off + n) % n] : team;
      slot.append(Draw.logoCanvas(t.logo, px));
      slot.style.opacity = op;
      if (off) { slot.title = t.name; slot.addEventListener("click", (e) => { e.stopPropagation(); onStep(off); }); }
    }
    return slot;
  }));
  if (d) { box.classList.remove("slide-l", "slide-r"); void box.offsetWidth; box.classList.add(d > 0 ? "slide-l" : "slide-r"); }
}
// how you play a match: control and recording (not when watching). Remembered in prefs. (No role picker: you play balanced.)
export function playControls(onSync = () => {}) {
  const ctl = seg("Control", ["One player", "Whole team", "Watch"], prefIdx("control", 0, 3), (i) => { prefs.control = i; savePrefs(); sync(); });
  const rec = recToggle();
  const control = () => CONTROLS[ctl.get()];
  function sync() { rec.hidden = control() === "none"; onSync(control()); }
  return { els: [ctl.el, rec], control, sync, human: () => ({ control: control(), record: control() !== "none" && !!prefs.record }) };
}
// one toggle: record my play for the dataset (imitation learning), remembered in prefs
export function recToggle() {
  const rec = document.createElement("button");
  rec.type = "button"; rec.className = "ks-rec"; rec.title = "Save my play to the dataset (imitation learning)";
  const paint = () => { rec.classList.toggle("on", !!prefs.record); rec.setAttribute("aria-pressed", String(!!prefs.record)); rec.innerHTML = `<i></i>Record ${prefs.record ? "on" : "off"}`; };
  rec.addEventListener("mousedown", (e) => e.preventDefault());
  rec.onclick = () => { prefs.record = !prefs.record; savePrefs(); paint(); };
  paint();
  return rec;
}
export const youPill = '<span class="you-pill">You</span>';
export function teamSelect() {
  const C = G.cat, P = C.pitches, L = C.leagues;
  const byLeague = L.map((l) => leagueTeams(l.id));
  const save = loadT();
  const first = (i) => { const id = prefs.sides?.[i]; const t = id && G.byId[id]; return t ? t : (byLeague[0][i] || C.teams[i]); };
  const st = { side: 0, team: [first(0), first(1)] };
  let pitchIdx = Math.max(0, P.findIndex((p) => p.id === (prefs.pitch || "arena")));
  const v = mount(`<div class="ks">
    <div class="ks-top"><nav class="ks-links"><a href="#/game">‹ Menu</a><a id="ks-teams" href="#/game/teams">Teams and players</a></nav>
      <div class="ks-keys" id="ks-keys"></div></div>
    <div class="ks-split">${[0, 1].map((i) => `<section class="ks-side" data-side="${i}" tabindex="0" aria-label="${i ? "Away" : "Home"} team">
        <div class="ks-mark" aria-hidden="true"></div><div class="ks-role"><span class="ks-who"></span><span>${i ? "Away" : "Home"}</span></div>
        <div class="ks-league"><button type="button" class="ks-lg-btn" aria-haspopup="listbox" aria-expanded="false" title="League (↑ ↓)"><span></span><svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true"><polyline points="1,1 5,5 9,1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
          <div class="ks-lg-menu" role="listbox" aria-label="League" hidden>${L.map((l, k) => `<button type="button" role="option" data-lg="${k}"><span>${esc(l.name)}</span><small>${l.count}</small></button>`).join("")}</div></div>
        <div class="ks-pick"><button type="button" class="ks-chev" data-d="-1" aria-label="Previous team" tabindex="-1">${CHEV(-1)}</button><span class="ks-reel"></span><button type="button" class="ks-chev" data-d="1" aria-label="Next team" tabindex="-1">${CHEV(1)}</button></div>
        <div class="ks-name"></div><div class="ks-elo"></div><p class="ks-plays"></p></section>`).join('<div class="ks-vs"><div class="ks-vs-badge" aria-hidden="true"></div><button type="button" class="ks-swap" title="Swap the teams (S)" aria-label="Swap the teams">⇄</button></div>')}</div>
    <div class="ks-more" id="ks-more" hidden></div>
    <div class="ks-bar" id="ks-bar"><div class="ks-opts"></div><button type="button" class="ks-more-btn" id="ks-more-btn" aria-expanded="false">More</button><button type="button" class="ks-go" id="ks-go">Kick off</button></div></div>`);
  const sides = [...v.querySelectorAll(".ks-side")];
  const leagueOf = (t) => Math.max(0, L.findIndex((l) => l.id === t.league));
  const reel = (i, d) => drawReel($(".ks-reel", sides[i]), byLeague[leagueOf(st.team[i])], st.team[i], d, (off) => step(i, off));
  function paint(i, d = 0) {
    const t = st.team[i], el = sides[i];
    el.style.setProperty("--kc", "#" + t.colors[0]);
    reel(i, d);
    $(".ks-mark", el).replaceChildren(Draw.logoCanvas(t.logo, 620));
    $(".ks-split", v).style.setProperty("--c" + i, "#" + t.colors[0]);
    $(".ks-name", el).textContent = t.name;
    $(".ks-elo", el).textContent = t.elo != null ? `Elo ${t.elo}` : "Elo not rated yet";
    $(".ks-plays", el).textContent = playsText(t);
    $(".ks-lg-btn span", el).textContent = L[leagueOf(t)].name;
    for (const b of el.querySelectorAll("[data-lg]")) { const on = Number(b.dataset.lg) === leagueOf(t); b.classList.toggle("on", on); b.setAttribute("aria-selected", on); }
    if (i === st.side) $("#ks-teams", v).href = "#/game/teams/" + encodeURIComponent(t.id);
    prefs.sides = st.team.map((x) => x.id); savePrefs();
  }
  function focusSide(i) {
    st.side = i;
    sides.forEach((el, k) => el.classList.toggle("on", k === i));
    $("#ks-teams", v).href = "#/game/teams/" + encodeURIComponent(st.team[i].id);
  }
  function step(i, d) {
    const list = byLeague[leagueOf(st.team[i])], k = list.indexOf(st.team[i]);
    st.team[i] = list[(k + d + list.length) % list.length]; paint(i, d);
  }
  function league(i, k) {
    k = (k + L.length) % L.length;
    if (k === leagueOf(st.team[i]) || !byLeague[k].length) return;
    st.team[i] = byLeague[k][0]; paint(i);
  }
  function swap() { st.team.reverse(); paint(0); paint(1); }   // you always play the home side: swap to play the other team
  function randomize() {
    const all = C.teams; if (all.length < 2) return;
    const a = Math.floor(Math.random() * all.length); let b = Math.floor(Math.random() * (all.length - 1)); if (b >= a) b += 1;
    st.team = [all[a], all[b]]; paint(0); paint(1);
  }
  sides.forEach((el, i) => {
    el.addEventListener("mousedown", () => focusSide(i));
    el.addEventListener("focus", () => focusSide(i));
    for (const b of el.querySelectorAll(".ks-chev")) b.addEventListener("click", () => step(i, Number(b.dataset.d)));
    // the league: its name; a click opens the list of every league (more can be added in data/), Up / Down cycles through them
    const lgBtn = $(".ks-lg-btn", el), menu = $(".ks-lg-menu", el);
    lgBtn.addEventListener("mousedown", (e) => e.preventDefault());
    lgBtn.addEventListener("click", (e) => { e.stopPropagation(); const open = menu.hidden; closeMenus(); if (open) { menu.hidden = false; lgBtn.setAttribute("aria-expanded", "true"); } });
    for (const b of menu.querySelectorAll("[data-lg]")) {
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("click", (e) => { e.stopPropagation(); closeMenus(); league(i, Number(b.dataset.lg)); });
    }
  });
  function closeMenus() {
    for (const m of v.querySelectorAll(".ks-lg-menu")) m.hidden = true;
    for (const b of v.querySelectorAll(".ks-lg-btn")) b.setAttribute("aria-expanded", "false");
  }
  v.addEventListener("click", closeMenus);
  // the bar: players, minutes, control (+ recording); More: the pitch
  const opts = $(".ks-opts", v);
  const size = seg("Players", SIZES.map((n) => `${n}v${n}`), prefIdx("size", Math.max(1, Math.min(5, P[pitchIdx].recommended)) - 1, 5), (i) => { prefs.size = i; savePrefs(); });
  const mins = seg("Minutes", MINUTES.map(String), prefIdx("minutes", 2, MINUTES.length), (i) => { prefs.minutes = i; savePrefs(); });
  const pc = playControls(() => sync());
  opts.append(size.el, mins.el, ...pc.els);
  const pitch = seg("Pitch", P.map((p) => p.name), pitchIdx, (i) => {
    pitchIdx = i; prefs.pitch = P[i].id; savePrefs();
    const n = Math.max(1, Math.min(5, P[i].recommended)) - 1; size.set(n); prefs.size = n; savePrefs(); pitchInfo();
  });
  const info = document.createElement("span"); info.className = "ks-info";
  const pitchInfo = () => { const p = P[pitchIdx]; info.textContent = `${Math.round(p.half_w * 2)} x ${Math.round(p.half_h * 2)}, goal ${Math.round(p.goal_half * 2)} wide`; };
  $("#ks-more", v).append(pitch.el, info); pitchInfo();
  const moreBtn = $("#ks-more-btn", v);
  moreBtn.addEventListener("mousedown", (e) => e.preventDefault());
  moreBtn.onclick = () => { const m = $("#ks-more", v); m.hidden = !m.hidden; moreBtn.setAttribute("aria-expanded", String(!m.hidden)); moreBtn.classList.toggle("on", !m.hidden); };
  function sync() {
    const c = pc.control();
    sides.forEach((el, k) => {                                        // who plays which side: you are always the home team
      const you = c !== "none" && k === 0, who = $(".ks-who", el);
      who.textContent = you ? "You" : "AI"; who.classList.toggle("you", you);
    });
    $("#ks-keys", v).innerHTML = [["Tab", "side"], ["← →", "team"], ["↑ ↓", "league"], ["S", "swap"], ["R", "random"], ["Enter", "kick off"], ["Esc", "menu"]].concat(c === "team" ? [["Q", "switch player in the match"]] : [])
      .map(([k, d]) => `<span><kbd>${k}</kbd> ${d}</span>`).join("");
  }
  function start() {
    // a team of 5v5-only nets cannot play smaller sizes: the match is played at the largest size both teams can play
    const both = SIZES.filter((n) => st.team[0].sizes.includes(n) && st.team[1].sizes.includes(n));
    if (both.length && !both.includes(SIZES[size.get()])) size.set(SIZES.indexOf(both[both.length - 1]));
    const setup = { home: st.team[0].id, away: st.team[1].id, pitch: P[pitchIdx].id, size: SIZES[size.get()], duration: MINUTES[mins.get()] * 60,
      seed: Math.floor(Math.random() * 2147483647), human_team: 0, allow_draw: true, ...pc.human() };
    play({ setup, rematch: true, done: (res) => showReport(res, "#/game/quick"), quit: () => go("#/game/quick") });
  }
  $("#ks-go", v).onclick = start;
  $(".ks-swap", v).addEventListener("mousedown", (e) => e.preventDefault());
  $(".ks-swap", v).onclick = swap;
  paint(0); paint(1); pc.sync(); focusSide(0); sides[0].focus({ preventScroll: true });
  G.keyHandler = (e, down) => {
    if (!down) return;
    const tag = document.activeElement?.tagName, inBar = document.activeElement?.closest?.(".ks-bar, .ks-more, .ks-links");   // the bar keeps its own keys
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { if (inBar) return; e.preventDefault(); step(st.side, e.key === "ArrowLeft" ? -1 : 1); }
    else if (e.key === "ArrowUp" || e.key === "ArrowDown") { if (inBar) return; e.preventDefault(); closeMenus(); league(st.side, leagueOf(st.team[st.side]) + (e.key === "ArrowUp" ? -1 : 1)); }
    else if (e.repeat) return;
    else if (e.key === "Tab" && !inBar && document.activeElement?.classList.contains("ks-side")) {
      const k = st.side + (e.shiftKey ? -1 : 1);
      if (k === 0 || k === 1) { e.preventDefault(); sides[k].focus(); }
    } else if (e.key === "r" || e.key === "R") randomize();
    else if (e.key === "s" || e.key === "S") swap();
    else if (e.key === "Escape") { if (v.querySelector(".ks-lg-menu:not([hidden])")) closeMenus(); else go("#/game"); }
    else if (e.key === "Enter" && !(tag === "BUTTON" && inBar) && tag !== "A") { e.preventDefault(); start(); }
  };
}
