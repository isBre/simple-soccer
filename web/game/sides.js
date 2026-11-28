// The Game (web/game.js has the overview): local multiplayer, who plays which side. The quick match shows it before the kickoff
// when a controller is connected. Every device (the keyboard, each controller) is a card that sits on the home side, in the
// middle (not playing) or on the away side, and says what it controls there:
//   Whole team   switch with Q / LB / RB (only for someone alone on a side)
//   Any player   one player for the whole match, the most advanced spot still free
//   #N name      that player of the line-up, for the whole match
// A side with two or more people plays one player each, never the same one (soccer/core/match.py check_humans). Every device moves its
// own card: ← → (stick, D-pad, arrows, A / D) side, ↑ ↓ (W / S) what it controls; Enter / A / Start kick off, Esc / B back.
// The places are remembered in this browser (prefs.devices). Nobody on a side: watch the match.
import { G, esc, prefs, savePrefs } from "./core.js";
import { HUMAN_COLORS, devName, devOfEvent } from "./match.js";

const HOME = 0, MID = 1, AWAY = 2;
const padDevs = () => [...(navigator.getGamepads?.() || [])].filter((g) => g && g.connected).map((g) => "pad:" + g.index);
const DIRS = { ArrowLeft: [-1, 0], KeyA: [-1, 0], ArrowRight: [1, 0], KeyD: [1, 0], ArrowUp: [0, -1], KeyW: [0, -1], ArrowDown: [0, 1], KeyS: [0, 1] };

