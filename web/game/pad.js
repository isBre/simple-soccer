// The Game (web/game.js has the overview): Xbox (or any "standard" mapping) controller through the Gamepad API.
// Polled every animation frame while a controller is connected and turned into the keys the screens already handle (G.keyHandler),
// so every page works with it; in a match the left stick is analog (the server normalises the direction, game/session.py).
//   menus:  D-pad / left stick = arrows (held: repeat), A = Enter (or clicks the focused button / link), B = Esc,
//           LB / RB = Shift+Tab / Tab, Y = R (random), X = S (swap), Start = start the page (kick off, play).
//           An arrow a page does not use moves the focus to the nearest button / link in that direction.
//   match:  left stick / D-pad = move, A / X / RT = kick (held), LB / RB = switch player, Start = pause,
//           View = speed (paused: quit), Y = restart / rematch, right stick click = sound;
//           on the pause / full-time / error card: A = Enter (or resume), B = Esc.
// Every connected controller is read. The keys it fires carry its index (e.padIndex), so a page can tell the devices apart
// (web/game/sides.js, local multiplayer); in a multiplayer match each controller moves only its own person (match.js p.devices),
// and a controller of the match that disconnects pauses it.
import { G } from "./core.js";
import { act, devName, humanOf, overlayKind, sendAll, sendInput } from "./match.js";

const B = { A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, LT: 6, RT: 7, VIEW: 8, START: 9, LS: 10, RS: 11, UP: 12, DOWN: 13, LEFT: 14, RIGHT: 15 };
const DEAD = 0.3, MENU_DEAD = 0.5, REPEAT_FIRST = 380, REPEAT_EVERY = 110, STEPS = 32;
const P = { raf: 0, prev: {}, dir: {}, dirNext: {}, kickLock: {}, cur: null };   // per controller index; cur: the one being read
export const padConnected = () => [...(navigator.getGamepads?.() || [])].some((g) => g && g.connected);

const pressed = (g, i) => { const b = g.buttons[i]; return !!b && (b.pressed || b.value > 0.5); };
function fire(key, code, down, extra = {}) {
  const e = { key, code, repeat: false, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false, pad: true, padIndex: P.cur, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, ...extra };
  if (document.body.dataset.area !== "game" || !G.keyHandler) return e;
  const tag = document.activeElement?.tagName;
  if ((tag === "INPUT" || tag === "TEXTAREA") && key !== "Escape") return e;
  G.keyHandler(e, down);
  return e;
}
const tap = (key, code, extra) => { const e = fire(key, code, true, extra); fire(key, code, false, extra); return e; };

// ---------- moving the focus without a mouse ----------
const FOCUSABLE = "a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]):not([type=hidden]), [tabindex]:not([tabindex='-1'])";
function scope() {   // the card over the page wins (match card, overlays), else the page
  const c = [...document.querySelectorAll(".mo:not([hidden]), .g-overlay")].pop();
  return c || document.getElementById("view") || document.body;
}
const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };
const targets = () => [...scope().querySelectorAll(FOCUSABLE)].filter(visible);
function focusEl(el) { el.focus({ preventScroll: false }); el.scrollIntoView?.({ block: "nearest", inline: "nearest" }); }
function moveFocus(dx, dy) {
  const all = targets();
  if (!all.length) return;
  const cur = document.activeElement;
  if (!cur || !all.includes(cur)) { focusEl(all[0]); return; }
  const r = cur.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  let best = null, bestScore = Infinity;
  for (const el of all) {
    if (el === cur || cur.contains(el)) continue;
    const q = el.getBoundingClientRect(), x = q.left + q.width / 2, y = q.top + q.height / 2;
    const along = (x - cx) * dx + (y - cy) * dy, across = Math.abs((x - cx) * dy) + Math.abs((y - cy) * dx);
    if (along <= 1) continue;
    const score = along + across * 2.5;
    if (score < bestScore) { bestScore = score; best = el; }
  }
  if (best) focusEl(best);
}
function tabFocus(back) {   // the next / previous control, skipping the ones inside the focused one (a team card's own buttons)
  const cur = document.activeElement, all = targets().filter((el) => el === cur || !cur?.contains(el) || cur === document.body);
  if (!all.length) return;
  const k = all.indexOf(cur);
  focusEl(all[k < 0 ? 0 : (k + (back ? -1 : 1) + all.length) % all.length]);
}
function startPage() {   // Start: what Enter does on the page with nothing focused (kick off, play, start); else as A
  const a = document.activeElement;
  a?.blur?.();
  const e = tap("Enter", "Enter");
  if (e.defaultPrevented) return;
  if (a && a !== document.body && a.isConnected) a.focus({ preventScroll: true });
  if (document.body.dataset.area === "game") activate();
}
function activate() {   // A on a focused control the page did not take Enter for
  const a = document.activeElement;
  if (!a || a === document.body) { const t = targets()[0]; if (t) focusEl(t); return; }
  if (a.tagName === "SELECT") { a.showPicker?.(); return; }
  a.click();
}

