// The Game's sounds, all synthesised with Web Audio (no audio files). This file owns the audio graph and makes the noises;
// web/game/render.js decides when a match sound plays (sfx()), web/music.js plays the menu songs on the "music" bus and
// web/game.js plays the menu clicks (ui()). The Lab never makes a sound.
//   graph: every sound -> one of four buses (sfx, crowd, music, ui) -> master (on / off) -> limiter -> speakers,
//          and a send into one shared stadium reverb (a generated impulse response), so nothing sounds bone dry.
//   match: kicks (a pass and a shot differ), the ball off a post / the boards / the net / a body, players colliding, the
//          referee's whistle, a crowd that hums louder as the ball nears a goal (hype()), "ooh"s at near misses, a roar,
//          applause and fans' whistles at a goal and at full time, a short sting when your team scores.
// On / off (all sound) and music on / off are remembered in this browser ("soccer.sound", "soccer.music"). Browsers start
// audio only after a key press or click: unlock() is called from those.
"use strict";

const Sound = (() => {
  const KEY = "soccer.sound", MKEY = "soccer.music", MASTER = 0.85;
  const LEVEL = { sfx: 1, crowd: 1, music: 0.5, ui: 0.45 };
  let on = true, musicOn = true;
  try { on = localStorage.getItem(KEY) !== "off"; musicOn = localStorage.getItem(MKEY) !== "off"; } catch (e) {}
  let ac = null, master = null, verb = null, noise = null, claps = null, crowd = null;
  const bus = {}, listeners = new Set();

  // ---------- the graph ----------
  function init() {
    if (ac) return ac.state !== "closed";
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try { ac = new AC({ latencyHint: "interactive" }); } catch (e) { ac = null; return false; }
    const lim = ac.createDynamicsCompressor();                          // a limiter: loud moments do not clip
    lim.threshold.value = -10; lim.knee.value = 6; lim.ratio.value = 12; lim.attack.value = 0.003; lim.release.value = 0.25;
    lim.connect(ac.destination);
    master = ac.createGain(); master.gain.value = on ? MASTER : 0; master.connect(lim);
    for (const k of Object.keys(LEVEL)) { bus[k] = ac.createGain(); bus[k].gain.value = k === "music" && !musicOn ? 0 : LEVEL[k]; bus[k].connect(master); }
    verb = ac.createConvolver(); verb.buffer = impulse(2.4, 3.2);
    const wet = ac.createGain(); wet.gain.value = 0.55; verb.connect(wet); wet.connect(master);
    noise = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate);
    const d = noise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    ac.onstatechange = () => { for (const f of listeners) f(ac.state); };
    return true;
  }
  // a stadium-ish room: stereo noise that dies away and darkens as it goes (the smoothing grows along the tail)
  function impulse(sec, decay) {
    const sr = ac.sampleRate, n = Math.floor(sr * sec), b = ac.createBuffer(2, n, sr), pre = Math.floor(sr * 0.018);
    for (let c = 0; c < 2; c++) {
      const d = b.getChannelData(c);
      let lp = 0;
      for (let i = pre; i < n; i++) {
        const k = (i - pre) / (n - pre), a = 0.55 - 0.47 * k;
        lp += (Math.random() * 2 - 1 - lp) * a;
        d[i] = (lp / Math.sqrt(a)) * Math.pow(1 - k, decay) * 0.6;
      }
    }
    return b;
  }
  // many hand claps, scattered over 4 s of stereo (looped for longer applause)
  function clapBuffer() {
    if (claps) return claps;
    const sr = ac.sampleRate, n = sr * 4;
    claps = ac.createBuffer(2, n, sr);
    for (let c = 0; c < 2; c++) {
      const d = claps.getChannelData(c);
      for (let k = 0; k < 4 * 160; k++) {
        const at = Math.floor(Math.random() * n), len = Math.floor(sr * (0.006 + Math.random() * 0.01)), amp = 0.25 + Math.random() * 0.75;
        let lp = 0, tone = 0.3 + Math.random() * 0.5;
        for (let i = 0; i < len * 4; i++) {
          lp += (Math.random() * 2 - 1 - lp) * tone;
          d[(at + i) % n] += lp * amp * Math.exp(-i / len);
        }
      }
      for (let i = 0; i < n; i++) d[i] *= 0.35;
    }
    return claps;
  }
  // call from a key press / click (or right after one): browsers only let a page start audio then. Resolves once it runs.
  function unlock() {
    if (!init()) return Promise.resolve(false);
    if (ac.state === "suspended") return ac.resume().then(() => true, () => false);
    return Promise.resolve(ac.state === "running");
  }
  const ready = () => on && ac && ac.state === "running";
  const running = () => !!ac && ac.state === "running";

  // ---------- building blocks ----------
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rnd = (a, b) => a + Math.random() * (b - a);
  // a gain into a bus, panned -1 (left) .. 1 (right), with `wet` of it sent to the reverb
  function out(name = "sfx", pan = 0, wet = 0) {
    const g = ac.createGain();
    if (ac.createStereoPanner && pan) { const p = ac.createStereoPanner(); p.pan.value = clamp(pan, -1, 1); g.connect(p); p.connect(bus[name]); }
    else g.connect(bus[name]);
    if (wet > 0) send(g, wet);
    return g;
  }
  function send(node, amt) { const g = ac.createGain(); g.gain.value = amt; node.connect(g); g.connect(verb); return g; }
  function env(p, t, peak, attack, decay) {
    p.setValueAtTime(0.0001, t);
    p.exponentialRampToValueAtTime(Math.max(peak, 0.0002), t + attack);
    p.exponentialRampToValueAtTime(0.0001, t + attack + decay);
  }
  // an oscillator from f0 to f1 (exponential glide over `glide` s, default the whole sound) with a percussive envelope
  function tone(type, f0, f1, t, dur, peak, dest, attack = 0.003, glide = dur) {
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = type; o.frequency.setValueAtTime(f0, t);
    if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + glide);
    env(g.gain, t, peak, attack, dur); o.connect(g); g.connect(dest); o.start(t); o.stop(t + attack + dur + 0.05);
    return o;
  }
  function noiseSrc(t, dur) { const s = ac.createBufferSource(); s.buffer = noise; s.loop = true; s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05); return s; }
  // filtered noise with a percussive envelope; f1 (optional) sweeps the filter
  function burst(t, dur, type, f0, q, peak, dest, attack = 0.001, f1 = f0) {
    const s = noiseSrc(t, attack + dur), f = ac.createBiquadFilter(), g = ac.createGain();
    f.type = type; f.Q.value = q; f.frequency.setValueAtTime(f0, t);
    if (f1 !== f0) f.frequency.exponentialRampToValueAtTime(f1, t + attack + dur);
    env(g.gain, t, peak, attack, dur); s.connect(f); f.connect(g); g.connect(dest);
  }
  // a short dip of one bus (the crowd under the whistle, the music under a sting)
  function duck(name, to, hold) {
    const p = bus[name].gain, t = ac.currentTime, lvl = name === "music" && !musicOn ? 0 : LEVEL[name];
    p.cancelScheduledValues(t); p.setValueAtTime(p.value, t); p.linearRampToValueAtTime(lvl * to, t + 0.05);
    p.setValueAtTime(lvl * to, t + hold); p.linearRampToValueAtTime(lvl, t + hold + 0.6);
  }

  // ---------- the ball ----------
  // a foot on the ball: s = 0..1 how hard. A pass is a soft "tup"; a shot a deeper thump, a sharp leather crack and air.
  function kick(s = 0.7, pan = 0) {
    if (!ready()) return;
    const t = ac.currentTime + 0.004, o = out("sfx", pan, 0.06 + 0.12 * s), r = rnd(0.9, 1.12);
    tone("sine", (120 + 50 * s) * r, 45, t, 0.09 + 0.08 * s, 0.22 + 0.5 * s, o, 0.003, 0.09);       // the foot's thump
    tone("triangle", 420 * r, 190, t, 0.035 + 0.02 * s, 0.12 + 0.18 * s, o, 0.002);                  // the ball's hollow body
    burst(t, 0.012 + 0.02 * s, "bandpass", (1700 + 1400 * s) * r, 0.8, 0.18 + 0.35 * s, o);         // leather
    if (s > 0.55) burst(t, 0.006, "highpass", 5000, 0.7, 0.1 + 0.25 * s, o);                         // the crack of a strike
    if (s > 0.8) whoosh(t + 0.02, pan, s);
  }
  // air past a hard shot
  function whoosh(t, pan, s) { burst(t, 0.32, "bandpass", 2600, 1.6, 0.05 * s, out("sfx", pan, 0.15), 0.07, 700); }
  // the ball off something: "post" rings like a metal tube, "wall" (the boards) a hollow wooden knock, "net" a swish,
  // "body" (a player) a soft thud
  function bounce(kind, s = 0.6, pan = 0) {
    if (!ready()) return;
    const t = ac.currentTime + 0.004;
    if (kind === "post") {
      const o = out("sfx", pan, 0.4), base = rnd(560, 660);
      for (const [ratio, a, d] of [[1, 0.32, 1.2], [2.32, 0.2, 0.85], [4.25, 0.12, 0.55], [6.63, 0.07, 0.35], [9.38, 0.04, 0.2]])
        tone("sine", base * ratio * rnd(0.995, 1.005), base * ratio, t, d * (0.6 + 0.4 * s), a * s, o, 0.001);
      burst(t, 0.012, "highpass", 3500, 0.7, 0.35 * s, o);
      tone("sine", 130, 70, t, 0.08, 0.3 * s, o);
      return;
    }
    if (kind === "net") {
      const o = out("sfx", pan, 0.25);
      burst(t, 0.42, "bandpass", 3800, 0.9, 0.32 * s + 0.08, o, 0.015, 800);
      burst(t + 0.03, 0.25, "highpass", 6000, 0.5, 0.06 * s, o, 0.02);
      tone("sine", 95, 55, t, 0.14, 0.3 * s, o);
      return;
    }
    if (kind === "wall") {
      const o = out("sfx", pan, 0.18), f = rnd(190, 240);
      burst(t, 0.11, "bandpass", f, 5, 1.1 * s, o);
      tone("triangle", f * 0.8, f * 0.55, t, 0.09, 0.35 * s, o);
      burst(t + 0.002, 0.03, "bandpass", 1100, 1.5, 0.22 * s, o);
      burst(t + rnd(0.03, 0.045), 0.05, "bandpass", f * 1.6, 4, 0.25 * s, o);               // the board rattles
      return;
    }
    const o = out("sfx", pan, 0.08);
    tone("sine", rnd(170, 200), 90, t, 0.07, 0.3 * s + 0.05, o);
    burst(t, 0.04, "lowpass", 900, 0.7, 0.25 * s + 0.05, o);
  }
  // two players running into each other: a muffled body bump and a scuff of studs
  function tackle(s = 0.6, pan = 0) {
    if (!ready()) return;
    const t = ac.currentTime + 0.004, o = out("sfx", pan, 0.1);
    burst(t, 0.09, "lowpass", 420, 0.8, 0.45 * s, o);
    tone("sine", 88, 55, t, 0.1, 0.32 * s, o);
    burst(t + 0.01, 0.1, "bandpass", 3200, 1.2, 0.05 * s, o, 0.01, 1800);
  }

  // ---------- the referee ----------
  // a pea whistle: two close tones (they beat) with a fast trill and a bit of breath; blasts = [[start, length], ...] in s
  function whistle(blasts = [[0, 0.32]]) {
    if (!ready()) return;
    const t0 = ac.currentTime + 0.02, o = out("sfx", 0, 0.3), end = blasts[blasts.length - 1];
    duck("crowd", 0.55, end[0] + end[1]);
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

  // ---------- the crowd ----------
  // two beds of filtered noise (left and right stands) with a slow swell, and two "babble" layers whose band wanders like
  // voices. hype(x) sets how excited they are (0 = midfield, 1 = the ball in front of a goal); roar() / ooh() / applause() on top.
  const MURMUR = 0.05;
  function crowdOn() {
    if (!init() || crowd) return;
    const t = ac.currentTime, g = ac.createGain(), C = { g, lv: [], bp: [], lp: [], stop: [], hype: 0 };
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(1, t + 2); g.connect(bus.crowd); send(g, 0.3);
    const lfo = (f, amt, param) => { const o = ac.createOscillator(), d = ac.createGain(); o.frequency.value = f; d.gain.value = amt; o.connect(d); d.connect(param); o.start(); C.stop.push(o); };
    for (const side of [-1, 1]) {
      const n = ac.createBufferSource(); n.buffer = noise; n.loop = true; n.start(t, side < 0 ? 0 : 0.9); C.stop.push(n);
      const bp = ac.createBiquadFilter(), lp = ac.createBiquadFilter(), lv = ac.createGain(), p = ac.createStereoPanner ? ac.createStereoPanner() : null;
      bp.type = "bandpass"; bp.frequency.value = 450; bp.Q.value = 0.55; lp.type = "lowpass"; lp.frequency.value = 1250;
      lv.gain.value = MURMUR;
      lfo(rnd(0.07, 0.16), MURMUR * 0.3, lv.gain);
      n.connect(bp); bp.connect(lp); lp.connect(lv);
      if (p) { p.pan.value = side * 0.75; lv.connect(p); p.connect(g); } else lv.connect(g);
      // the babble: a narrow band that wanders 450..1100 Hz with a flutter, like many voices
      const bb = ac.createBiquadFilter(), bg = ac.createGain();
      bb.type = "bandpass"; bb.frequency.value = 760; bb.Q.value = 2.4; bg.gain.value = MURMUR * 0.6;
      lfo(rnd(0.6, 1.1), 260, bb.frequency); lfo(rnd(0.27, 0.45), 120, bb.frequency); lfo(rnd(1.8, 2.9), MURMUR * 0.25, bg.gain);
      n.connect(bb); bb.connect(bg);
      if (p) bg.connect(p); else bg.connect(g);
      C.lv.push(lv.gain, bg.gain); C.bp.push(bp.frequency); C.lp.push(lp.frequency);
    }
    crowd = C;
  }
  function crowdOff() {
    if (!crowd) return;
    const c = crowd, t = ac.currentTime; crowd = null;
    c.g.gain.cancelScheduledValues(t); c.g.gain.setValueAtTime(c.g.gain.value, t); c.g.gain.linearRampToValueAtTime(0.0001, t + 0.4);
    for (const s of c.stop) s.stop(t + 0.5);
  }
  function setCrowd(level, bright, t, tc) {
    const c = crowd;
    c.lv.forEach((p, i) => p.setTargetAtTime(level * (i % 2 ? 0.6 : 1), t, tc));
    for (const p of c.bp) p.setTargetAtTime(450 + 300 * bright, t, tc);
    for (const p of c.lp) p.setTargetAtTime(1250 + 2200 * bright, t, tc);
  }
  // 0..1: the crowd follows it over about half a second (ignored for a while after a roar)
  function hype(x) {
    if (!ac || !crowd || ac.currentTime < (crowd.hold || 0)) return;
    x = clamp(x, 0, 1);
    if (Math.abs(x - crowd.hype) < 0.03) return;
    crowd.hype = x;
    setCrowd(MURMUR * (1 + 2.4 * x * x), x, ac.currentTime, 0.45);
  }
  // a choir of n voices through two formant filters: "aah" (roar) or "ooh" (a near miss); slide bends the formants
  function voices(t, dur, f1, f2, peak, slide, n, pitchUp) {
    const g = ac.createGain(), a = ac.createBiquadFilter(), b = ac.createBiquadFilter();
    a.type = b.type = "bandpass"; a.Q.value = 2.2; b.Q.value = 3.5;
    a.frequency.setValueAtTime(f1, t); a.frequency.linearRampToValueAtTime(f1 * slide, t + dur);
    b.frequency.setValueAtTime(f2, t); b.frequency.linearRampToValueAtTime(f2 * slide, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + Math.min(0.35, dur * 0.3));
    g.gain.setTargetAtTime(0.0001, t + dur * 0.45, dur * 0.25);
    const mix = ac.createGain(); mix.gain.value = 1; mix.connect(a); mix.connect(b); a.connect(g); b.connect(g);
    g.connect(bus.crowd); send(g, 0.45);
    for (let i = 0; i < n; i++) {
      const o = ac.createOscillator(), og = ac.createGain(), f = rnd(120, 330), vib = ac.createOscillator(), vd = ac.createGain();
      o.type = "sawtooth"; o.frequency.setValueAtTime(f, t); o.frequency.linearRampToValueAtTime(f * (pitchUp ? 1.18 : 0.86), t + dur);
      vib.frequency.value = rnd(4, 6.5); vd.gain.value = f * 0.012; vib.connect(vd); vd.connect(o.frequency);
      og.gain.value = 0.05; o.connect(og); og.connect(mix);
      const st = t + rnd(0, 0.12); o.start(st); vib.start(st); o.stop(t + dur * 1.8); vib.stop(t + dur * 1.8);
    }
    const s = noiseSrc(t, dur * 1.8), ng = ac.createGain(); ng.gain.value = 0.5; s.connect(ng); ng.connect(mix);
  }
  function roar(big = 1) {
    if (!ready()) return;
    const t = ac.currentTime;
    if (crowd) {
      crowd.hold = t + 3.5; crowd.hype = 0.4;
      for (const p of [...crowd.lv, ...crowd.bp, ...crowd.lp]) { p.cancelScheduledValues(t); p.setValueAtTime(p.value, t); }
      setCrowd(MURMUR * (4 + 4 * big), 1, t, 0.12);
      setCrowd(MURMUR * 1.6, 0.4, t + 2.2, 1.2);
    }
    voices(t, 3.2, 750, 1200, 0.5 + 0.4 * big, 1.08, 10, true);
    applause(3.5, 0.5 + 0.5 * big, 1.1);
    fans(Math.round(1 + 2 * big), 0.4);
  }
  function ooh(amt = 0.8) {
    if (!ready()) return;
    voices(ac.currentTime, 1.7, 430, 880, 0.85 * amt, 0.8, 9, false);
  }
  function applause(dur = 3, amt = 0.7, delay = 0) {
    if (!ready()) return;
    const t = ac.currentTime + delay, s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = clapBuffer(); s.loop = true; f.type = "bandpass"; f.frequency.value = 1900; f.Q.value = 0.45;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(1.5 * amt, t + 0.35);
    g.gain.setValueAtTime(1.5 * amt, t + dur * 0.5); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f); f.connect(g); g.connect(bus.crowd); send(g, 0.35); s.start(t, Math.random() * 3); s.stop(t + dur + 0.1);
  }
  // fans whistling through their fingers: a rising then falling sine, here and there in the stands
  function fans(n = 2, delay = 0) {
    if (!ready()) return;
    for (let i = 0; i < n; i++) {
      const t = ac.currentTime + delay + rnd(0, 1.6), f = rnd(2100, 3000), len = rnd(0.35, 0.8), o = out("crowd", rnd(-0.9, 0.9), 0.5);
      const osc = ac.createOscillator(), g = ac.createGain();
      osc.frequency.setValueAtTime(f * 0.8, t); osc.frequency.exponentialRampToValueAtTime(f * 1.12, t + len * 0.35);
      osc.frequency.exponentialRampToValueAtTime(f * 0.85, t + len);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.035, t + 0.05);
      g.gain.setValueAtTime(0.035, t + len * 0.7); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
      osc.connect(g); g.connect(o); osc.start(t); osc.stop(t + len + 0.05);
    }
  }
  // ---------- the big moments ----------
  // a goal: the roar (bigger when it is yours) and, for your goal, a short rising brass sting with a cymbal
  function goal(mine = true) {
    if (!ready()) return;
    roar(mine ? 1 : 0.55);
    if (!mine) return;
    const t = ac.currentTime + 0.05, o = out("sfx", 0, 0.35), lp = ac.createBiquadFilter();
    lp.type = "lowpass"; lp.Q.value = 1.2; lp.frequency.setValueAtTime(900, t); lp.frequency.linearRampToValueAtTime(4200, t + 0.45);
    lp.connect(o);
    const notes = [[67, 0, 0.12], [71, 0.1, 0.12], [74, 0.2, 0.12], [79, 0.3, 0.9], [74, 0.3, 0.9], [71, 0.3, 0.9]];
    for (const [m, st, d] of notes) for (const det of [-8, 8]) {
      const osc = ac.createOscillator(), g = ac.createGain();
      osc.type = "sawtooth"; osc.frequency.value = 440 * Math.pow(2, (m - 69) / 12); osc.detune.value = det;
      g.gain.setValueAtTime(0.0001, t + st); g.gain.exponentialRampToValueAtTime(0.07, t + st + 0.02);
      g.gain.setValueAtTime(0.07, t + st + d * 0.6); g.gain.exponentialRampToValueAtTime(0.0001, t + st + d);
      osc.connect(g); g.connect(lp); osc.start(t + st); osc.stop(t + st + d + 0.05);
    }
    burst(t + 0.3, 1.3, "highpass", 5500, 0.6, 0.16, o, 0.003);
  }
  function fulltime() {
    if (!ready()) return;
    voices(ac.currentTime, 2.8, 700, 1150, 0.4, 1.04, 8, true);
    applause(5, 0.8, 0.2);
    fans(4, 0.3);
  }

  // ---------- the menus ----------
  // "move" (the focus moved), "select" (opened something), "back", "toggle"
  function ui(kind = "move") {
    if (!ready()) return;
    const t = ac.currentTime + 0.002, o = out("ui", 0, 0.12);
    if (kind === "move") { tone("sine", rnd(1180, 1260), 1100, t, 0.045, 0.14, o, 0.002); return; }
    const seq = { select: [[76, 0], [83, 0.06]], back: [[79, 0], [72, 0.06]], toggle: [[81, 0]] }[kind] || [[76, 0]];
    for (const [m, st] of seq) {
      const f = 440 * Math.pow(2, (m - 69) / 12);
      tone("triangle", f, f, t + st, 0.12, 0.2, o, 0.003);
      tone("sine", f * 2, f * 2, t + st, 0.06, 0.05, o, 0.002);
    }
  }

  // ---------- state ----------
  function pause(p) { if (!ac) return; if (p) ac.suspend().catch(() => {}); else ac.resume().catch(() => {}); }
  function ramp(p, v) { const t = ac.currentTime; p.cancelScheduledValues(t); p.setValueAtTime(p.value, t); p.linearRampToValueAtTime(v, t + 0.15); }
  function setOn(v) {
    on = !!v;
    try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (e) {}
    if (master) ramp(master.gain, on ? MASTER : 0);
    for (const f of listeners) f(ac ? ac.state : "none");
    return on;
  }
  function setMusic(v) {
    musicOn = !!v;
    try { localStorage.setItem(MKEY, musicOn ? "on" : "off"); } catch (e) {}
    if (bus.music) ramp(bus.music.gain, musicOn ? LEVEL.music : 0);
    for (const f of listeners) f(ac ? ac.state : "none");
    return musicOn;
  }

  return { unlock, kick, bounce, tackle, whistle, WHISTLE, crowdOn, crowdOff, hype, roar, ooh, applause, fans, goal, fulltime, ui,
    pause, setOn, toggle: () => setOn(!on), setMusic, toggleMusic: () => setMusic(!musicOn), duck,
    get on() { return on; }, get musicOn() { return musicOn; }, get running() { return running(); },
    get state() { return ac ? ac.state : "none"; },                                   // "running" once audio is unlocked (for tests)
    // for web/music.js: the context, a bus, the reverb send, the noise buffer; onChange(f): f() after a state / switch change
    ctx: () => (init() ? ac : null), bus: (k) => bus[k], send, noise: () => noise, onChange: (f) => listeners.add(f) };
})();
