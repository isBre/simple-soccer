// The Game area: Simple Soccer in the browser. The pages are those of the Godot game (main menu, quick match, teams and players,
// tournaments, match report) and the match itself is played by the Python match core on the server: game/session.py streams
// every tick over a WebSocket, this page draws it and sends the keyboard (or a controller, game/pad.js) back. Local multiplayer:
// the quick match asks who plays where (game/sides.js) when a controller is connected; each device then moves its own person.
// Routes: #/game · #/game/quick · #/game/puzzle · #/game/teams[/<id>] · #/game/players[/<id>] · #/game/build[/<team id>[/copy]]
//         · #/game/rankings[/<size>]
//         · #/game/tournament/new · #/game/tournament · #/game/match · #/game/report
//         · #/game/sounds (every sound and song on its own button; not linked)
// Sound: the menu music (web/music.js) plays on every page but the match and stops in the Lab; menu clicks, the two sound
// buttons in the top bar and the M (music) / N (all sound) keys are set up at the bottom of this file.
// The Lab's router (web/lab/app.js) calls Game.show(parts) for #/game/... ; the tournament is kept in this browser (localStorage).
// The screens are ES modules in web/game/ (core.js: state and helpers; one module per screen; render.js: the canvas).
// This entry module routes #/game/... to them and exposes window.Game for the Lab's router (web/lab/app.js waits for "game-ready").
import { $, G, catalog, esc, header, mount, overlay } from "./game/core.js";
import { match, stopMatch } from "./game/match.js";
import { menu } from "./game/menu.js";
import { padStep } from "./game/pad.js";   // Xbox / standard controller: polled and turned into the same keys
import { puzzlePage } from "./game/puzzle.js";
import { builder } from "./game/builder.js";
import { playerPage, playersList } from "./game/players.js";
import { teamSelect } from "./game/quick.js";
import { rankingsPage } from "./game/rankings.js";
import { drawMatch } from "./game/render.js";
import { report } from "./game/report.js";
import { soundsPage } from "./game/sounds.js";
import { teams } from "./game/teams.js";
import { tourHub, tourNew } from "./game/tournament.js";

// ---------- entry (called by the Lab's router for every #/game/... route) ----------
async function show(parts) {
  stopMatch();
  if (G.showcase) G.showcase.stop();
  document.body.classList.remove("g-playing");
  for (const o of document.querySelectorAll(".g-overlay")) o.remove();
  G.keyHandler = null;
  Sound.crowdOff();
  const [a, b] = parts;
  if (a === "sounds") Music.stop(0.4); else if (!(a === "match" && G.pending)) Music.play();
  try { await catalog(); }
  catch (e) { mount(`<div class="g-page">${header("Simple Soccer")}<p class="g-error">The game server is not available: ${esc(e.message)}</p></div>`); return; }
  if (a === "sounds") return soundsPage();
  if (a === "quick") return teamSelect();
  if (a === "puzzle") return puzzlePage();
  if (a === "teams") return teams(b ? decodeURIComponent(b) : "");
  if (a === "players") return b ? playerPage(decodeURIComponent(b)) : playersList();
  if (a === "build") return builder(b ? decodeURIComponent(b) : "", parts[2] === "copy");
  if (a === "rankings") return rankingsPage(Number(b) || 5);
  if (a === "tournament" && b === "new") return tourNew();
  if (a === "tournament") return tourHub();
  if (a === "match" && G.pending) return match(G.pending);
  if (a === "report" && G.report) return report(G.report.result, G.report.cont);
  if (a === "match" || a === "report") { history.replaceState(null, "", "#/game"); }
  return menu();
}
document.addEventListener("keydown", (e) => {
  if (document.body.dataset.area !== "game") return;
  const tag = document.activeElement?.tagName;
  if ((tag === "INPUT" || tag === "TEXTAREA") && e.key !== "Escape") return;
  if (!G.match && !e.repeat && !e.metaKey && !e.ctrlKey && !e.altKey && (e.code === "KeyM" || e.code === "KeyN")) { toggleSound(e.code === "KeyM"); return; }
  if (G.keyHandler) G.keyHandler(e, true);
});
document.addEventListener("keyup", (e) => { if (document.body.dataset.area === "game" && G.keyHandler) G.keyHandler(e, false); });

