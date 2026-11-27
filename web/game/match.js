// The Game (web/game.js has the overview): the live match over the WebSocket and the cards over it.
import { $, G, card, esc, go, mount } from "./core.js";
import { clockText, drawMatch, onGoal, sfx, text } from "./render.js";
import { report } from "./report.js";
import { padConnected } from "./pad.js";
import { teams } from "./teams.js";

// ---------- the live match ----------
export function play(p) { G.pending = p; go("#/game/match"); }
export function stopMatch() {
  const M = G.match; if (!M) return;
  M.stopped = true; cancelAnimationFrame(M.raf);
  Sound.crowdOff(); if (M.paused) Sound.pause(false);
  window.removeEventListener("blur", M.onBlur);
  try { M.ws.send(JSON.stringify({ quit: 1 })); } catch (e) {}
  try { M.ws.close(); } catch (e) {}
  G.match = null;
}
// Who plays with what. p.devices (local multiplayer, web/game/sides.js): one device per person of setup.humans, in order, "kb" or
// "pad:<index>" (the Gamepad API index); each device moves only its own person. Without it every device moves the one human.
export const humanOf = (M, dev) => (M.p.devices ? M.p.devices.indexOf(dev) : 0);
export const devOfEvent = (e) => (e && e.padIndex != null ? "pad:" + e.padIndex : "kb");
export const devName = (dev) => (dev === "kb" ? "Keyboard" : "Controller " + (Number(dev.slice(4)) + 1));
export const HUMAN_COLORS = ["#ef5350", "#42a5f5", "#aed581", "#ffb74d"];   // P1 red, P2 blue, P3, P4: rings, the side picker
export const KEYS = { ArrowLeft: [-1, 0], KeyA: [-1, 0], ArrowRight: [1, 0], KeyD: [1, 0], ArrowUp: [0, -1], KeyW: [0, -1], ArrowDown: [0, 1], KeyS: [0, 1] };
export function match(p) {
  document.body.classList.add("g-playing");
  Music.stop(1.2); Sound.unlock();
  const v = mount('<div class="g-match"><canvas></canvas></div>');
  const cv = $("canvas", v);
  const M = G.match = { p, cv, ws: null, meta: null, frames: [], held: new Set(), pads: {}, sentIn: [], paused: false, speed: 1, result: null, error: "", stopped: false,
    cam: null, parts: [], mes: [], goal: null, lastStep: 0, partAcc: 0, raf: 0, ended: false };
  M.ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/match");
  M.ws.onopen = () => M.ws.send(JSON.stringify({ setup: p.setup, puzzle: p.puzzle ?? null }));
  M.ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.k === "m") prepareMeta(M, d);
    else if (d.k === "f") {
      d.at = performance.now();
      sfx(M, d);
      M.frames.push(d); if (M.frames.length > 8) M.frames.shift();
      for (const ev of d.ev || []) onGoal(M, ev);
    } else if (d.k === "r") {
      M.result = d.result;
      if (p.session) setTimeout(() => { if (G.match === M && !M.stopped && !M.doneCalled) { M.doneCalled = true; p.done(d.result); } }, 1700);   // puzzle: the next round starts by itself
    }
    else if (d.k === "e") M.error = d.error;
  };
  M.ws.onclose = () => { if (!M.result && !M.stopped && !M.error) M.error = "the connection to the game server closed"; };
  M.onBlur = () => { M.held.clear(); M.pads = {}; sendAll(M); };
  window.addEventListener("blur", M.onBlur);
  G.keyHandler = (e, down) => onKey(M, e, down);
  const loop = (ts) => { if (M.stopped) return; M.raf = requestAnimationFrame(loop); drawMatch(M, ts); };
  M.raf = requestAnimationFrame(loop);
}
export function wsSend(M, obj) { try { if (M.ws.readyState === 1) M.ws.send(JSON.stringify(obj)); } catch (e) {} }
// the keys of person h (default the one human): the keyboard's arrows / WASD first, else a controller's stick (web/game/pad.js sets
// M.pads[index] = {stick, kick}); sent only when they change
export function sendInput(M, h = 0) {
  if (h < 0) return;
  const mine = (dev) => !M.p.devices || M.p.devices[h] === dev;
  let dx = 0, dy = 0, kick = 0;
  if (mine("kb")) {
    for (const k of M.held) if (KEYS[k]) { dx += KEYS[k][0]; dy += KEYS[k][1]; }
    dx = Math.sign(dx); dy = Math.sign(dy);
    if (M.held.has("KeyX") || M.held.has("Space")) kick = 1;
  }
  for (const [i, q] of Object.entries(M.pads)) {
    if (!mine("pad:" + i)) continue;
    if (!dx && !dy && q.stick) [dx, dy] = q.stick;
    if (q.kick) kick = 1;
  }
  const s = `${dx},${dy},${kick}`;
  if (s !== M.sentIn[h]) { M.sentIn[h] = s; wsSend(M, M.p.devices ? { in: [dx, dy, kick], h } : { in: [dx, dy, kick] }); }
}
export function sendAll(M) { for (let h = 0; h < (M.p.devices ? M.p.devices.length : 1); h++) sendInput(M, h); }
export function onKey(M, e, down) {
  const c = e.code;
  if (KEYS[c] || c === "KeyX" || c === "Space") {
    e.preventDefault();
    if (down) M.held.add(c); else M.held.delete(c);
    sendInput(M, humanOf(M, "kb")); return;
  }
  if (!down || e.repeat) return;
  const f = M.frames[M.frames.length - 1], ended = f && f.st === 2 && !M.p.session, ok = c === "Enter" || c === "NumpadEnter";
  if (M.error) { if (ok || c === "Escape") act(M, "quit"); }
  else if (ended) { if ((ok || c === "Escape") && M.result) act(M, "report"); else if (c === "KeyR" && M.p.rematch) act(M, "restart"); }
  else if (c === "Escape" || c === "KeyP") act(M, "pause");
  else if (M.paused && c === "KeyM") act(M, "quit");
  else if (M.paused && c === "KeyR" && !M.p.session) act(M, "restart");
  else if (c === "KeyT") { M.speed = M.speed === 1 ? 2 : M.speed === 2 ? 4 : M.speed === 4 ? 8 : 1; wsSend(M, { speed: M.speed }); }
  else if (c === "KeyQ") { const h = humanOf(M, devOfEvent(e)); if (h >= 0) wsSend(M, M.p.devices ? { switch: 1, h } : { switch: 1 }); }
  else if (c === "KeyN") { Sound.unlock(); M.toast = { text: Sound.toggle() ? "Sound on" : "Sound off", at: performance.now() }; }
}
// what a key or a card button does: pause / resume, restart (same teams, new seed), quit, the report after the final whistle
export function act(M, a) {
  if (a === "pause") { M.paused = !M.paused; wsSend(M, { pause: M.paused }); Sound.pause(M.paused); }
  else if (a === "restart") { const p = { ...M.p, setup: { ...M.p.setup, seed: Math.floor(Math.random() * 2147483647) } }; G.pending = null; stopMatch(); G.pending = p; match(p); }
  else if (a === "quit") { const q = M.p.quit; G.pending = null; stopMatch(); q(); }
  else if (a === "report" && M.result) { const res = M.result, done = M.p.done; G.pending = null; stopMatch(); done(res); }
}
// ---------- the cards over the match: pause, full time, error (HTML, so they have real buttons) ----------
export function overlayKind(M, f) {
  if (M.error) return "error";
  if (f && f.st === 2 && !M.p.session) return M.result ? "end" : "wait";
  return M.paused ? "pause" : "";
}
export function syncOverlay(M, f) {
  const kind = overlayKind(M, f);
  if (kind === M.ovKind) return;
  M.ovKind = kind;
  if (!kind) { if (M.ov) M.ov.hidden = true; return; }
  if (!M.ov) { M.ov = document.createElement("div"); M.ov.className = "mo"; M.cv.parentElement.append(M.ov); }
  const ov = M.ov, m = M.meta;
  ov.hidden = false;
  const k = (x) => `<kbd>${x}</kbd>`;
  const sw = m.control === 2 || (m.humans || []).some((h) => h.mode === 2);
  const who = M.p.devices ? `<div class="mo-keys mo-who">${M.p.devices.map((d, i) => `<span><b style="color:${HUMAN_COLORS[i % 4]}">P${i + 1}</b> ${devName(d)} · ${esc(m.teams[m.humans[i].team].name)} · ${m.humans[i].mode === 2 ? "whole team" : "one player"}</span>`).join("")}</div>` : "";
  if (kind === "error") ov.innerHTML = `<div class="mo-card"><div class="mo-k">The match stopped</div><p class="mo-msg">${esc(M.error)}</p>
    <div class="mo-btns"><button type="button" class="ks-go" data-act="quit">Back ${k("Enter")}</button></div></div>`;
  else if (kind === "pause") ov.innerHTML = `<div class="mo-card"><div class="mo-k">Paused · ${f.ot ? "overtime " + clockText(f.ots) : clockText(f.tl) + " left"}</div>
    <div class="mo-sc small">${esc(m.teams[0].name)} <b>${f.sc[0]} – ${f.sc[1]}</b> ${esc(m.teams[1].name)}</div>
    <div class="mo-btns col"><button type="button" class="ks-go" data-act="pause">Resume ${k("Esc")}</button>
      ${M.p.session ? "" : `<button type="button" class="ks-btn2" data-act="restart">Restart ${k("R")}</button>`}<button type="button" class="ks-btn2" data-act="quit">Quit the match ${k("M")}</button></div>
    <div class="mo-keys"><span>${k("WASD")} ${k("↑↓←→")} move</span><span>${k("Space")} ${k("X")} kick</span>${sw ? `<span>${k("Q")} switch player (tap again: next)</span>` : ""}<span>${k("T")} speed</span><span>${k("N")} sound ${Sound.on ? "on" : "off"}</span></div>
    ${padConnected() ? `<div class="mo-keys"><span>Controller:</span><span>${k("L")} move</span><span>${k("A")} ${k("X")} ${k("RT")} kick</span>${sw ? `<span>${k("LB")} ${k("RB")} switch</span>` : ""}<span>${k("☰")} pause</span><span>${k("⧉")} speed</span></div>
    <div class="mo-keys"><span>Paused:</span><span>${k("A")} resume</span>${M.p.session ? "" : `<span>${k("Y")} restart</span>`}<span>${k("⧉")} quit</span></div>` : ""}${who}</div>`;
  else {
    const res = M.result, w = f.w, ev = res ? res.events : [];
    const verdict = w === -1 ? "Draw" : `${esc(m.teams[w].name)} win${res?.overtime ? " with a golden goal" : ""}`;
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
export function prepareMeta(M, m) {
  M.meta = m;
  m.kits = m.teams.map((t) => [Draw.rgb(t.kit[0]), Draw.rgb(t.kit[1])]);
  const P = m.pitch;
  P.cPitch = Draw.rgb(P.pitch); P.cOuter = Draw.rgb(P.outer); P.cLine = Draw.rgb(P.line);
  m.goalCols = m.kits.map((k) => Draw.goalColour(k, P.cPitch));
  m.byUid = {}; m.players.forEach((pl, i) => { pl.i = i; pl.last = pl.name.split(" ")[1] || ""; m.byUid[pl.uid] = pl; });
  Sound.crowdOn();
}