// home, away: catalog teams; size: players per side; control: the quick match's Control ("single" | "team" | "none"), the default
// of a device seen for the first time. onGo(humans, devices): the setup's "humans" and the device of each, in the same order.
export function pickSides({ home, away, size, control, onGo, onBack }) {
  const teams = [home, away];
  const lineup = (t) => (t.lineup_for?.[String(size)] || []).map((id) => G.playerById[id]?.name || id);
  const names = [lineup(home), lineup(away)];
  const st = {};                                       // device -> {col: HOME | MID | AWAY, pick: "team" | "auto" | slot}
  let devs = [];
  const side = (d) => (st[d].col === HOME ? 0 : st[d].col === AWAY ? 1 : -1);
  const on = (t) => devs.filter((d) => side(d) === t);
  const playing = () => devs.filter((d) => side(d) >= 0);
  function refresh() {                                 // the devices now connected; a new one starts where it was last time
    devs = ["kb", ...padDevs()];
    for (const d of devs) if (!st[d]) {
      const saved = prefs.devices?.[d];
      st[d] = saved && [HOME, MID, AWAY].includes(saved.col) ? { col: saved.col, pick: saved.pick }
        : { col: d === "kb" && control !== "none" ? HOME : MID, pick: control === "team" ? "team" : "auto" };
    }
    fix();
  }
  function options(d) {                                // what device d can control on its side
    const t = side(d); if (t < 0) return [];
    const others = on(t).filter((x) => x !== d);
    const taken = new Set(others.map((x) => st[x].pick).filter((p) => typeof p === "number"));
    return [...(others.length ? [] : ["team"]), "auto", ...names[t].map((_, k) => k).filter((k) => !taken.has(k))];
  }
  function fix() {                                     // keep the rules: nobody controls a whole shared side, no slot twice
    for (const t of [0, 1]) {
      const seen = new Set(), mine = on(t);
      for (const d of mine) {
        const p = st[d].pick;
        if (p === "team" && mine.length > 1) st[d].pick = "auto";
        else if (typeof p === "number" && (seen.has(p) || p >= size)) st[d].pick = "auto";
        if (typeof st[d].pick === "number") seen.add(st[d].pick);
      }
    }
  }
  const o = document.createElement("div");
  o.className = "g-overlay sd";
  document.body.append(o);
  const prevKeys = G.keyHandler;
  let flash = null;
  const pickText = (d) => {
    const p = st[d].pick, t = side(d);
    if (t < 0) return "Watching";
    if (p === "team") return "Whole team";
    if (p === "auto") return "Any player";
    return `#${p + 1} ${names[t][p] || ""}`;
  };
  function paint() {
    const pl = playing();
    const card = (d) => {
      const k = pl.indexOf(d), col = k >= 0 ? HUMAN_COLORS[k % 4] : "var(--g-muted)", c = st[d].col;
      return `<div class="sd-card${d === flash ? " no" : ""}" data-dev="${d}" style="--hc:${col}">
        <div class="sd-dev"><b>${k >= 0 ? "P" + (k + 1) : "–"}</b><span>${esc(devName(d))}</span></div>
        <div class="sd-pick"><button type="button" class="sd-a" data-d="${d}" data-m="-1" aria-label="Move left"${c === HOME ? " disabled" : ""}>‹</button>
          <button type="button" class="sd-what" data-d="${d}"${c === MID ? " disabled" : ""} title="What you control (↑ ↓)">${esc(pickText(d))}</button>
          <button type="button" class="sd-a" data-d="${d}" data-m="1" aria-label="Move right"${c === AWAY ? " disabled" : ""}>›</button></div></div>`;
    };
    const head = (t) => `<div class="sd-team"><span class="sd-crest" data-t="${t}"></span><div><div class="sd-name">${esc(teams[t].name)}</div>
      <div class="sd-role">${t ? "Away" : "Home"} · ${on(t).length ? on(t).length + (on(t).length > 1 ? " people, one player each" : " person") : "AI"}</div></div></div>`;
    const n = pl.length;
    o.innerHTML = `<div class="sd-box"><div class="sd-title">Who plays where</div>
      <div class="sd-cols"><div class="sd-col">${head(0)}${devs.filter((d) => st[d].col === HOME).map(card).join("")}</div>
        <div class="sd-col mid"><div class="sd-team"><div><div class="sd-name">Not playing</div><div class="sd-role">${size}v${size}</div></div></div>${devs.filter((d) => st[d].col === MID).map(card).join("")}</div>
        <div class="sd-col">${head(1)}${devs.filter((d) => st[d].col === AWAY).map(card).join("")}</div></div>
      <div class="sd-keys"><span><kbd>← →</kbd> side</span><span><kbd>↑ ↓</kbd> whole team / one player</span><span><kbd>Enter</kbd> <kbd>A</kbd> kick off</span><span><kbd>Esc</kbd> <kbd>B</kbd> back</span>
        <span class="sd-note">Every device moves its own card. Two people on one side control one player each.</span></div>
      <div class="sd-btns"><button type="button" class="ks-btn2" data-act="back">Back</button><button type="button" class="ks-go" data-act="go">${n ? "Kick off" : "Watch"}</button></div></div>`;
    for (const el of o.querySelectorAll(".sd-crest")) el.append(Draw.logoCanvas(teams[Number(el.dataset.t)].logo, 44));
    for (const b of o.querySelectorAll("button")) b.addEventListener("mousedown", (e) => e.preventDefault());
    for (const b of o.querySelectorAll(".sd-a")) b.onclick = () => move(b.dataset.d, Number(b.dataset.m));
    for (const b of o.querySelectorAll(".sd-what")) b.onclick = () => cycle(b.dataset.d, 1);
    o.querySelector('[data-act="back"]').onclick = back;
    o.querySelector('[data-act="go"]').onclick = start;
  }
  function move(d, dir) {
    const c = Math.max(HOME, Math.min(AWAY, st[d].col + dir));
    if (c === st[d].col) return;
    if (c !== MID && on(c === HOME ? 0 : 1).length >= size) {        // a side has room for `size` people
      flash = d; paint(); setTimeout(() => { if (flash === d) { flash = null; paint(); } }, 350); return;
    }
    st[d].col = c;
    if (c !== MID && on(c === HOME ? 0 : 1).length > 1 && st[d].pick === "team") st[d].pick = "auto";
    fix(); save(); Sound.ui("move"); paint();
  }
  function cycle(d, dir) {
    const opts = options(d); if (!opts.length) return;
    const k = opts.indexOf(st[d].pick);
    st[d].pick = opts[((k < 0 ? 0 : k + dir) + opts.length) % opts.length];
    save(); Sound.ui("move"); paint();
  }
  function save() { prefs.devices = { ...(prefs.devices || {}), ...Object.fromEntries(devs.map((d) => [d, st[d]])) }; savePrefs(); }
  function close() {
    o.remove();
    window.removeEventListener("gamepadconnected", onPads); window.removeEventListener("gamepaddisconnected", onPads);
    G.keyHandler = prevKeys;
  }
  function back() { close(); onBack?.(); }
  function start() {
    fix();
    const pl = playing();
    const humans = pl.map((d) => {
      const p = st[d].pick;
      return { team: side(d), control: p === "team" ? "team" : "single", player: typeof p === "number" ? String(p) : "" };
    });
    close(); onGo(humans, pl);
  }
  const onPads = () => { if (!o.isConnected) return close(); refresh(); paint(); };
  window.addEventListener("gamepadconnected", onPads); window.addEventListener("gamepaddisconnected", onPads);
  G.keyHandler = (e, down) => {
    if (!o.isConnected) { G.keyHandler = prevKeys; return; }
    if (!down) return;
    const d = devOfEvent(e), dir = DIRS[e.code] || DIRS[e.key];
    if (dir && st[d]) {
      e.preventDefault();
      if (e.repeat) return;
      if (dir[0]) move(d, dir[0]); else cycle(d, dir[1]);
    } else if (e.repeat) return;
    else if (e.key === "Enter") { e.preventDefault(); start(); }
    else if (e.key === "Escape") { e.preventDefault(); back(); }
  };
  refresh(); paint();
  return { close };
}
