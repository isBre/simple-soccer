// The Game area: Simple Soccer in the browser. The pages are those of the Godot game (main menu, quick match, teams & squads,
// tournaments, match report) and the match itself is played by the Python match core on the server: game/session.py streams
// every tick over a WebSocket, this page draws it and sends the keyboard back.
// Routes: #/game · #/game/quick · #/game/puzzle · #/game/teams[/<id>] · #/game/tournament/new · #/game/tournament · #/game/match · #/game/report
// lab.js owns the router and calls Game.show(parts) for #/game/... ; the tournament is kept in this browser (localStorage).
"use strict";

const Game = (() => {
  const G = { cat: null, byId: {}, keyHandler: null, match: null, pending: null, report: null, tab: 0, busy: false, pz: null };
  const SAVE = "soccer.tournament";
  const CONTROLS = ["single", "team", "none"];
  // "Record my play": the match is saved as a dataset file for imitation learning (game/recorder.py), remembered in this browser
  const PREFS = "soccer.prefs";
  const prefs = (() => { try { return { record: true, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; } catch (e) { return { record: true }; } })();
  const savePrefs = () => { try { localStorage.setItem(PREFS, JSON.stringify(prefs)); } catch (e) {} };
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const view = () => document.getElementById("view");
  const go = (h) => { location.hash = h; };
  const RAT = (r) => (r >= 7.5 ? "var(--g-good)" : r >= 6.5 ? "#b9e36a" : r >= 5.8 ? "var(--g-accent)" : "var(--g-bad)");

  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    let d = {};
    try { d = await r.json(); } catch (e) { d = { error: "HTTP " + r.status }; }
    if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
    return d;
  }
  async function catalog() {
    if (!G.cat) { G.cat = await api("/api/game/catalog"); for (const t of G.cat.teams) G.byId[t.id] = t; }
    return G.cat;
  }
  const loadT = () => { try { return JSON.parse(localStorage.getItem(SAVE) || "null"); } catch (e) { return null; } };
  const saveT = (t) => { try { localStorage.setItem(SAVE, JSON.stringify(t)); } catch (e) {} };
  const leagueTeams = (id) => G.cat.teams.filter((t) => t.league === id);
  const pitchOf = (id) => G.cat.pitches.find((p) => p.id === id) || G.cat.pitches[0];

  // ---------- small components ----------
  function mount(html) { const v = view(); v.innerHTML = html; Draw.fillLogos(v, G.byId); return v; }
  const btn = (label, attrs = "", cls = "") => `<button class="g-btn ${cls}" ${attrs}>${label}</button>`;
  const card = (body, title = "", cls = "", style = "") => `<div class="g-card ${cls}" style="${style}">${title ? `<h2>${esc(title)}</h2>` : ""}${body}</div>`;
  const header = (title, sub) => `<div><h1 class="g-h1">${esc(title)}</h1>${sub ? `<p class="g-sub">${esc(sub)}</p>` : ""}</div>`;
  const CHEV = (d) => `<svg width="14" height="24" viewBox="0 0 14 24" style="--nudge:${d * 2}px"><polyline points="${d > 0 ? "3,1 11,12 3,23" : "11,1 3,12 11,23"}" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  // a table in the game's look: cols [{t, w, a: l|r|c}], rows [{cells: [html | {text, color, size}], hl, zone}]
  function table(cols, rows) {
    const cell = (c) => (c && typeof c === "object" ? `<span style="${c.color ? "color:" + c.color + ";" : ""}${c.size ? "font-size:" + c.size + "px;" : ""}${c.bold ? "font-weight:700;" : ""}">${esc(c.text)}</span>` : c);
    return `<table class="g-table"><thead><tr>${cols.map((c) => `<th class="${c.a || ""}" style="${c.w ? "width:" + c.w + "px" : ""}">${esc(c.t)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
      `<tr class="${r.hl ? "hl" : ""}${r.zone ? " zone" : ""}">${r.cells.map((c, i) => `<td class="${cols[i].a || ""}">${cell(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  const teamCell = (t, text, color, px = 24, you = false) => `<span class="teamcell">${Draw.logoTag(t.id, px)}<span style="color:${color || "inherit"}">${esc(text)}</span>${you ? '<span class="you-pill">You</span>' : ""}</span>`;
  function overlay(html) { const o = document.createElement("div"); o.className = "g-overlay"; o.innerHTML = html; document.body.append(o); return o; }

  // ---------- entry (called by lab.js for every #/game/... route) ----------
  async function show(parts) {
    stopMatch();
    document.body.classList.remove("g-playing");
    for (const o of document.querySelectorAll(".g-overlay")) o.remove();
    G.keyHandler = null;
    try { await catalog(); }
    catch (e) { mount(`<div class="g-page">${header("Simple Soccer")}<p class="g-error">The game server is not available: ${esc(e.message)}</p></div>`); return; }
    const [a, b] = parts;
    if (a === "quick") return teamSelect();
    if (a === "puzzle") return puzzlePage();
    if (a === "teams") return teams(b ? decodeURIComponent(b) : "");
    if (a === "tournament" && b === "new") return tourNew();
    if (a === "tournament") return tourHub();
    if (a === "match" && G.pending) return match(G.pending);
    if (a === "report" && G.report) return report(G.report.result, G.report.cont);
    if (a === "match" || a === "report") { history.replaceState(null, "", "#/game"); }
    return menu();
  }
  document.addEventListener("keydown", (e) => {
    if (document.body.dataset.area !== "game" || !G.keyHandler) return;
    const tag = document.activeElement?.tagName;
    if ((tag === "INPUT" || tag === "TEXTAREA") && e.key !== "Escape") return;
    G.keyHandler(e, true);
  });
  document.addEventListener("keyup", (e) => { if (document.body.dataset.area === "game" && G.keyHandler) G.keyHandler(e, false); });

  // ---------- main menu: Quick match (the team select), the tournament, the teams. Up / Down move, Enter opens.
  function menu() {
    const save = loadT();
    const items = [["Quick match", "#/game/quick", "Pick two teams and play"]]
      .concat(save ? [["Continue tournament", "#/game/tournament", save.title || ""]] : [])
      .concat([["Puzzle", "#/game/puzzle", "One-minute rounds from random positions (data collection)"], ["New tournament", "#/game/tournament/new", "One league or all of them"], ["Teams and squads", "#/game/teams", `${G.cat.teams.length} teams in ${G.cat.leagues.length} leagues`]]);
    const v = mount(`<div class="gm"><div class="gm-in"><div class="gm-title">Simple Soccer</div><div class="gm-sub">Football against handmade and trained AI teams</div>
      <nav class="gm-list">${items.map(([label, href, sub], k) => `<a class="gm-item${k ? "" : " primary"}" href="${href}"><b>${esc(label)}</b><span>${esc(sub)}</span></a>`).join("")}</nav></div></div>`);
    const links = [...v.querySelectorAll(".gm-item")];
    links[0].focus({ preventScroll: true });
    G.keyHandler = (e, down) => {
      if (!down || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      e.preventDefault();
      const k = Math.max(0, links.indexOf(document.activeElement));
      links[(k + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length].focus();
    };
  }

  // ---------- team select: the quick match screen (kit split). Each half is one side: its league, its team (crest, Elo, how it plays);
  // the bar underneath holds the match settings. Keys: Tab / click picks the side, Left / Right its team, Up / Down its league,
  // R random teams, Enter kick off, Esc back to the menu. Every choice is remembered in this browser (prefs).
  const SIZES = [1, 2, 3, 4, 5], MINUTES = [1, 2, 3, 5];
  function seg(name, items, sel, onPick, hint = "") {
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
  const prefIdx = (k, d, n) => (Number.isInteger(prefs[k]) && prefs[k] >= 0 && prefs[k] < n ? prefs[k] : d);
  const DOWN = '<svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true"><polyline points="1,1 5,5 9,1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const closeLists = () => { for (const m of document.querySelectorAll(".ks-lg-menu")) m.hidden = true; for (const b of document.querySelectorAll(".ks-lg-btn")) b.setAttribute("aria-expanded", "false"); };
  document.addEventListener("click", closeLists);
  // a league (or any short list) as a pill with its name; a click opens the whole list. items: [{label, count}]
  function listPick(items, sel, onPick, title = "League") {
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
  function drawReel(box, list, team, d, onStep, big = 200, small = 88) {
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
  function playControls(onSync = () => {}) {
    const ctl = seg("Control", ["One player", "Whole team", "Watch"], prefIdx("control", 0, 3), (i) => { prefs.control = i; savePrefs(); sync(); });
    const rec = recToggle();
    const control = () => CONTROLS[ctl.get()];
    function sync() { rec.hidden = control() === "none"; onSync(control()); }
    return { els: [ctl.el, rec], control, sync, human: () => ({ control: control(), record: control() !== "none" && !!prefs.record }) };
  }
  // one toggle: record my play for the dataset (imitation learning), remembered in prefs
  function recToggle() {
    const rec = document.createElement("button");
    rec.type = "button"; rec.className = "ks-rec"; rec.title = "Save my play to the dataset (imitation learning)";
    const paint = () => { rec.classList.toggle("on", !!prefs.record); rec.setAttribute("aria-pressed", String(!!prefs.record)); rec.innerHTML = `<i></i>Record ${prefs.record ? "on" : "off"}`; };
    rec.addEventListener("mousedown", (e) => e.preventDefault());
    rec.onclick = () => { prefs.record = !prefs.record; savePrefs(); paint(); };
    paint();
    return rec;
  }
  const youPill = '<span class="you-pill">You</span>';
  function teamSelect() {
    const C = G.cat, P = C.pitches, L = C.leagues;
    const byLeague = L.map((l) => leagueTeams(l.id));
    const save = loadT();
    const first = (i) => { const id = prefs.sides?.[i]; const t = id && G.byId[id]; return t ? t : (byLeague[0][i] || C.teams[i]); };
    const st = { side: 0, team: [first(0), first(1)] };
    let pitchIdx = Math.max(0, P.findIndex((p) => p.id === (prefs.pitch || "arena")));
    const v = mount(`<div class="ks">
      <div class="ks-top"><nav class="ks-links"><a href="#/game">‹ Menu</a><a id="ks-teams" href="#/game/teams">Teams and squads</a></nav>
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
      const setup = { home: st.team[0].id, away: st.team[1].id, pitch: P[pitchIdx].id, size: SIZES[size.get()], duration: MINUTES[mins.get()] * 60,
        seed: Math.floor(Math.random() * 2147483647), human_team: 0, allow_draw: true, formations: ["", ""], ...pc.human() };
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

  // ---------- page shell of the other game pages: a slim top row (back to the menu, keys), then the page ----------
  const KEYS_HTML = (keys) => keys.map(([k, d]) => `<span><kbd>${k}</kbd> ${d}</span>`).join("");
  const shell = (body, keys = [], cls = "") => `<div class="gp ${cls}"><div class="ks-top"><nav class="ks-links"><a href="#/game">‹ Menu</a></nav><div class="ks-keys">${KEYS_HTML(keys)}</div></div>${body}</div>`;
  const eloText = (t) => (t.elo != null ? `Elo ${t.elo}` : "Elo not rated yet");
  const playsText = (t) => t.plays || "Play style not measured yet (python3 game/profiles.py).";
  const whoDrives = (t) => (t.id.startsWith("net_") ? "Driven by a trained net (reinforcement learning), with RL Team 5's squad."
    : t.net ? "Every player, the keeper included, is driven by a trained net (reinforcement learning)." : "Driven by the handmade AI.");

  // ---------- teams & squads: one league at a time (strongest first), the picked team in its colours with its squad ----------
  function teams(id) {
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

  // ---------- new tournament: your team on the left (in its colours), the settings on the right ----------
  const FORMATS = ["League", "Knockout", "Groups + knockout"];
  function tourNew() {
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
  async function tourHub() {
    const t0 = loadT();
    if (!t0) { history.replaceState(null, "", "#/game"); return menu(); }
    let d;
    try { d = await api("/api/game/tournament", { action: "view", t: t0 }); }
    catch (e) { mount(shell(`<p class="g-error">${esc(e.message)}</p>`)); return; }
    renderHub(d.t, d.view);
    const vw = d.view;
    if (!vw.finished && vw.user_fixture === null && !vw.eliminated && vw.pending > 0) simulateRound(d.t);   // the rest of the round after the player's match
  }
  const TABS = ["Match day", "Table", "Results", "Players"];
  function renderHub(t, vw) {
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
  const nameOf = (id) => esc(G.byId[id]?.name || id);
  function fixtureRow(t, f, detail) {
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
  function matchDayTab(t, vw) {
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
  function standingsTable(t, rows, qualify) {
    const cols = [{ t: "#", w: 40 }, { t: "Team" }, { t: "P", w: 48, a: "r" }, { t: "W", w: 48, a: "r" }, { t: "D", w: 48, a: "r" }, { t: "L", w: 48, a: "r" },
      { t: "GF", w: 52, a: "r" }, { t: "GA", w: 52, a: "r" }, { t: "GD", w: 56, a: "r" }, { t: "Pts", w: 60, a: "r" }];
    return table(cols, rows.map((r, i) => {
      const mine = r.id === t.user_team, gd = r.gd;
      return { hl: mine, zone: i < qualify, cells: [{ text: i + 1, color: "var(--g-muted)" }, teamCell(G.byId[r.id] || { id: r.id }, G.byId[r.id]?.name || r.id, "", 24, mine),
        r.p, r.w, r.d, r.l, r.gf, r.ga, { text: gd > 0 ? "+" + gd : gd, color: gd > 0 ? "var(--g-good)" : gd < 0 ? "var(--g-bad)" : "var(--g-muted)" },
        { text: r.pts, bold: true }] };
    }));
  }
  function tablesTab(t, vw) {
    if (!vw.tables.length) return '<p class="gh-empty">A knockout cup has no table: the Results tab shows every round.</p>';
    let out = "";
    for (const tb of vw.tables) out += `<section class="gp-card">${tb.title ? `<h2>${esc(tb.title)}</h2>` : ""}${standingsTable(t, tb.rows, vw.tables.length > 1 ? tb.qualify : 0)}</section>`;
    if (vw.tables.length > 1) out += '<div class="g-caption">Green bar: goes through to the knockout stage.</div>';
    return out;
  }
  function resultsTab(t) {
    let out = "";
    for (let i = t.rounds.length - 1; i >= 0; i--) {
      const r = t.rounds[i], played = r.fixtures.filter((f) => f.played);
      if (played.length) out += `<section class="gp-card"><h2>${esc(r.name)}</h2><div class="gf-list">${played.map((f) => fixtureRow(t, f, true)).join("")}</div></section>`;
    }
    return out || '<p class="gh-empty">No matches played yet.</p>';
  }
  function playersTab(t, vw) {
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
  async function simulateRound(t) {
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
  async function playUser(t) {
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

  // ---------- match report ----------
  function showReport(result, cont) { G.report = { result, cont }; G.pending = null; go("#/game/report"); }
  function report(res, cont) {
    const T = res.teams.map((id) => G.byId[id] || { id, name: id, colors: ["888888", "ffffff"], logo: {} });
    let note = "Full time";
    if (res.shootout && res.shootout.length) note = `Full time · penalties ${res.shootout[0]}–${res.shootout[1]}`;
    else if (res.overtime) note = "Full time · golden goal in overtime";
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
      ["Dribbles won", ts[0].dribbles, ts[1].dribbles, ts[0].dribbles, ts[1].dribbles], ["Saves", ts[0].saves, ts[1].saves, ts[0].saves, ts[1].saves]]
      .map((r) => stat(...r)).join("");
    const cols = [{ t: "#", w: 40 }, { t: "Player" }, { t: "Pos", w: 56 }, { t: "Grade", w: 66, a: "r" }, { t: "G", w: 40, a: "r" }, { t: "A", w: 40, a: "r" }, { t: "Shots", w: 64, a: "r" },
      { t: "Passes", w: 72, a: "r" }, { t: "Key", w: 46, a: "r" }, { t: "Tkl", w: 46, a: "r" }, { t: "Int", w: 46, a: "r" }, { t: "Drb", w: 46, a: "r" }, { t: "Sv", w: 46, a: "r" }];
    const ptable = (team) => table(cols, res.players.filter((p) => p.team === team).map((p) => {
      const mom = p.uid === res.mom;
      return { hl: mom, cells: [{ text: p.number, color: "var(--g-muted)" }, { text: (mom ? "★ " : "") + p.name, color: mom ? "var(--g-accent)" : "" }, { text: p.played, color: "var(--g-muted)" },
        { text: p.rating.toFixed(1), color: RAT(p.rating), bold: true }, p.goals, p.assists, `${p.shots_on_target}/${p.shots}`, `${p.passes_ok}/${p.passes_ok + p.passes_failed}`,
        p.key_passes, p.tackles, p.interceptions, p.dribbles, p.saves] };
    }));
    const mp = res.players.find((p) => p.uid === res.mom);
    const why = (p) => {
      const items = [["goals", "goal", "goals"], ["assists", "assist", "assists"], ["saves", "save", "saves"], ["key_passes", "key pass", "key passes"], ["tackles", "tackle", "tackles"],
        ["interceptions", "interception", "interceptions"], ["dribbles", "dribble won", "dribbles won"], ["progressive_passes", "progressive pass", "progressive passes"], ["clearances", "clearance", "clearances"]];
      const parts = items.filter(([k]) => p[k] > 0).map(([k, one, many]) => `${p[k]} ${p[k] === 1 ? one : many}`);
      if (p.xg >= 0.5) parts.push(p.xg.toFixed(1) + " xG");
      return parts.slice(0, 5).join(", ");
    };
    const v = mount(shell(`<section class="rp-head" style="--c0:#${T[0].colors[0]};--c1:#${T[1].colors[0]}">
        <div class="rp-team"><span class="rp-crest"></span><div class="rp-name">${esc(T[0].name)}</div><div class="rp-goals">${scorers(0)}</div></div>
        <div class="rp-mid"><div class="rp-score">${res.scores[0]} – ${res.scores[1]}</div><div class="rp-note">${esc(note)}</div><button type="button" class="ks-go" id="r-go">Continue</button></div>
        <div class="rp-team"><span class="rp-crest"></span><div class="rp-name">${esc(T[1].name)}</div><div class="rp-goals">${scorers(1)}</div></div></section>
      <div class="rp-grid"><section class="gp-card rp-stats" style="--c0:#${T[0].colors[0]};--c1:#${T[1].colors[0]}"><h2>Match stats</h2>${stats}</section>
        ${mp ? `<section class="gp-card rp-mom"><h2>Player of the match</h2><span class="rp-mom-crest"></span><div class="rp-mom-name">${esc(mp.name)}</div>
          <div class="g-caption">${esc(T[mp.team].name)}</div><div class="rp-mom-grade" style="color:${RAT(mp.rating)}">${mp.rating.toFixed(1)}</div><div class="rp-mom-why">${esc(why(mp))}</div></section>` : ""}</div>
      ${[0, 1].map((t) => `<section class="gp-card"><h2 class="rp-th"><span class="rp-tcrest" data-t="${t}"></span>${esc(T[t].name)} · player grades</h2>${ptable(t)}</section>`).join("")}`,
      [["Enter", "continue"]], "rp"));
    v.querySelectorAll(".rp-crest").forEach((el, t) => el.append(Draw.logoCanvas(T[t].logo, 88)));
    v.querySelectorAll(".rp-tcrest").forEach((el) => el.append(Draw.logoCanvas(T[Number(el.dataset.t)].logo, 24)));
    if (mp) $(".rp-mom-crest", v).append(Draw.logoCanvas(T[mp.team].logo, 56));
    $(".ks-links a", v).remove();                                      // the report always continues (a tournament result is already saved)
    const cont2 = () => { G.report = null; go(cont); };
    $("#r-go", v).onclick = cont2;
    window.scrollTo(0, 0);
    G.keyHandler = (e, down) => { if (down && !e.repeat && e.key === "Enter") { e.preventDefault(); cont2(); } };
  }

  // ---------- puzzle: rounds of at most 1 minute from a random layout, random teams every round, until the session time is used ----------
  // Every round: two random teams (any league), random sides, every player and the ball at random places (game/session.py), over at
  // the first goal. Points: you score first 3, nobody scores in 60 s 1, they score first 0. Recorded for the dataset when "Record my
  // play" is on (one file per round, grouped by session on the Lab's Dataset page).
  const PZ_LENGTHS = [300, 600, 900];
  const PZ_BEST = "soccer.puzzleBest";
  const pzBest = () => { try { return JSON.parse(localStorage.getItem(PZ_BEST) || "{}"); } catch (e) { return {}; } };
  const pzPlayed = (pz) => pz.rounds.reduce((s, r) => s + r.secs, 0);
  function puzzlePage() {
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
  function nextRound() {
    const pz = G.pz, all = G.cat.teams;
    const a = Math.floor(Math.random() * all.length); let b = Math.floor(Math.random() * (all.length - 1)); if (b >= a) b += 1;
    const setup = { home: all[a].id, away: all[b].id, pitch: "arena", size: 5, duration: 60, seed: Math.floor(Math.random() * 2147483647), control: pz.control,
      human_team: Math.random() < 0.5 ? 0 : 1, allow_draw: true, player: "random", record: prefs.record, session: pz.id, round: pz.rounds.length + 1 };
    const p = { setup, puzzle: Math.floor(Math.random() * 2147483647), session: pz, done: (res) => roundOver(res, setup), quit: () => { pz.done = true; pz.quit = true; finishPuzzle(); } };
    if (location.hash === "#/game/match") { stopMatch(); G.pending = p; match(p); }
    else play(p);
  }
  function roundOver(res, setup) {
    const pz = G.pz; if (!pz || pz.done) return;
    const h = setup.human_team, gf = res.scores[h], ga = res.scores[1 - h], goal = res.puzzle?.end === "goal";
    const outcome = goal ? (gf > ga ? "W" : "L") : "D";
    pz.rounds.push({ home: setup.home, away: setup.away, h, gf, ga, outcome, secs: Math.min(60, res.puzzle?.seconds ?? 60), pts: { W: 3, D: 1, L: 0 }[outcome] });
    if (pzPlayed(pz) >= pz.total) { pz.done = true; finishPuzzle(); } else nextRound();
  }
  function finishPuzzle() {
    const pz = G.pz;
    if (!pz.quit) { const best = pzBest(), score = pz.rounds.reduce((s, r) => s + r.pts, 0); if (best[pz.total] == null || score > best[pz.total]) { best[pz.total] = score; pz.newBest = true; try { localStorage.setItem(PZ_BEST, JSON.stringify(best)); } catch (e) {} } }
    stopMatch();
    G.pending = null;
    if (location.hash === "#/game/puzzle") puzzlePage(); else go("#/game/puzzle");
  }
  function puzzleSummary(pz) {
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
  function drawPuzzleHud(ctx, M, f, W, H, intro) {
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

  // the puzzle card, top right, in the scorebug's style: round, points, session time left (bar), one dot per round played
  function drawPuzzleCard(ctx, M, f, W) {
    const pz = M.p.session, R = pz.rounds, n = R.length + 1, pts = R.reduce((s, r) => s + r.pts, 0);
    const left = Math.max(0, pz.total - pzPlayed(pz) - (60 - f.tl)), used = Math.min(1, 1 - left / pz.total);
    const w = 248, pad = 14, h = 112, x0 = W - 16 - w, y0 = 14, xr = x0 + w - pad, MUTED = "#8d98ab";
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)"; ctx.shadowBlur = 14; ctx.shadowOffsetY = 4;
    roundRect(ctx, x0, y0, w, h, 9, "#12161d");
    ctx.restore();
    ctx.save(); ctx.beginPath(); ctx.roundRect(x0, y0, w, h, 9); ctx.clip();
    ctx.fillStyle = "#ffd54a"; ctx.fillRect(x0, y0, w, 4);
    ctx.restore();
    // row 1: PUZZLE | ROUND n
    ctx.letterSpacing = "1.5px";
    text(ctx, "PUZZLE", x0 + pad, y0 + 26, "l", 0, 11, MUTED, 0, "", 700);
    ctx.letterSpacing = "0px";
    text(ctx, `ROUND ${n}`, x0 + pad, y0 + 26, "r", w - 2 * pad, 13, "#fff", 0, "", 700);
    // row 2: points (big, accent) | time left
    const by = y0 + 66;
    text(ctx, String(pts), x0 + pad, by, "l", 0, 36, "#ffd54a", 0, "", 800);
    const pw = ctx.measureText(String(pts)).width;
    text(ctx, pts === 1 ? "PT" : "PTS", x0 + pad + pw + 6, by, "l", 0, 13, MUTED, 0, "", 700);
    const low = left < 30;
    text(ctx, "LEFT", x0 + pad, by, "r", w - 2 * pad, 11, MUTED, 0, "", 700);
    const lw = ctx.measureText("LEFT").width;
    text(ctx, clockText(left), x0 + pad, by, "r", w - 2 * pad - lw - 6, 22, low ? "#ef6a5b" : "#fff", 0, "", 800);
    // row 3: session progress
    const bw = w - 2 * pad, bar = 5;
    roundRect(ctx, x0 + pad, y0 + 78, bw, bar, bar / 2, "rgba(255,255,255,0.08)");
    if (used > 0) roundRect(ctx, x0 + pad, y0 + 78, Math.max(bar, bw * used), bar, bar / 2, low ? "#ef6a5b" : "#ffd54a");
    // row 4: one dot per round (green = you scored, grey = no goal, red = they scored), the current one hollow; the newest that fit
    const step = 13, r = 4.5, fit = Math.floor((bw + step - 2 * r) / step), shown = R.slice(-(fit - 1)), cy = y0 + 98;
    const col = { W: "#46c98d", D: "#5b6577", L: "#ef6a5b" };
    shown.forEach((rd, i) => { ctx.beginPath(); ctx.arc(x0 + pad + r + i * step, cy, r, 0, 2 * Math.PI); ctx.fillStyle = col[rd.outcome]; ctx.fill(); });
    const pulse = 0.55 + 0.45 * Math.abs(Math.sin(performance.now() / 400));
    ctx.beginPath(); ctx.arc(x0 + pad + r + shown.length * step, cy, r - 0.75, 0, 2 * Math.PI); ctx.lineWidth = 1.5; ctx.strokeStyle = Draw.css(ACC, pulse); ctx.stroke();
    M.pzCard = { x: x0, y: y0, w, h };
  }

  // ---------- the live match ----------
  function play(p) { G.pending = p; go("#/game/match"); }
  function stopMatch() {
    const M = G.match; if (!M) return;
    M.stopped = true; cancelAnimationFrame(M.raf);
    window.removeEventListener("blur", M.onBlur);
    try { M.ws.send(JSON.stringify({ quit: 1 })); } catch (e) {}
    try { M.ws.close(); } catch (e) {}
    G.match = null;
  }
  const KEYS = { ArrowLeft: [-1, 0], KeyA: [-1, 0], ArrowRight: [1, 0], KeyD: [1, 0], ArrowUp: [0, -1], KeyW: [0, -1], ArrowDown: [0, 1], KeyS: [0, 1] };
  function match(p) {
    document.body.classList.add("g-playing");
    const v = mount('<div class="g-match"><canvas></canvas></div>');
    const cv = $("canvas", v);
    const M = G.match = { p, cv, ws: null, meta: null, frames: [], held: new Set(), sentIn: "", paused: false, speed: 1, result: null, error: "", stopped: false,
      cam: null, parts: [], goal: null, lastStep: 0, partAcc: 0, raf: 0, ended: false };
    M.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/match");
    M.ws.onopen = () => M.ws.send(JSON.stringify({ setup: p.setup, puzzle: p.puzzle ?? null }));
    M.ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.k === "m") prepareMeta(M, d);
      else if (d.k === "f") {
        d.at = performance.now();
        M.frames.push(d); if (M.frames.length > 8) M.frames.shift();
        for (const ev of d.ev || []) onGoal(M, ev);
      } else if (d.k === "r") {
        M.result = d.result;
        if (p.session) setTimeout(() => { if (G.match === M && !M.stopped && !M.doneCalled) { M.doneCalled = true; p.done(d.result); } }, 1700);   // puzzle: the next round starts by itself
      }
      else if (d.k === "e") M.error = d.error;
    };
    M.ws.onclose = () => { if (!M.result && !M.stopped && !M.error) M.error = "the connection to the game server closed"; };
    M.onBlur = () => { M.held.clear(); sendInput(M); };
    window.addEventListener("blur", M.onBlur);
    G.keyHandler = (e, down) => onKey(M, e, down);
    const loop = (ts) => { if (M.stopped) return; M.raf = requestAnimationFrame(loop); drawMatch(M, ts); };
    M.raf = requestAnimationFrame(loop);
  }
  function wsSend(M, obj) { try { if (M.ws.readyState === 1) M.ws.send(JSON.stringify(obj)); } catch (e) {} }
  function sendInput(M) {
    let dx = 0, dy = 0;
    for (const k of M.held) if (KEYS[k]) { dx += KEYS[k][0]; dy += KEYS[k][1]; }
    const kick = M.held.has("KeyX") || M.held.has("Space") ? 1 : 0;
    const s = `${Math.sign(dx)},${Math.sign(dy)},${kick}`;
    if (s !== M.sentIn) { M.sentIn = s; wsSend(M, { in: [Math.sign(dx), Math.sign(dy), kick] }); }
  }
  function onKey(M, e, down) {
    const c = e.code;
    if (KEYS[c] || c === "KeyX" || c === "Space") {
      e.preventDefault();
      if (down) M.held.add(c); else M.held.delete(c);
      sendInput(M); return;
    }
    if (!down || e.repeat) return;
    const f = M.frames[M.frames.length - 1], ended = f && f.st === 2 && !M.p.session, ok = c === "Enter" || c === "NumpadEnter";
    if (M.error) { if (ok || c === "Escape") act(M, "quit"); }
    else if (ended) { if ((ok || c === "Escape") && M.result) act(M, "report"); else if (c === "KeyR" && M.p.rematch) act(M, "restart"); }
    else if (c === "Escape" || c === "KeyP") act(M, "pause");
    else if (M.paused && c === "KeyM") act(M, "quit");
    else if (M.paused && c === "KeyR" && !M.p.session) act(M, "restart");
    else if (c === "KeyT") { M.speed = M.speed === 1 ? 2 : M.speed === 2 ? 4 : M.speed === 4 ? 8 : 1; wsSend(M, { speed: M.speed }); }
    else if (c === "KeyQ") wsSend(M, { switch: 1 });
  }
  // what a key or a card button does: pause / resume, restart (same teams, new seed), quit, the report after the final whistle
  function act(M, a) {
    if (a === "pause") { M.paused = !M.paused; wsSend(M, { pause: M.paused }); }
    else if (a === "restart") { const p = { ...M.p, setup: { ...M.p.setup, seed: Math.floor(Math.random() * 2147483647) } }; G.pending = null; stopMatch(); G.pending = p; match(p); }
    else if (a === "quit") { const q = M.p.quit; G.pending = null; stopMatch(); q(); }
    else if (a === "report" && M.result) { const res = M.result, done = M.p.done; G.pending = null; stopMatch(); done(res); }
  }
  // ---------- the cards over the match: pause, full time, error (HTML, so they have real buttons) ----------
  function overlayKind(M, f) {
    if (M.error) return "error";
    if (f && f.st === 2 && !M.p.session) return M.result ? "end" : "wait";
    return M.paused ? "pause" : "";
  }
  function syncOverlay(M, f) {
    const kind = overlayKind(M, f);
    if (kind === M.ovKind) return;
    M.ovKind = kind;
    if (!kind) { if (M.ov) M.ov.hidden = true; return; }
    if (!M.ov) { M.ov = document.createElement("div"); M.ov.className = "mo"; M.cv.parentElement.append(M.ov); }
    const ov = M.ov, m = M.meta;
    ov.hidden = false;
    const k = (x) => `<kbd>${x}</kbd>`;
    if (kind === "error") ov.innerHTML = `<div class="mo-card"><div class="mo-k">The match stopped</div><p class="mo-msg">${esc(M.error)}</p>
      <div class="mo-btns"><button type="button" class="ks-go" data-act="quit">Back ${k("Enter")}</button></div></div>`;
    else if (kind === "pause") ov.innerHTML = `<div class="mo-card"><div class="mo-k">Paused · ${f.ot ? "overtime " + clockText(f.otl) : clockText(f.tl) + " left"}</div>
      <div class="mo-sc small">${esc(m.teams[0].name)} <b>${f.sc[0]} – ${f.sc[1]}</b> ${esc(m.teams[1].name)}</div>
      <div class="mo-btns col"><button type="button" class="ks-go" data-act="pause">Resume ${k("Esc")}</button>
        ${M.p.session ? "" : `<button type="button" class="ks-btn2" data-act="restart">Restart ${k("R")}</button>`}<button type="button" class="ks-btn2" data-act="quit">Quit the match ${k("M")}</button></div>
      <div class="mo-keys"><span>${k("WASD")} ${k("↑↓←→")} move</span><span>${k("Space")} ${k("X")} kick</span>${m.control === 2 ? `<span>${k("Q")} switch player</span>` : ""}<span>${k("T")} speed</span></div></div>`;
    else {
      const res = M.result, w = f.w, ev = res ? res.events : [];
      const verdict = w === -1 ? "Draw" : `${esc(m.teams[w].name)} win${f.so ? ` on penalties ${f.so[0]}–${f.so[1]}` : res?.overtime ? " with a golden goal" : ""}`;
      const goals = (t) => ev.filter((e) => e.team === t).map((e) => `<div>${Math.floor(e.clock / 60) + 1}' ${esc(e.scorer_name)}${e.own ? " (OG)" : ""}</div>`).join("");
      ov.innerHTML = `<div class="mo-card end" style="--c0:#${m.teams[0].kit[0]};--c1:#${m.teams[1].kit[0]}"><div class="mo-k">Full time</div>
        <div class="mo-final"><span class="mo-crest"></span><span class="mo-name r">${esc(m.teams[0].name)}</span><span class="mo-big">${f.sc[0]} – ${f.sc[1]}</span><span class="mo-name">${esc(m.teams[1].name)}</span><span class="mo-crest"></span></div>
        <div class="mo-verdict">${verdict}</div>
        <div class="mo-goals"><div class="r">${goals(0)}</div><div>${goals(1)}</div></div>
        <div class="mo-btns">${res ? `<button type="button" class="ks-go" data-act="report">Match report ${k("Enter")}</button>${M.p.rematch ? `<button type="button" class="ks-btn2" data-act="restart">Rematch ${k("R")}</button>` : ""}` : '<span class="mo-msg">Final whistle…</span>'}</div></div>`;
      ov.querySelectorAll(".mo-crest").forEach((el, t) => el.append(Draw.logoCanvas(m.teams[t].logo, 56)));
    }
    for (const b of ov.querySelectorAll("[data-act]")) { b.addEventListener("mousedown", (e) => e.preventDefault()); b.onclick = () => act(M, b.dataset.act); }
  }
  function prepareMeta(M, m) {
    M.meta = m;
    m.kits = m.teams.map((t) => [Draw.rgb(t.kit[0]), Draw.rgb(t.kit[1])]);
    const P = m.pitch;
    P.cPitch = Draw.rgb(P.pitch); P.cOuter = Draw.rgb(P.outer); P.cLine = Draw.rgb(P.line);
    m.goalCols = m.kits.map((k) => Draw.goalColour(k, P.cPitch));
    m.byUid = {}; m.players.forEach((pl, i) => { pl.i = i; pl.last = pl.name.split(" ")[1] || ""; m.byUid[pl.uid] = pl; });
  }

  // the camera uses the whole window (no HUD strip); TOP = just below the scorebug (the off-screen marker stays under it)
  const BASE_W = 1280, BASE_H = 720, TOP = 64, CAM_ZOOM = 1.15, CAM_SMOOTH = 0.08, INTRO = 130, INTRO_FROM = 0.86;
  let FAMILY = "";
  const FONT = (px, wt = 400) => { if (!FAMILY) FAMILY = getComputedStyle(document.documentElement).getPropertyValue("--g-font").trim() || "sans-serif"; return `${wt} ${px}px ${FAMILY}`; };
  const ACC = [1, 213 / 255, 74 / 255];
  // Godot's draw_string: (x, y) = baseline start; align c / r inside [x, x + w]
  function text(ctx, s, x, y, align, w, px, color, outline = 0, outCol = "rgba(0,0,0,0.9)", wt = 400) {
    ctx.font = FONT(px, wt); ctx.textBaseline = "alphabetic";
    let tx = x;
    if (align === "c") { ctx.textAlign = "center"; tx = x + w / 2; } else if (align === "r") { ctx.textAlign = "right"; tx = x + w; } else ctx.textAlign = "left";
    if (outline) { ctx.lineJoin = "round"; ctx.lineWidth = outline; ctx.strokeStyle = outCol; ctx.strokeText(s, tx, y); }
    ctx.fillStyle = color; ctx.fillText(s, tx, y);
  }
  const clockText = (s) => { s = Math.max(0, Math.floor(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

  function onGoal(M, ev) {
    const m = M.meta; if (!m) return;
    const team = ev.team, col = Draw.lightened(m.kits[team][0], 0.15);
    M.goal = { name: m.teams[team].name.toUpperCase(), scorer: ev.scorer_name, own: ev.own, col };
    M.parts = [];
    const W = M.size ? M.size[0] : BASE_W, H = M.size ? M.size[1] : BASE_H, cx = W / 2, cy = H / 2 + 5;
    const pal = [ACC, [1, 1, 1], col, Draw.lightened(col, 0.4)];
    const R = (a, b) => a + Math.random() * (b - a);
    for (let i = 0; i < 120; i++) {
      const a = Math.random() * 2 * Math.PI, sp = R(3, 16);
      M.parts.push({ x: cx + R(-120, 120), y: cy, vx: Math.cos(a) * sp * 1.4, vy: Math.sin(a) * sp * 0.8 - 3, life: Math.floor(R(70, 151)), age: 0, col: pal[i % 4], sz: R(3, 7), rot: Math.random() * 6.283, spin: R(-0.4, 0.4), grav: 0.22, kind: 0 });
    }
    for (let i = 0; i < 70; i++)
      M.parts.push({ x: R(0, W), y: -R(10, 400), vx: R(-1, 1), vy: R(2, 4.5), life: Math.floor(R(120, 191)), age: 0, col: pal[i % 4], sz: R(4, 8), rot: Math.random() * 6.283, spin: R(-0.2, 0.2), grav: 0, kind: 0 });
  }
  function stepParticles(M, f) {
    const P = M.parts;
    for (let i = P.length - 1; i >= 0; i--) {
      const q = P[i]; q.age += 1;
      if (q.age >= q.life) { P.splice(i, 1); continue; }
      q.x += q.vx; q.y += q.vy; q.vx *= 0.975; q.vy = q.vy * 0.985 + q.grav; q.rot += q.spin;
    }
    if (f && f.st === 1) {                                     // sparks out of the banner edges while the word is on screen
      const age = f.gp - f.gtm;
      if (age > 8 && age < 70 && age % 2 === 0)
        for (const sgn of [-1, 1]) P.push({ x: M.size[0] / 2 + sgn * (60 + Math.random() * 200), y: M.size[1] / 2 + 5, vx: sgn * (1 + Math.random() * 4), vy: -7 + Math.random() * 5,
          life: Math.floor(30 + Math.random() * 26), age: 0, col: ACC, sz: 2 + Math.random() * 2, rot: 0, spin: 0, grav: 0.25, kind: 1 });
    }
  }
  function drawParticles(ctx, M) {
    for (const q of M.parts) {
      const a = Math.max(0, Math.min(1, 1 - q.age / q.life)), col = Draw.css(q.col, Math.min(1, a * 2));
      ctx.fillStyle = col;
      if (q.kind === 1) { ctx.beginPath(); ctx.arc(q.x, q.y, q.sz * a + 0.5, 0, 2 * Math.PI); ctx.fill(); }
      else { ctx.save(); ctx.translate(q.x, q.y); ctx.rotate(q.rot); ctx.scale(1, Math.abs(Math.cos(q.rot * 0.7)) * 0.8 + 0.2); ctx.fillRect(-q.sz, -q.sz * 0.5, q.sz * 2, q.sz); ctx.restore(); }
    }
  }

  function drawMatch(M, ts) {
    const cv = M.cv, dpr = window.devicePixelRatio || 1, cw = cv.clientWidth, ch = cv.clientHeight;
    if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) { cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr); }
    const u = Math.min(cw / BASE_W, ch / BASE_H), W = cw / u, H = ch / u;     // Godot's "canvas_items / expand" stretch: a 1280x720 base, extended
    M.size = [W, H];
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr * u, 0, 0, dpr * u, 0, 0);
    ctx.fillStyle = "#0b0e13"; ctx.fillRect(0, 0, W, H);
    const m = M.meta, fr = M.frames;
    if (!m || !fr.length) {
      if (!M.error) text(ctx, "Starting the match…", 0, H / 2, "c", W, 22, "#8d98ab");
      syncOverlay(M, null);
      return;
    }
    // positions: interpolated between the two frames around (now - one tick), so the 60 Hz stream looks smooth at any refresh rate
    const rt = performance.now() - 20;
    let a = fr[fr.length - 1], b = a, k = 0;
    for (let i = fr.length - 1; i > 0; i--) if (fr[i - 1].at <= rt) { a = fr[i - 1]; b = fr[i]; k = Math.min(1, Math.max(0, (rt - a.at) / Math.max(b.at - a.at, 1))); break; }
    if (b.t < a.t || a.p.length !== b.p.length) { a = b; k = 0; }
    const L = (x, y) => x + (y - x) * k, f = b;
    // particles and camera move at the game's 60 Hz
    const dt = M.lastStep ? Math.min(0.25, (ts - M.lastStep) / 1000) : 0; M.lastStep = ts;
    if (!M.paused) { M.partAcc += dt * 60; while (M.partAcc >= 1) { M.partAcc -= 1; stepParticles(M, f); } }
    const intro = f.in || 0;
    const zoomMul = intro > 0 ? (() => { const q = 1 - intro / INTRO; return INTRO_FROM + (1 - INTRO_FROM) * (1 - Math.pow(1 - q, 3)); })() : 1;
    const zoom = CAM_ZOOM * zoomMul, P = m.pitch;
    const ball = [L(a.b[0], b.b[0]), L(a.b[1], b.b[1])];
    if (!M.cam || intro > 0) M.cam = ball.slice();
    else if (!M.paused) { const s = 1 - Math.pow(1 - CAM_SMOOTH, dt * 60); M.cam[0] += (ball[0] - M.cam[0]) * s; M.cam[1] += (ball[1] - M.cam[1]) * s; }
    const centre = [W / 2, H / 2], half = [W / 2 / zoom, H / 2 / zoom], bound = [P.out_x + 8, P.out_y + 4];
    const cam = [half[0] >= bound[0] ? 0 : Math.max(-bound[0] + half[0], Math.min(bound[0] - half[0], M.cam[0])),
      half[1] >= bound[1] ? 0 : Math.max(-bound[1] + half[1], Math.min(bound[1] - half[1], M.cam[1]))];
    ctx.save();
    ctx.translate(centre[0] - cam[0] * zoom, centre[1] - cam[1] * zoom); ctx.scale(zoom, zoom);
    drawPitch(ctx, m);
    drawPlayers(ctx, M, m, a, b, L, f);
    drawNets(ctx, m);
    ctx.restore();
    if (M.me) drawOffscreen(ctx, M, m, [centre[0] + (M.me.x - cam[0]) * zoom, centre[1] + (M.me.y - cam[1]) * zoom], W, H);
    drawHud(ctx, M, m, f, W, H, intro);
    syncOverlay(M, f);
  }
  function drawPitch(ctx, m) {
    const P = m.pitch, hw = P.half_w, hh = P.half_h, C = Draw.css;
    ctx.fillStyle = C(Draw.darkened(P.cOuter, 0.25)); ctx.fillRect(-2000, -1200, 4000, 2400);
    ctx.fillStyle = C(P.cOuter); ctx.fillRect(-P.out_x, -P.out_y, 2 * P.out_x, 2 * P.out_y);
    const n = Math.max(P.stripes, 1), sw = (2 * hw) / n;
    for (let i = 0; i < n; i++) { ctx.fillStyle = C(P.stripes > 0 && i % 2 === 0 ? Draw.darkened(P.cPitch, 0.07) : P.cPitch); ctx.fillRect(-hw + i * sw, -hh, sw + 0.4, 2 * hh); }
    for (let t = 0; t < 2; t++) {                              // goal floor and goal line; the net goes on top later (drawNets)
      const sx = t === 0 ? -1 : 1, col = m.goalCols[t], x0 = sx * hw, x1 = sx * (hw + P.net_depth), gh = P.goal_half;
      ctx.fillStyle = C(Draw.darkened(P.cPitch, 0.2)); ctx.fillRect(Math.min(x0, x1), -gh, P.net_depth, 2 * gh);
      ctx.beginPath(); ctx.moveTo(x0, -gh); ctx.lineTo(x0, gh);
      ctx.lineWidth = 7.5; ctx.strokeStyle = "rgba(0,0,0,0.75)"; ctx.stroke(); ctx.lineWidth = 4; ctx.strokeStyle = C(col); ctx.stroke();
    }
    const lc = C(P.cLine);
    ctx.strokeStyle = lc; ctx.lineWidth = 3; ctx.strokeRect(-hw, -hh, 2 * hw, 2 * hh);
    ctx.beginPath(); ctx.moveTo(0, -hh); ctx.lineTo(0, hh); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, 0, P.center_r, 0, 2 * Math.PI); ctx.stroke();
    ctx.fillStyle = lc; ctx.beginPath(); ctx.arc(0, 0, 4, 0, 2 * Math.PI); ctx.fill();
    if (P.box_depth > 0) { ctx.lineWidth = 2.5; ctx.strokeRect(-hw, -P.box_half, P.box_depth, 2 * P.box_half); ctx.strokeRect(hw - P.box_depth, -P.box_half, P.box_depth, 2 * P.box_half); }
  }
  function drawNets(ctx, m) {                                   // nets in the colour of the team defending them, over the ball and players
    const P = m.pitch, hw = P.half_w, C = Draw.css;
    for (let t = 0; t < 2; t++) {
      const sx = t === 0 ? -1 : 1, col = m.goalCols[t], x0 = sx * hw, x1 = sx * (hw + P.net_depth), gh = P.goal_half;
      ctx.strokeStyle = C(col, 0.55); ctx.lineWidth = 1; ctx.beginPath();
      for (let g = 0; g <= P.net_depth; g += 10) { ctx.moveTo(x0 + sx * g, -gh); ctx.lineTo(x0 + sx * g, gh); }
      for (let g = -gh; g <= gh; g += 10) { ctx.moveTo(x0, g); ctx.lineTo(x1, g); }
      ctx.stroke();
      const frame = () => { ctx.beginPath(); ctx.moveTo(x0, -gh); ctx.lineTo(x1, -gh); ctx.lineTo(x1, gh); ctx.lineTo(x0, gh); };
      ctx.lineJoin = "miter";
      frame(); ctx.lineWidth = 6.5; ctx.strokeStyle = "rgba(0,0,0,0.75)"; ctx.stroke();
      frame(); ctx.lineWidth = 3; ctx.strokeStyle = C(col); ctx.stroke();
    }
    for (const [x, y, r] of P.statics) {                        // posts and obstacles
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fillStyle = "#f2f2f2"; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.stroke();
    }
  }
  function drawPlayers(ctx, M, m, a, b, L, f) {
    M.me = null;
    m.players.forEach((pl, i) => {
      if (2 * i + 1 >= b.p.length) return;
      const x = L(a.p[2 * i], b.p[2 * i]), y = L(a.p[2 * i + 1], b.p[2 * i + 1]), r = pl.r, fl = b.h[i] || 0, kit = m.teams[pl.team];
      if (fl & 1) {                                             // you: a translucent yellow ring around the player (off screen: drawOffscreen)
        M.me = { x, y, pl };
        ctx.beginPath(); ctx.arc(x, y, r + 6, 0, 2 * Math.PI); ctx.lineWidth = 3; ctx.strokeStyle = "rgba(255,213,74,0.5)"; ctx.stroke();
      }
      Draw.kit(ctx, x, y, r, "#" + kit.kit[0], "#" + kit.kit[1], kit.pattern);
      ctx.beginPath(); ctx.arc(x, y, r - 1, 0, 2 * Math.PI); ctx.lineWidth = 2.5; ctx.strokeStyle = fl & 2 && !(fl & 4) ? "#fff" : "#000"; ctx.stroke();
      text(ctx, String(pl.number), x - r, y + 5.5, "c", 2 * r, 14, "#fff", 5);
    });
    if (f.st === 1 && f.gs >= 0 && m.byUid[f.gs]) {             // celebration: pulsing rings and confetti around the scorer
      const sc = m.byUid[f.gs], i = sc.i, x = L(a.p[2 * i], b.p[2 * i]), y = L(a.p[2 * i + 1], b.p[2 * i + 1]);
      const age = f.gp - f.gtm, col = Draw.lightened(m.kits[sc.team][0], 0.35);
      for (let k = 0; k < 2; k++) {
        const ph = (age * 0.025 + k * 0.5) % 1;
        ctx.beginPath(); ctx.arc(x, y, sc.r + 6 + ph * 60, 0, 2 * Math.PI); ctx.lineWidth = 3; ctx.strokeStyle = Draw.css(col, 0.7 * (1 - ph)); ctx.stroke();
      }
      const pal = [ACC, [1, 1, 1], col];
      for (let j = 0; j < 24; j++) {
        const ang = j * 2.399 + 0.5, spd = 0.9 + 0.5 * ((j * 0.37) % 1), t = Math.min(age, 70);
        ctx.beginPath(); ctx.arc(x + Math.cos(ang) * (sc.r + t * spd), y + Math.sin(ang) * (sc.r + t * spd) + 0.012 * t * t, 3, 0, 2 * Math.PI);
        ctx.fillStyle = Draw.css(pal[j % 3], Math.max(0, Math.min(1, 1 - age / 110))); ctx.fill();
      }
    }
    const bx = L(a.b[0], b.b[0]), by = L(a.b[1], b.b[1]), br = m.ball_r;
    ctx.beginPath(); ctx.arc(bx, by, br, 0, 2 * Math.PI); ctx.fillStyle = "#fff"; ctx.fill();
    ctx.beginPath(); ctx.arc(bx, by, br - 1, 0, 2 * Math.PI); ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.stroke();
  }
  // you cannot be seen (off screen, on its very edge, or under the scorebug): an arrow on the window edge pointing at you, with your number
  function drawOffscreen(ctx, M, m, sp, W, H) {
    const pad = 30, top = TOP + 10, e = 12, b = M.bug, c = M.pzCard;
    const under = (q) => q && sp[0] > q.x - 14 && sp[0] < q.x + q.w + 14 && sp[1] < q.y + q.h + 14;
    if (sp[0] >= e && sp[0] <= W - e && sp[1] >= e && sp[1] <= H - e && !under(b) && !under(c)) return;
    const cx = W / 2, cy = H / 2, dx = sp[0] - cx, dy = sp[1] - cy;
    const k = Math.min(Math.abs((W / 2 - pad) / (dx || 1e-6)), Math.abs((H / 2 - pad) / (dy || 1e-6)));
    const x = cx + dx * k, y = Math.max(c && x > c.x - 30 ? c.y + c.h + 27 : top, cy + dy * k), ang = Math.atan2(dy, dx);
    ctx.save(); ctx.translate(x, y);
    ctx.beginPath(); ctx.arc(0, 0, 17, 0, 2 * Math.PI); ctx.fillStyle = "rgba(11,14,19,0.85)"; ctx.fill(); ctx.lineWidth = 2.5; ctx.strokeStyle = "#ffd54a"; ctx.stroke();
    ctx.rotate(ang);
    ctx.beginPath(); ctx.moveTo(27, 0); ctx.lineTo(18, -8); ctx.lineTo(18, 8); ctx.closePath(); ctx.fillStyle = "#ffd54a"; ctx.fill();
    ctx.restore();
    text(ctx, String(M.me.pl.number), x - 17, y + 5.5, "c", 34, 15, "#ffd54a", 0, "", 700);
  }
  function roundRect(ctx, x, y, w, h, r, fill) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fillStyle = fill; ctx.fill(); }
  // the TV scorebug, top left: crest CODE | score | CODE crest | clock
  function drawScorebug(ctx, M, m, f) {
    const x0 = 16, y0 = 14, h = 38, pad = 12, crest = 13, bar = 5;
    ctx.font = FONT(15, 700);
    const codes = m.teams.map((t) => (t.short || t.name.slice(0, 3)).toUpperCase());
    const cw = codes.map((c) => ctx.measureText(c).width);
    ctx.font = FONT(20, 800);
    const score = `${f.sc[0]} – ${f.sc[1]}`, sw = ctx.measureText(score).width;
    const clock = f.ot ? "OT " + clockText(f.otl) : clockText(f.tl);
    ctx.font = FONT(15, 700);
    const kw = ctx.measureText(clock).width;
    const segT = (i) => pad + crest * 2 + 8 + cw[i] + pad;
    const total = segT(0) + bar + sw + 2 * pad + bar + segT(1) + kw + 2 * pad;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)"; ctx.shadowBlur = 14; ctx.shadowOffsetY = 4;
    roundRect(ctx, x0, y0, total, h, 9, "#12161d");
    ctx.restore();
    ctx.save(); ctx.beginPath(); ctx.roundRect(x0, y0, total, h, 9); ctx.clip();
    let x = x0;
    // home: crest, code, colour bar
    Draw.logo(ctx, x + pad + crest, y0 + h / 2, crest, m.teams[0].logo);
    text(ctx, codes[0], x + pad + crest * 2 + 8, y0 + 25, "l", 0, 15, "#fff", 0, "", 700);
    x += segT(0);
    ctx.fillStyle = Draw.css(m.kits[0][0]); ctx.fillRect(x, y0, bar, h); x += bar;
    ctx.fillStyle = "#0b0e13"; ctx.fillRect(x, y0, sw + 2 * pad, h);
    text(ctx, score, x, y0 + 27, "c", sw + 2 * pad, 20, "#fff", 0, "", 800); x += sw + 2 * pad;
    ctx.fillStyle = Draw.css(m.kits[1][0]); ctx.fillRect(x, y0, bar, h); x += bar;
    text(ctx, codes[1], x + pad, y0 + 25, "l", 0, 15, "#fff", 0, "", 700);
    Draw.logo(ctx, x + pad + cw[1] + 8 + crest, y0 + h / 2, crest, m.teams[1].logo);
    x += segT(1);
    ctx.fillStyle = f.ot ? "#ef6a5b" : "#ffd54a"; ctx.fillRect(x, y0, kw + 2 * pad, h);
    text(ctx, clock, x, y0 + 25, "c", kw + 2 * pad, 15, "#12161d", 0, "", 700);
    ctx.restore();
    M.bug = { x: x0, y: y0, w: total, h };
    // chips to the right of the bug: recording, speed
    let cxp = x0 + total + 8;
    const cyc = y0 + h / 2;
    const chip = (label, col, dot) => {
      ctx.font = FONT(12, 700); const w = ctx.measureText(label).width + (dot ? 30 : 20);
      roundRect(ctx, cxp, cyc - 11, w, 22, 11, "rgba(11,14,19,0.75)");
      if (dot) { ctx.beginPath(); ctx.arc(cxp + 12, cyc, 4, 0, 2 * Math.PI); ctx.fillStyle = dot; ctx.fill(); }
      text(ctx, label, cxp + (dot ? 21 : 10), cyc + 4, "l", 0, 12, col, 0, "", 700);
      cxp += w + 6;
    };
    if (m.rec && f.cu >= 0 && f.st !== 2) chip("REC", "#ef6a5b", Math.floor(performance.now() / 700) % 2 ? "#ef6a5b" : "#b8463b");
    if (M.speed > 1) chip(`×${M.speed}`, "#ffd54a");
  }
  function drawHud(ctx, M, m, f, W, H, intro) {
    if (f.st === 1) drawGoalBanner(ctx, M, f, W, H);
    else if (intro > 0 && !M.p.session && f.st !== 2) drawKickoff(ctx, m, f, W, H, intro);
    drawParticles(ctx, M);
    drawScorebug(ctx, M, m, f);
    if (M.p.session && !M.error) drawPuzzleHud(ctx, M, f, W, H, intro);
  }
  function drawKickoff(ctx, m, f, W, H, intro) {
    const k = 1 - intro / INTRO, a = Math.max(0, Math.min(1, k / 0.15)) * Math.max(0, Math.min(1, (1 - k) / 0.2));
    if (a <= 0) return;
    const col = m.kits[f.kt][0], name = m.teams[f.kt].name, w = 300, h = 74, x = W / 2 - w / 2, y = H / 2 - 230 + (1 - a) * -12;
    ctx.save(); ctx.globalAlpha = a;
    ctx.shadowColor = "rgba(0,0,0,0.4)"; ctx.shadowBlur = 20; ctx.shadowOffsetY = 6;
    roundRect(ctx, x, y, w, h, 12, "rgba(11,14,19,0.88)");
    ctx.shadowColor = "transparent";
    ctx.save(); ctx.beginPath(); ctx.roundRect(x, y, w, h, 12); ctx.clip(); ctx.fillStyle = Draw.css(col); ctx.fillRect(x, y, w, 5); ctx.restore();
    Draw.logo(ctx, x + 38, y + h / 2 + 2, 20, m.teams[f.kt].logo);
    text(ctx, "KICK OFF", x + 70, y + 38, "l", 0, 26, "#fff", 0, "", 800);
    text(ctx, name, x + 70, y + 59, "l", 0, 14, Draw.css(Draw.lightened(col, 0.35)), 0, "", 600);
    ctx.restore();
  }
  const easeOutBack = (t) => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
  // "GOAL" in big letters that pop in one by one, an accent band, team + scorer lines underneath
  function drawGoalBanner(ctx, M, f, W, H) {
    const g = M.goal || { name: "", scorer: "", own: false, col: [1, 1, 1] };
    const age = f.gp - f.gtm, fade = Math.max(0, Math.min(1, f.gtm / 22)), cy = H / 2 + 5, col = g.col;
    let open = Math.max(0, Math.min(1, age / 12)); open = 1 - Math.pow(1 - open, 3);
    const hh = 92 * open;
    ctx.fillStyle = `rgba(11,14,19,${0.72 * fade})`; ctx.fillRect(0, cy - hh, W, hh * 2);
    ctx.fillStyle = Draw.css(col, fade); ctx.fillRect(0, cy - hh - 5, W, 5); ctx.fillRect(0, cy + hh, W, 5);
    const sw = Math.max(0, Math.min(1, (age - 4) / 40));
    if (sw > 0 && sw < 1) {
      const sx = -200 + (W + 400) * sw;
      ctx.fillStyle = `rgba(255,255,255,${0.16 * fade})`;
      Draw.path(ctx, [[sx - 40, cy - hh], [sx + 20, cy - hh], [sx - 10, cy + hh], [sx - 70, cy + hh]]); ctx.fill();
    }
    const word = "GOAL", fs = 100, track = 8;
    ctx.font = FONT(fs, 800);
    const widths = [...word].map((ch) => ctx.measureText(ch).width);
    const total = widths.reduce((s, w) => s + w + track, 0) - track;
    let x = W / 2 - total / 2;
    const baseY = cy - 6;
    for (let i = 0; i < word.length; i++) {
      const t = Math.max(0, Math.min(1, (age - 6 - i * 4) / 16));
      if (t > 0) {
        const sc = easeOutBack(t), drop = (1 - t) * -50, wob = Math.sin(age * 0.12 + i) * 2 * t;
        ctx.save(); ctx.translate(x + widths[i] / 2, baseY - fs * 0.3 + drop + wob); ctx.scale(sc, sc);
        const ox = -widths[i] / 2, oy = fs * 0.3;
        text(ctx, word[i], ox + 4, oy + 5, "l", 0, fs, `rgba(0,0,0,${0.55 * fade})`, 0, "", 800);
        const fill = Draw.mix([1, 1, 1], col, Math.max(0, Math.min(0.45, (age - 30) / 30)));
        text(ctx, word[i], ox, oy, "l", 0, fs, Draw.css(fill, fade * t), 10, `rgba(0,0,0,${fade * t})`, 800);
        ctx.restore();
      }
      x += widths[i] + track;
    }
    const ul = Math.max(0, Math.min(1, (age - 24) / 14));
    if (ul > 0) { ctx.fillStyle = Draw.css(col, fade); ctx.fillRect(W / 2 - (total * ul) / 2, cy + 12, total * ul, 4); }
    const ta = Math.max(0, Math.min(1, (age - 28) / 12));
    if (ta > 0) {
      text(ctx, g.name, 0, cy + 44 + (1 - ta) * 18, "c", W, 24, Draw.css(Draw.lightened(col, 0.25), ta * fade), 0, "", 700);
      if (g.scorer) {
        const sa = Math.max(0, Math.min(1, (age - 36) / 12));
        text(ctx, g.scorer + (g.own ? "  (own goal)" : ""), 0, cy + 74 + (1 - sa) * 18, "c", W, 19, `rgba(255,255,255,${sa * fade})`, 0, "", 600);
      }
    }
  }

  return { show, stopMatch, state: () => G, redraw: () => G.match && drawMatch(G.match, performance.now()) };   // state, redraw: for tests
})();
