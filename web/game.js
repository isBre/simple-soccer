// The Game area: Simple Soccer in the browser. The pages are those of the Godot game (main menu, quick match, teams & squads,
// tournaments, match report) and the match itself is played by the Python match core on the server: game/session.py streams
// every tick over a WebSocket, this page draws it and sends the keyboard back.
// Routes: #/game · #/game/quick · #/game/puzzle · #/game/teams[/<id>] · #/game/tournament/new · #/game/tournament · #/game/match · #/game/report
// The Lab's router (web/lab/app.js) calls Game.show(parts) for #/game/... ; the tournament is kept in this browser (localStorage).
// The screens are ES modules in web/game/ (core.js: state and helpers; one module per screen; render.js: the canvas).
// This entry module routes #/game/... to them and exposes window.Game for the Lab's router (web/lab/app.js waits for "game-ready").
import { $, G, catalog, esc, header, mount, overlay } from "./game/core.js";
import { match, stopMatch } from "./game/match.js";
import { menu } from "./game/menu.js";
import { puzzlePage } from "./game/puzzle.js";
import { teamSelect } from "./game/quick.js";
import { drawMatch } from "./game/render.js";
import { report } from "./game/report.js";
import { teams } from "./game/teams.js";
import { tourHub, tourNew } from "./game/tournament.js";

// ---------- entry (called by the Lab's router for every #/game/... route) ----------
async function show(parts) {
  stopMatch();
  if (G.showcase) G.showcase.stop();
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

window.Game = { show, stopMatch, state: () => G, redraw: () => G.match && drawMatch(G.match, performance.now()) };   // state, redraw: for tests
window.dispatchEvent(new Event("game-ready"));
