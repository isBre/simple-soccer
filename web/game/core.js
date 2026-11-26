// The Game (web/game.js has the overview): the state, helpers, API calls and small components shared by every screen.
import { match, play } from "./match.js";
import { menu, showcase } from "./menu.js";
import { text } from "./render.js";
import { report } from "./report.js";

export const G = { cat: null, byId: {}, playerById: {}, keyHandler: null, match: null, pending: null, report: null, tab: 0, busy: false, pz: null, showcase: null };
export const SAVE = "soccer.tournament";
export const CONTROLS = ["single", "team", "none"];
// "Record my play": the match is saved as a dataset file for imitation learning (game/recorder.py), remembered in this browser
export const PREFS = "soccer.prefs";
export const prefs = (() => { try { return { record: true, ...JSON.parse(localStorage.getItem(PREFS) || "{}") }; } catch (e) { return { record: true }; } })();
export const savePrefs = () => { try { localStorage.setItem(PREFS, JSON.stringify(prefs)); } catch (e) {} };
export const $ = (s, el = document) => el.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const view = () => document.getElementById("view");
export const go = (h) => { location.hash = h; };
export const RAT = (r) => (r >= 7.5 ? "var(--g-good)" : r >= 6.5 ? "#b9e36a" : r >= 5.8 ? "var(--g-accent)" : "var(--g-bad)");

export async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
  let d = {};
  try { d = await r.json(); } catch (e) { d = { error: "HTTP " + r.status }; }
  if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
  return d;
}
export async function catalog() {
  if (!G.cat) { G.cat = await api("/api/game/catalog"); for (const t of G.cat.teams) G.byId[t.id] = t; for (const p of G.cat.players) G.playerById[p.id] = p; }
  return G.cat;
}
export const loadT = () => { try { return JSON.parse(localStorage.getItem(SAVE) || "null"); } catch (e) { return null; } };
export const saveT = (t) => { try { localStorage.setItem(SAVE, JSON.stringify(t)); } catch (e) {} };
export const leagueTeams = (id) => G.cat.teams.filter((t) => t.league === id);
export const pitchOf = (id) => G.cat.pitches.find((p) => p.id === id) || G.cat.pitches[0];

// ---------- small components ----------
export function mount(html) { const v = view(); v.innerHTML = html; Draw.fillLogos(v, G.byId); return v; }
export const btn = (label, attrs = "", cls = "") => `<button class="g-btn ${cls}" ${attrs}>${label}</button>`;
export const card = (body, title = "", cls = "", style = "") => `<div class="g-card ${cls}" style="${style}">${title ? `<h2>${esc(title)}</h2>` : ""}${body}</div>`;
export const header = (title, sub) => `<div><h1 class="g-h1">${esc(title)}</h1>${sub ? `<p class="g-sub">${esc(sub)}</p>` : ""}</div>`;
export const CHEV = (d) => `<svg width="14" height="24" viewBox="0 0 14 24" style="--nudge:${d * 2}px"><polyline points="${d > 0 ? "3,1 11,12 3,23" : "11,1 3,12 11,23"}" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
// a table in the game's look: cols [{t, w, a: l|r|c}], rows [{cells: [html | {text, color, size}], hl, zone}]
export function table(cols, rows) {
  const cell = (c) => (c && typeof c === "object" ? `<span style="${c.color ? "color:" + c.color + ";" : ""}${c.size ? "font-size:" + c.size + "px;" : ""}${c.bold ? "font-weight:700;" : ""}">${esc(c.text)}</span>` : c);
  return `<table class="g-table"><thead><tr>${cols.map((c) => `<th class="${c.a || ""}" style="${c.w ? "width:" + c.w + "px" : ""}">${esc(c.t)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
    `<tr class="${r.hl ? "hl" : ""}${r.zone ? " zone" : ""}">${r.cells.map((c, i) => `<td class="${cols[i].a || ""}">${cell(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
export const teamCell = (t, text, color, px = 24, you = false) => `<span class="teamcell">${Draw.logoTag(t.id, px)}<span style="color:${color || "inherit"}">${esc(text)}</span>${you ? '<span class="you-pill">You</span>' : ""}</span>`;
export function overlay(html) { const o = document.createElement("div"); o.className = "g-overlay"; o.innerHTML = html; document.body.append(o); return o; }

// ---------- page shell of the other game pages: a slim top row (back to the menu, keys), then the page ----------
export const KEYS_HTML = (keys) => keys.map(([k, d]) => `<span><kbd>${k}</kbd> ${d}</span>`).join("");
export const shell = (body, keys = [], cls = "") => `<div class="gp ${cls}"><div class="ks-top"><nav class="ks-links"><a href="#/game">‹ Menu</a></nav><div class="ks-keys">${KEYS_HTML(keys)}</div></div>${body}</div>`;
export const eloText = (t) => (t.elo != null ? `Elo ${t.elo}` : "Elo not rated yet");
export const playsText = (t) => t.plays || "Play style not measured yet (python3 game/profiles.py).";
export const whoDrives = (t) => (t.net ? "Every player is the same trained net (reinforcement learning); it plays 5v5 only."
  : t.kinds.length > 1 ? "A mixed line-up: " + t.kinds.map((k) => ({ rules: "rule-based", opus: "Opus", net: "net" })[k]).join(", ") + " players."
  : t.kinds[0] === "opus" ? "Every player is the Opus planner." : "Driven by the handmade AI.");
