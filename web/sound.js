// Match sounds, all synthesised with Web Audio (no audio files): kicks, the ball off a post / a wall / a body, the referee's whistle,
// and a crowd that murmurs through the match and roars at a goal. web/game/render.js decides when (sfx()); this file only makes the noise.
// On / off is remembered in this browser ("soccer.sound"); the audio starts on the first match, which always follows a key press or click.
"use strict";

const Sound = (() => {
  const KEY = "soccer.sound";
  let on = true;
  try { on = localStorage.getItem(KEY) !== "off"; } catch (e) {}
  let ac = null, master = null, noise = null, crowd = null;

  function init() {
    if (ac) return ac.state !== "closed";
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try { ac = new AC(); } catch (e) { ac = null; return false; }
    const comp = ac.createDynamicsCompressor();
    comp.threshold.value = -14; comp.knee.value = 10; comp.ratio.value = 4;
    master = ac.createGain(); master.gain.value = on ? 0.8 : 0;
    master.connect(comp); comp.connect(ac.destination);
    noise = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate);
    const d = noise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return true;
  }
  // call from a key press / click (or right after one): browsers only let a page start audio then
  function unlock() { if (init() && ac.state === "suspended") ac.resume().catch(() => {}); }
  const ready = () => on && ac && ac.state === "running";

  function out(pan) {                                     // a gain into the master, panned -1 (left) .. 1 (right)
    const g = ac.createGain();
    if (ac.createStereoPanner && pan) { const p = ac.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, pan)); g.connect(p); p.connect(master); }
    else g.connect(master);
    return g;
  }
  function env(g, t, peak, attack, decay) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
  }
  function noiseSrc(t, dur) { const s = ac.createBufferSource(); s.buffer = noise; s.loop = true; s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05); return s; }

  // a foot on the ball: a low thump with a short leather "tok" on top; s = 0..1 how hard
  function kick(s = 0.7, pan = 0) {
    if (!ready()) return;
    const t = ac.currentTime, o = out(pan);
    const osc = ac.createOscillator(), g = ac.createGain();
    osc.frequency.setValueAtTime(170 + 40 * Math.random(), t); osc.frequency.exponentialRampToValueAtTime(55, t + 0.11);
    env(g, t, 0.9 * s, 0.004, 0.13); osc.connect(g); g.connect(o); osc.start(t); osc.stop(t + 0.2);
    const n = noiseSrc(t, 0.05), bp = ac.createBiquadFilter(), gn = ac.createGain();
    bp.type = "bandpass"; bp.frequency.value = 1500 + 600 * Math.random(); bp.Q.value = 1.2;
    env(gn, t, 0.5 * s, 0.002, 0.035); n.connect(bp); bp.connect(gn); gn.connect(o);
  }
  // the ball off something: "post" rings, "wall" (the boards, the net) is a dull thud, "body" a soft tap
  function bounce(kind, s = 0.6, pan = 0) {
    if (!ready()) return;
    const t = ac.currentTime, o = out(pan);
    if (kind === "post") {
      for (const [f, a, d] of [[880, 0.35, 0.5], [1347, 0.22, 0.35], [2211, 0.12, 0.25], [3080, 0.06, 0.15]]) {
        const osc = ac.createOscillator(), g = ac.createGain();
        osc.frequency.value = f * (0.99 + 0.02 * Math.random());
        env(g, t, a * s, 0.002, d); osc.connect(g); g.connect(o); osc.start(t); osc.stop(t + d + 0.05);
      }
      return;
    }
    const wall = kind === "wall", osc = ac.createOscillator(), g = ac.createGain(), lp = ac.createBiquadFilter();
    osc.type = "triangle"; lp.type = "lowpass"; lp.frequency.value = wall ? 700 : 1400;
    osc.frequency.setValueAtTime(wall ? 140 : 320, t); osc.frequency.exponentialRampToValueAtTime(wall ? 70 : 200, t + 0.06);
    env(g, t, (wall ? 0.6 : 0.3) * s, 0.003, wall ? 0.12 : 0.06);
    osc.connect(lp); lp.connect(g); g.connect(o); osc.start(t); osc.stop(t + 0.2);
  }
  // the referee's pea whistle: two close tones (they beat) with a fast trill and a bit of breath; blasts = [[start, length], ...] in s
  function whistle(blasts = [[0, 0.32]]) {
    if (!ready()) return;
    const t0 = ac.currentTime + 0.02, o = out(0);
    for (const [st, len] of blasts) {
      const t = t0 + st, g = ac.createGain();
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.16, t + 0.03);
      g.gain.setValueAtTime(0.16, t + len - 0.05); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
      const trill = ac.createGain(); trill.gain.value = 0.55;
      const lfo = ac.createOscillator(), depth = ac.createGain();
      lfo.frequency.value = 28 + 6 * Math.random(); depth.gain.value = 0.45; lfo.connect(depth); depth.connect(trill.gain);
      for (const f of [2750, 2795]) {
        const osc = ac.createOscillator(); osc.frequency.setValueAtTime(f * 0.97, t); osc.frequency.linearRampToValueAtTime(f, t + 0.05);
        osc.connect(trill); osc.start(t); osc.stop(t + len + 0.02);
      }
      const n = noiseSrc(t, len), bp = ac.createBiquadFilter(), gn = ac.createGain();
      bp.type = "bandpass"; bp.frequency.value = 2800; bp.Q.value = 3; gn.gain.value = 0.25;
      n.connect(bp); bp.connect(gn); gn.connect(trill);
      trill.connect(g); g.connect(o); lfo.start(t); lfo.stop(t + len + 0.02);
    }
  }
  const WHISTLE = { kickoff: [[0, 0.32]], overtime: [[0, 0.22], [0.32, 0.22]], fulltime: [[0, 0.32], [0.5, 0.32], [1.0, 0.95]] };

  // the crowd: filtered noise, quiet during play; roar() swells it and brightens it for a few seconds
  const MURMUR = 0.055;
  function crowdOn() {
    if (!ac || crowd) return;
    const n = ac.createBufferSource(); n.buffer = noise; n.loop = true;
    const bp = ac.createBiquadFilter(), lp = ac.createBiquadFilter(), g = ac.createGain();
    bp.type = "bandpass"; bp.frequency.value = 520; bp.Q.value = 0.6; lp.type = "lowpass"; lp.frequency.value = 1300;
    const lfo = ac.createOscillator(), depth = ac.createGain();       // a slow swell so it does not sound like a fan
    lfo.frequency.value = 0.13; depth.gain.value = MURMUR * 0.35; lfo.connect(depth); depth.connect(g.gain);
    g.gain.setValueAtTime(0.0001, ac.currentTime); g.gain.linearRampToValueAtTime(MURMUR, ac.currentTime + 1.5);
    n.connect(bp); bp.connect(lp); lp.connect(g); g.connect(master); n.start(); lfo.start();
    crowd = { n, lfo, g, bp, lp };
  }
  function crowdOff() {
    if (!crowd) return;
    const c = crowd, t = ac.currentTime; crowd = null;
    c.g.gain.cancelScheduledValues(t); c.g.gain.setValueAtTime(c.g.gain.value, t); c.g.gain.linearRampToValueAtTime(0.0001, t + 0.4);
    c.n.stop(t + 0.5); c.lfo.stop(t + 0.5);
  }
  function roar(big = 1) {
    if (!ready() || !crowd) return;
    const t = ac.currentTime, { g, bp, lp } = crowd, peak = 0.22 + 0.16 * big;
    for (const p of [g.gain, bp.frequency, lp.frequency]) { p.cancelScheduledValues(t); p.setValueAtTime(p.value, t); }
    g.gain.linearRampToValueAtTime(peak, t + 0.25); g.gain.setTargetAtTime(MURMUR, t + 1.8, 1.1);
    bp.frequency.linearRampToValueAtTime(900, t + 0.25); bp.frequency.setTargetAtTime(520, t + 1.8, 1.1);
    lp.frequency.linearRampToValueAtTime(3200, t + 0.25); lp.frequency.setTargetAtTime(1300, t + 1.8, 1.1);
  }

  function pause(p) { if (!ac) return; if (p) ac.suspend().catch(() => {}); else ac.resume().catch(() => {}); }
  function setOn(v) {
    on = !!v;
    try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (e) {}
    if (master) { const t = ac.currentTime; master.gain.cancelScheduledValues(t); master.gain.setValueAtTime(master.gain.value, t); master.gain.linearRampToValueAtTime(on ? 0.8 : 0, t + 0.15); }
    return on;
  }

  return { unlock, kick, bounce, whistle, WHISTLE, crowdOn, crowdOff, roar, pause, setOn, toggle: () => setOn(!on), get on() { return on; },
    get state() { return ac ? ac.state : "none"; } };                                  // "running" once audio is unlocked (for tests)
})();