// ---------- per frame ----------
const ARROW = { L: ["ArrowLeft", -1, 0], R: ["ArrowRight", 1, 0], U: ["ArrowUp", 0, -1], D: ["ArrowDown", 0, 1] };
function menuDir(g) {
  if (pressed(g, B.LEFT)) return "L"; if (pressed(g, B.RIGHT)) return "R"; if (pressed(g, B.UP)) return "U"; if (pressed(g, B.DOWN)) return "D";
  const x = g.axes[0] || 0, y = g.axes[1] || 0;
  if (Math.hypot(x, y) < MENU_DEAD) return "";
  return Math.abs(x) > Math.abs(y) ? (x < 0 ? "L" : "R") : (y < 0 ? "U" : "D");
}
function arrow(d, repeat) {
  const [key, dx, dy] = ARROW[d];
  const e = fire(key, key, true, { repeat });
  fire(key, key, false);
  if (!e.defaultPrevented) moveFocus(dx, dy);
}
function menus(g, now, edge) {
  const d = menuDir(g), i = g.index;
  if (d !== (P.dir[i] || "")) { P.dir[i] = d; if (d) { arrow(d, false); P.dirNext[i] = now + REPEAT_FIRST; } }
  else if (d && now >= P.dirNext[i]) { arrow(d, true); P.dirNext[i] = now + REPEAT_EVERY; }
  if (edge(B.A)) { const e = tap("Enter", "Enter"); if (!e.defaultPrevented && document.body.dataset.area === "game") activate(); }
  if (edge(B.START)) startPage();
  if (edge(B.B)) tap("Escape", "Escape");
  if (edge(B.RB)) { const e = tap("Tab", "Tab"); if (!e.defaultPrevented) tabFocus(false); }
  if (edge(B.LB)) { const e = tap("Tab", "Tab", { shiftKey: true }); if (!e.defaultPrevented) tabFocus(true); }
  if (edge(B.Y)) tap("r", "KeyR");
  if (edge(B.X)) tap("s", "KeyS");
}
function inMatch(M, g, edge) {
  const f = M.frames[M.frames.length - 1], card = overlayKind(M, f);
  // movement: D-pad (8 ways) or the left stick (analog, in STEPS directions so the page sends only real changes)
  let x = (pressed(g, B.RIGHT) ? 1 : 0) - (pressed(g, B.LEFT) ? 1 : 0), y = (pressed(g, B.DOWN) ? 1 : 0) - (pressed(g, B.UP) ? 1 : 0);
  if (!x && !y) {
    const ax = g.axes[0] || 0, ay = g.axes[1] || 0;
    if (Math.hypot(ax, ay) >= DEAD) {
      const a = Math.round(Math.atan2(ay, ax) / (2 * Math.PI / STEPS)) * (2 * Math.PI / STEPS);
      x = Math.round(Math.cos(a) * 1000) / 1000; y = Math.round(Math.sin(a) * 1000) / 1000;
    }
  }
  const kickHeld = pressed(g, B.A) || pressed(g, B.X) || pressed(g, B.RT), i = g.index;
  if (card) P.kickLock[i] = true; else if (!kickHeld) P.kickLock[i] = false;   // the A that closed a card does not kick
  const kick = !card && !P.kickLock[i] && kickHeld;
  const stick = card ? null : (x || y ? [x, y] : null), was = M.pads[i] || {};
  if (String(stick) !== String(was.stick) || kick !== !!was.kick) { M.pads[i] = { stick, kick }; sendInput(M, humanOf(M, "pad:" + i)); }
  if (card) {
    if (edge(B.A)) { if (card === "pause") act(M, "pause"); else tap("Enter", "Enter"); }
    if (edge(B.B)) tap("Escape", "Escape");
    if (edge(B.START)) tap("Escape", "Escape");
    if (edge(B.Y)) tap("r", "KeyR");
    if (edge(B.VIEW) && card === "pause") tap("m", "KeyM");
    return;
  }
  if (edge(B.START)) tap("Escape", "Escape");
  if (edge(B.LB) || edge(B.RB)) tap("q", "KeyQ");
  if (edge(B.VIEW)) tap("t", "KeyT");
  if (edge(B.RS)) tap("n", "KeyN");
}
function poll(now) {
  P.raf = 0;
  if (padStep(now)) P.raf = requestAnimationFrame(poll);
}
// one frame of the controller (exported as Game.padStep for tests); false when no controller is connected
export function padStep(now = performance.now()) {
  const pads = [...(navigator.getGamepads?.() || [])].filter((g) => g && g.connected);
  if (!pads.length) return false;
  for (const g of pads) {
    const was = P.prev[g.index] || [], cur = g.buttons.map((_, i) => pressed(g, i));
    P.prev[g.index] = cur;
    if (document.body.dataset.area !== "game") continue;
    const edge = (i) => cur[i] && !was[i];
    P.cur = g.index;
    if (G.match && !G.match.stopped && G.keyHandler) inMatch(G.match, g, edge);
    else menus(g, now, edge);
    P.cur = null;
  }
  return true;
}
function start() { if (!P.raf) P.raf = requestAnimationFrame(poll); }
window.addEventListener("gamepadconnected", (e) => {
  start();
  if (G.match) G.match.toast = { text: devName("pad:" + e.gamepad.index) + " connected", at: performance.now() };
});
window.addEventListener("gamepaddisconnected", (e) => {
  const M = G.match, i = e.gamepad.index;
  delete P.prev[i];
  if (!M) return;
  delete M.pads[i];
  sendAll(M);
  const mine = M.p.devices && M.p.devices.includes("pad:" + i);
  if (mine) {                                         // a person of this match lost their controller: pause until it is back
    const f = M.frames[M.frames.length - 1];
    if (!M.paused && !overlayKind(M, f)) act(M, "pause");
    M.toast = { text: devName("pad:" + i) + " disconnected: reconnect it and resume", at: performance.now() };
  } else if (!padConnected()) M.toast = { text: "Controller disconnected", at: performance.now() };
});
if (padConnected()) start();
