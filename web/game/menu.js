// The Game (web/game.js has the overview): the main menu (a real match plays behind it).
import { $, G, esc, loadT, mount, prefs } from "./core.js";
import { match, play, prepareMeta } from "./match.js";
import { clockText, drawMatch, drawNets, drawPitch, drawPlayers } from "./render.js";
import { teams } from "./teams.js";

// ---------- main menu: a title screen. Behind it a real match plays between the two teams of your last quick match (showcase());
// Quick match leads, then the other pages; every crest along the bottom opens its team.
// Keys: Up / Down move, Enter opens, 1-9 jump to an entry.
export const ICON = {
  resume: '<path d="M7 5v14l12-7z"/>',
  puzzle: '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.6 2M9.5 2.5h5M12 2.5V6"/>',
  trophy: '<path d="M8 21h8M12 16.5V21M7 3.5h10V9a5 5 0 0 1-10 0zM7 5.5H4V7a3 3 0 0 0 3 3M17 5.5h3V7a3 3 0 0 1-3 3"/>',
  shield: '<path d="M12 3l8 3v6c0 4.8-3.4 8-8 9-4.6-1-8-4.2-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
export const icon = (k, px = 22) => `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;
export function menu() {
  const C = G.cat, save = loadT();
  const last = (prefs.sides || []).map((id) => G.byId[id]).filter(Boolean);
  const pair = last.length === 2 && last[0].id !== last[1].id ? last : (() => {
    const a = C.teams[Math.floor(Math.random() * C.teams.length)];
    const rest = C.teams.filter((t) => t.id !== a.id && Draw.dist(Draw.rgb(t.colors[0]), Draw.rgb(a.colors[0])) > 0.45);
    return [a, rest[Math.floor(Math.random() * rest.length)] || C.teams.find((t) => t.id !== a.id)];
  })();
  const vs = `<span class="gm-vs">${Draw.logoTag(pair[0].id, 18)}<span>${esc(pair[0].name)}</span><i>vs</i><span>${esc(pair[1].name)}</span>${Draw.logoTag(pair[1].id, 18)}</span>`;
  const items = (save ? [["resume", "Continue tournament", "#/game/tournament", save.title || "Your saved tournament"]] : [])
    .concat([["puzzle", "Puzzle", "#/game/puzzle", "One-minute rounds from random positions"],
      ["trophy", "New tournament", "#/game/tournament/new", "One league or all of them"],
      ["shield", "Teams and players", "#/game/teams", `${C.teams.length} teams in ${C.leagues.length} leagues`]]);
  const ranked = C.teams.slice().sort((a, b) => (b.elo || 0) - (a.elo || 0));
  const crests = ranked.map((t) => `<a href="#/game/teams/${encodeURIComponent(t.id)}" title="${esc(t.name)}${t.elo ? " · Elo " + t.elo : ""}" tabindex="-1">${Draw.logoTag(t.id, 34)}</a>`).join("");
  const bug = (t) => `${Draw.logoTag(t.id, 20)}<b>${esc(t.short || t.name.slice(0, 3).toUpperCase())}</b>`;
  const v = mount(`<div class="gm">
    <div class="gm-stage" aria-hidden="true"><canvas class="gm-pitch"></canvas></div><div class="gm-shade" aria-hidden="true"></div>
    <div class="gm-bug" aria-hidden="true" hidden><span class="gm-bug-l">Live</span>${bug(pair[0])}<span class="gm-score" id="gm-score">0 – 0</span>${bug(pair[1])}<span class="gm-clock" id="gm-clock"></span></div>
    <div class="gm-in">
      <div class="gm-kicker">5-a-side football</div>
      <h1 class="gm-title"><span>Simple</span><span>Soccer</span></h1>
      <p class="gm-sub">Play against ${C.teams.length} teams: handmade rule bots and nets trained by self-play.</p>
      <nav class="gm-list" aria-label="Main menu">
        <a class="gm-play gm-link" href="#/game/quick"><span class="gm-play-t"><b>Quick match</b>${last.length === 2 ? vs : "<span>Pick two teams and play</span>"}</span>${icon("arrow", 26)}</a>
        ${items.map(([ic, label, href, sub], k) => `<a class="gm-item gm-link" href="${href}"><span class="gm-ic">${icon(ic)}</span><span class="gm-t"><b>${esc(label)}</b><small>${esc(sub)}</small></span><kbd>${k + 2}</kbd></a>`).join("")}
      </nav>
    </div>
    <div class="gm-reel" aria-label="Teams by Elo"><div class="gm-reel-track">${crests}${crests.replace(/<a /g, '<a aria-hidden="true" ')}</div></div>
  </div>`);
  const links = [...v.querySelectorAll(".gm-link")];
  links[0].focus({ preventScroll: true });
  const scoreEl = $("#gm-score", v), clockEl = $("#gm-clock", v), bugEl = $(".gm-bug", v);
  let shown = "";
  showcase($(".gm-pitch", v), pair, (f) => {
    if (!f) { bugEl.hidden = true; return; }
    const s = `${f.sc[0]} – ${f.sc[1]}|${f.st === 2 ? "FT" : f.ot ? "OT " + clockText(f.ots) : clockText(f.tl)}`;
    if (s === shown) return;
    shown = s; bugEl.hidden = false; [scoreEl.textContent, clockEl.textContent] = s.split("|");
  }, () => { bugEl.classList.remove("goal"); void bugEl.offsetWidth; bugEl.classList.add("goal"); });
  G.keyHandler = (e, down) => {
    if (!down || e.metaKey || e.ctrlKey || e.altKey) return;
    const n = Number(e.key);
    if (n >= 1 && n <= links.length) { e.preventDefault(); location.hash = links[n - 1].getAttribute("href"); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const k = Math.max(0, links.indexOf(document.activeElement));
    links[(k + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length].focus();
  };
}

// the menu's background: a real match between the two teams, played by the match core on the server exactly like Watch in
// Quick match, drawn with the match's own pitch, players and nets and a still camera on the whole pitch (the CSS tilts it).
// A new match starts after each final whistle; it is paused while the tab is hidden and closed when the menu goes.
// With reduced motion: the kickoff line-up only.
export function showcase(cv, teams, onFrame, onGoalEv) {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const S = { ws: null, meta: null, frames: [], timer: 0, done: false };
  const send = (o) => { try { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); } catch (e) {} };
  const vis = () => send({ pause: document.hidden });
  S.stop = () => {
    if (S.done) return;
    S.done = true; clearTimeout(S.timer); document.removeEventListener("visibilitychange", vis);
    send({ quit: 1 }); try { S.ws.close(); } catch (e) {}
    if (G.showcase === S) G.showcase = null;
  };
  if (G.showcase) G.showcase.stop();
  G.showcase = S;
  document.addEventListener("visibilitychange", vis);
  function start() {
    if (S.done) return;
    const ws = S.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/match");
    let ended = false;
    ws.onopen = () => {
      ws.send(JSON.stringify({ setup: { home: teams[0].id, away: teams[1].id, pitch: "big", size: 5, duration: 300, control: "none", allow_draw: true, record: false } }));
      if (document.hidden) send({ pause: true });
    };
    ws.onmessage = (e) => {
      if (S.ws !== ws) return;
      const d = JSON.parse(e.data);
      if (d.k === "m") { prepareMeta(S, d); S.frames = []; }
      else if (d.k === "f") {
        d.at = performance.now();
        S.frames.push(d); if (S.frames.length > 8) S.frames.shift();
        for (const ev of d.ev || []) onGoalEv(ev);
        onFrame(d);
        if (still) { draw(); S.stop(); }
      } else if (d.k === "r" && !ended) {
        ended = true;
        S.timer = setTimeout(() => { send({ quit: 1 }); try { ws.close(); } catch (er) {} start(); }, 6000);
      } else if (d.k === "e") { onFrame(null); S.stop(); }
    };
    ws.onclose = () => { if (S.ws === ws && !ended && !S.done) S.timer = setTimeout(start, 5000); };   // the server went away: try again later
  }
  function draw() {
    const m = S.meta, fr = S.frames;
    const dpr = Math.min(2, window.devicePixelRatio || 1), cw = cv.clientWidth, ch = cv.clientHeight;
    if (!m || !fr.length || !cw || !ch) return;
    if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) { cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr); }
    const ctx = cv.getContext("2d"), P = m.pitch, bx = P.out_x + 6, by = P.out_y + 6, u = Math.min(cw / (2 * bx), ch / (2 * by));
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.setTransform(dpr * u, 0, 0, dpr * u, (dpr * cw) / 2, (dpr * ch) / 2);
    // as drawMatch: positions interpolated between the two frames around (now - one tick)
    const rt = performance.now() - 20;
    let a = fr[fr.length - 1], b = a, k = 0;
    for (let i = fr.length - 1; i > 0; i--) if (fr[i - 1].at <= rt) { a = fr[i - 1]; b = fr[i]; k = Math.min(1, Math.max(0, (rt - a.at) / Math.max(b.at - a.at, 1))); break; }
    if (b.t < a.t || a.p.length !== b.p.length) { a = b; k = 0; }
    const L = (x, y) => x + (y - x) * k;
    ctx.save();
    ctx.beginPath(); ctx.roundRect(-bx, -by, 2 * bx, 2 * by, 16); ctx.clip();
    drawPitch(ctx, m); drawPlayers(ctx, S, m, a, b, L, b); drawNets(ctx, m);
    ctx.restore();
  }
  start();
  if (still) return;
  const loop = () => { if (S.done) return; if (!cv.isConnected) { S.stop(); return; } draw(); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
}