// ---------- sound around the pages ----------
// browsers start audio only from a key press or a click: the first one in the Game area starts the menu music
const wake = () => { if (document.body.dataset.area === "game") Sound.unlock().then(() => Music.refresh()); };
for (const ev of ["pointerdown", "keydown", "touchend"]) document.addEventListener(ev, wake, true);
// the two buttons in the top bar (music, all sound) and their keys in the menus (M, N; in a match N is the match's own key)
const ICONS = {
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  sound: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
  off: '<path d="M3 3l18 18"/>',
};
const svg = (k, on) => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[k]}${on ? "" : ICONS.off}</svg>`;
function syncSound() {
  const mb = document.getElementById("snd-music"), sb = document.getElementById("snd-all");
  if (!mb || !sb) return;
  const m = Sound.musicOn && Sound.on, s = Sound.on;
  mb.innerHTML = svg("music", m); mb.setAttribute("aria-pressed", String(m)); mb.classList.toggle("off", !m); mb.disabled = !s;
  sb.innerHTML = svg("sound", s); sb.setAttribute("aria-pressed", String(s)); sb.classList.toggle("off", !s);
}
function toggleSound(music) {
  Sound.unlock();
  if (music) Sound.toggleMusic(); else Sound.toggle();
  Sound.ui("toggle");
  syncSound();
}
document.getElementById("snd-music")?.addEventListener("click", () => toggleSound(true));
document.getElementById("snd-all")?.addEventListener("click", () => toggleSound(false));
Sound.onChange(syncSound);
syncSound();
// menu clicks: a tick when the focus or the mouse moves to another control, a blip when one opens a page, a lower one going back
const UI = "a[href], button, select, summary, input[type=checkbox], input[type=radio], [tabindex]:not([tabindex='-1'])";
const UI_SKIP = ".snd, .gm-reel, [data-area-link], .snd-page [data-s], .snd-page [data-song]";
const uiOk = () => document.body.dataset.area === "game" && !G.match;
const ui = { focus: null, hover: null, at: 0, hash: location.hash };
const depth = (h) => h.replace(/^#\/?/, "").split("/").filter(Boolean).length;
function uiMove(el) {
  if (!el || el.closest(UI_SKIP) || performance.now() - ui.at < 250) return;
  ui.at = performance.now() - 200;                                     // at most one tick per 50 ms
  Sound.ui("move");
}
document.addEventListener("focusin", (e) => {
  if (!uiOk()) return;
  const el = e.target.closest?.(UI);
  if (el && el !== ui.focus) { ui.focus = el; uiMove(el); }
});
document.addEventListener("pointerover", (e) => {
  if (!uiOk() || e.pointerType !== "mouse") return;
  const el = e.target.closest?.(UI);
  if (el !== ui.hover) { ui.hover = el; if (el && el !== document.activeElement) uiMove(el); }
});
document.addEventListener("click", (e) => {
  if (!uiOk()) return;
  const el = e.target.closest?.("a[href], button");
  if (!el || el.closest(UI_SKIP)) return;
  const back = el.getAttribute("href") === "#/game" || /^(‹|back|cancel|close)/i.test(el.textContent.trim());
  ui.at = performance.now(); Sound.ui(back ? "back" : "select");
}, true);
window.addEventListener("hashchange", () => {                          // a page opened by a key (Enter, 1-9, Esc) rather than a click
  const from = ui.hash; ui.hash = location.hash;
  if (!uiOk() || !location.hash.startsWith("#/game") || performance.now() - ui.at < 300) return;
  ui.at = performance.now(); Sound.ui(depth(location.hash) < depth(from) ? "back" : "select");
});

window.Game = { show, stopMatch, state: () => G, redraw: () => G.match && drawMatch(G.match, performance.now()), padStep };   // state, redraw, padStep: for tests
window.dispatchEvent(new Event("game-ready"));
