// The Game (web/game.js has the overview): drawing the match on the canvas (camera, pitch, players, scorebug, goal banner, sounds).
import { $, G } from "./core.js";
import { match, play, syncOverlay } from "./match.js";
import { drawPuzzleHud } from "./puzzle.js";

// the camera uses the whole window (no HUD strip); TOP = just below the scorebug (the off-screen marker stays under it)
export const BASE_W = 1280, BASE_H = 720, TOP = 64, CAM_ZOOM = 1.15, CAM_SMOOTH = 0.08, INTRO = 130, INTRO_FROM = 0.86;
export let FAMILY = "";
export const FONT = (px, wt = 400) => { if (!FAMILY) FAMILY = getComputedStyle(document.documentElement).getPropertyValue("--g-font").trim() || "sans-serif"; return `${wt} ${px}px ${FAMILY}`; };
export const ACC = [1, 213 / 255, 74 / 255];
// Godot's draw_string: (x, y) = baseline start; align c / r inside [x, x + w]
export function text(ctx, s, x, y, align, w, px, color, outline = 0, outCol = "rgba(0,0,0,0.9)", wt = 400) {
  ctx.font = FONT(px, wt); ctx.textBaseline = "alphabetic";
  let tx = x;
  if (align === "c") { ctx.textAlign = "center"; tx = x + w / 2; } else if (align === "r") { ctx.textAlign = "right"; tx = x + w; } else ctx.textAlign = "left";
  if (outline) { ctx.lineJoin = "round"; ctx.lineWidth = outline; ctx.strokeStyle = outCol; ctx.strokeText(s, tx, y); }
  ctx.fillStyle = color; ctx.fillText(s, tx, y);
}
export const clockText = (s) => { s = Math.max(0, Math.floor(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

export function onGoal(M, ev) {
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
// the sounds of a new frame d, from what changed since the frames before it (web/sound.js makes them)
export function sfx(M, d) {
  const m = M.meta, fr = M.frames, a = fr[fr.length - 1], z = fr[fr.length - 2];
  if (!m || !a || d.t < a.t) return;                                                  // (the tick stands still during the kickoff intro)
  const P = m.pitch, pan = d.b[0] / (P.out_x || P.half_w) * 0.7, now = performance.now(), mine = (t) => m.control === 0 || t === m.human_team;
  if (a.in > 0 && !d.in && d.st === 0) Sound.whistle(Sound.WHISTLE.kickoff);          // every kickoff's intro is over: play
  if (!a.ot && d.ot) Sound.whistle(Sound.WHISTLE.overtime);
  if (a.st !== 1 && d.st === 1) { Sound.goal(mine(d.gt)); Sound.bounce("net", 0.8, pan); M.shot = null; M.bounceAt = now; }
  if (a.st !== 2 && d.st === 2) { Sound.whistle(Sound.WHISTLE.fulltime); setTimeout(() => G.match === M && Sound.fulltime(), 1300); }
  if (d.st === 2 || d.in) return;
  // the crowd: louder as the ball nears either goal, more so in front of it and when it moves fast
  if (d.st === 0 && !(d.t % 6)) {
    const near = Math.max(0, (Math.abs(d.b[0]) / P.half_w - 0.4) / 0.6), central = Math.abs(d.b[1]) < P.goal_half * 2.5 ? 1 : 0.6;
    const speed = Math.min(1, Math.hypot(d.b[0] - a.b[0], d.b[1] - a.b[1]) / (M.speed || 1) / 8);
    Sound.hype(Math.pow(near, 1.4) * central * (0.75 + 0.25 * speed));
  }
  // a kick: a player's "kick used" flag (it is set only when the kick reached the ball) goes on
  let kicked = false;
  for (let i = 0; i < d.h.length && !kicked; i++) if ((d.h[i] & 4) && !(a.h[i] & 4)) {
    const v = Math.hypot(d.b[0] - a.b[0], d.b[1] - a.b[1]) / (M.speed || 1), s = Math.min(1, Math.max(0.3, v / 7));
    Sound.kick(s * (d.h[i] & 1 ? 1 : 0.8), pan); kicked = true;
    // a shot: fast, towards the goal the player attacks, from the half nearer it (for an "ooh" if it misses)
    const goalX = Math.sign(d.b[0] - a.b[0]) * P.half_w;
    if (v > 5 && Math.abs(d.b[0]) > P.half_w * 0.3 && Math.sign(d.b[0]) === Math.sign(goalX)) M.shot = { at: now, x: goalX };
  }
  if (M.shot && now - M.shot.at > 2500) M.shot = null;
  if (M.speed !== 1) return;
  // two players of different teams run into each other fighting for the ball (hard enough to hear; at most one in 0.6 s)
  if (now - (M.tackleAt || 0) > 600 && d.p.length === a.p.length) {
    const n = d.p.length / 2, pl = m.players;
    pairs: for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      if (pl[i].team === pl[j].team) continue;
      const r = pl[i].r + pl[j].r + 1.5;
      const dd = Math.hypot(d.p[2 * i] - d.p[2 * j], d.p[2 * i + 1] - d.p[2 * j + 1]), da = Math.hypot(a.p[2 * i] - a.p[2 * j], a.p[2 * i + 1] - a.p[2 * j + 1]);
      if (dd < r && da >= r && da - dd > 1.5 && Math.min(Math.hypot(d.p[2 * i] - d.b[0], d.p[2 * i + 1] - d.b[1]), Math.hypot(d.p[2 * j] - d.b[0], d.p[2 * j + 1] - d.b[1])) < 1.6 * r) {
        M.tackleAt = now; Sound.tackle(Math.min(1, (da - dd) / 3), d.p[2 * i] / (P.out_x || P.half_w) * 0.7);
        break pairs;
      }
    }
  }
  // the ball changed direction without a kick: off a post, the boards, the net or a player
  if (kicked || !z || now - (M.bounceAt || 0) < 90) return;
  const v1 = [a.b[0] - z.b[0], a.b[1] - z.b[1]], v2 = [d.b[0] - a.b[0], d.b[1] - a.b[1]], s1 = Math.hypot(...v1);
  if (s1 < 1.2 || Math.hypot(...v2) > 40 || !((v1[0] * v2[0] < 0 && Math.abs(v1[0]) > 0.8) || (v1[1] * v2[1] < 0 && Math.abs(v1[1]) > 0.8))) return;
  const br = m.ball_r, [bx, by] = a.b;
  const post = P.statics.some(([sx, sy, sr]) => Math.hypot(bx - sx, by - sy) < sr + br + 6);
  const net = !post && Math.abs(bx) > P.half_w && Math.abs(by) < P.goal_half + br;
  const wall = Math.abs(by) > P.half_h - br - 6 || Math.abs(bx) > P.half_w - br - 6;
  M.bounceAt = now;
  Sound.bounce(post ? "post" : net ? "net" : wall ? "wall" : "body", Math.min(1, s1 / 6), pan);
  // a near miss or a save: an "ooh" (a moment later, and not if it went in after all)
  const nearGoal = Math.abs(bx) > P.half_w * 0.7 && Math.abs(by) < P.goal_half * 2.5;
  if (!net && nearGoal && (post || (M.shot && s1 > 3.5 && Math.sign(bx) === Math.sign(M.shot.x)))) {
    const save = !post && !wall;
    M.shot = null;
    setTimeout(() => {
      const f = M.frames[M.frames.length - 1];
      if (G.match !== M || !f || f.st !== 0) return;
      Sound.ooh(post ? 1 : 0.75);
      if (save) Sound.applause(2, 0.45, 0.5);
    }, 160);
  }
}
export function stepParticles(M, f) {
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
export function drawParticles(ctx, M) {
  for (const q of M.parts) {
    const a = Math.max(0, Math.min(1, 1 - q.age / q.life)), col = Draw.css(q.col, Math.min(1, a * 2));
    ctx.fillStyle = col;
    if (q.kind === 1) { ctx.beginPath(); ctx.arc(q.x, q.y, q.sz * a + 0.5, 0, 2 * Math.PI); ctx.fill(); }
    else { ctx.save(); ctx.translate(q.x, q.y); ctx.rotate(q.rot); ctx.scale(1, Math.abs(Math.cos(q.rot * 0.7)) * 0.8 + 0.2); ctx.fillRect(-q.sz, -q.sz * 0.5, q.sz * 2, q.sz); ctx.restore(); }
  }
}

export function drawMatch(M, ts) {
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
export function drawPitch(ctx, m) {
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
export function drawNets(ctx, m) {                                   // nets in the colour of the team defending them, over the ball and players
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
const ME = "rgba(222,226,232,0.6)", ME_SOLID = "#dee2e8";        // the controlled player's ring and off-screen badge
export function drawPlayers(ctx, M, m, a, b, L, f) {
  M.me = null;
  m.players.forEach((pl, i) => {
    if (2 * i + 1 >= b.p.length) return;
    const x = L(a.p[2 * i], b.p[2 * i]), y = L(a.p[2 * i + 1], b.p[2 * i + 1]), r = pl.r, fl = b.h[i] || 0, kit = m.teams[pl.team];
    if (fl & 1) {                                             // you: a translucent light grey ring around the player (off screen: drawOffscreen)
      M.me = { x, y, pl };
      ctx.beginPath(); ctx.arc(x, y, r + 6, 0, 2 * Math.PI); ctx.lineWidth = 3; ctx.strokeStyle = ME; ctx.stroke();
    } else if (pl.uid === f.nx && f.st !== 2) {               // who the next Q picks: a thin dashed ring, a bit brighter inside the 1 s window
      ctx.save(); ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.arc(x, y, r + 5, 0, 2 * Math.PI);
      ctx.lineWidth = 1; ctx.strokeStyle = f.nw ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.45)"; ctx.stroke(); ctx.restore();
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
export function drawOffscreen(ctx, M, m, sp, W, H) {
  const pad = 30, top = TOP + 10, e = 12, b = M.bug, c = M.pzCard;
  const under = (q) => q && sp[0] > q.x - 14 && sp[0] < q.x + q.w + 14 && sp[1] < q.y + q.h + 14;
  if (sp[0] >= e && sp[0] <= W - e && sp[1] >= e && sp[1] <= H - e && !under(b) && !under(c)) return;
  const cx = W / 2, cy = H / 2, dx = sp[0] - cx, dy = sp[1] - cy;
  const k = Math.min(Math.abs((W / 2 - pad) / (dx || 1e-6)), Math.abs((H / 2 - pad) / (dy || 1e-6)));
  const x = cx + dx * k, y = Math.max(c && x > c.x - 30 ? c.y + c.h + 27 : top, cy + dy * k), ang = Math.atan2(dy, dx);
  ctx.save(); ctx.translate(x, y);
  ctx.beginPath(); ctx.arc(0, 0, 17, 0, 2 * Math.PI); ctx.fillStyle = "rgba(11,14,19,0.85)"; ctx.fill(); ctx.lineWidth = 2.5; ctx.strokeStyle = ME_SOLID; ctx.stroke();
  ctx.rotate(ang);
  ctx.beginPath(); ctx.moveTo(27, 0); ctx.lineTo(18, -8); ctx.lineTo(18, 8); ctx.closePath(); ctx.fillStyle = ME_SOLID; ctx.fill();
  ctx.restore();
  text(ctx, String(M.me.pl.number), x - 17, y + 5.5, "c", 34, 15, ME_SOLID, 0, "", 700);
}
export function roundRect(ctx, x, y, w, h, r, fill) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fillStyle = fill; ctx.fill(); }
// the TV scorebug, top left: crest CODE | score | CODE crest | clock
export function drawScorebug(ctx, M, m, f) {
  const x0 = 16, y0 = 14, h = 38, pad = 12, crest = 13, bar = 5;
  ctx.font = FONT(15, 700);
  const codes = m.teams.map((t) => (t.short || t.name.slice(0, 3)).toUpperCase());
  const cw = codes.map((c) => ctx.measureText(c).width);
  ctx.font = FONT(20, 800);
  const score = `${f.sc[0]} – ${f.sc[1]}`, sw = ctx.measureText(score).width;
  const clock = f.ot ? "OT " + clockText(f.ots) : clockText(f.tl);
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
export function drawHud(ctx, M, m, f, W, H, intro) {
  if (f.st === 1) drawGoalBanner(ctx, M, f, W, H);
  else if (intro > 0 && !M.p.session && f.st !== 2) drawKickoff(ctx, m, f, W, H, intro);
  drawParticles(ctx, M);
  drawScorebug(ctx, M, m, f);
  if (M.p.session && !M.error) drawPuzzleHud(ctx, M, f, W, H, intro);
  const ta = M.toast ? 1 - (performance.now() - M.toast.at) / 1400 : 0;                  // "Sound on / off" after N
  if (ta > 0) {
    ctx.save(); ctx.globalAlpha = Math.min(1, ta * 4);
    roundRect(ctx, W / 2 - 120, H - 64, 240, 36, 18, "rgba(11,14,19,0.85)");
    text(ctx, M.toast.text, W / 2 - 120, H - 40, "c", 240, 16, "#fff", 0, "", 700);
    ctx.restore();
  }
}
export function drawKickoff(ctx, m, f, W, H, intro) {
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
export const easeOutBack = (t) => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
// "GOAL" in big letters that pop in one by one, an accent band, team + scorer lines underneath
export function drawGoalBanner(ctx, M, f, W, H) {
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
