// The menu music of the Game area: four short songs synthesised with Web Audio (no audio files) by a small step sequencer,
// played on web/sound.js's "music" bus. They play on every Game page except the match itself (the crowd takes over there) and
// never in the Lab: web/game.js calls play() / stop() as the routes change, web/lab/app.js stop() when the Lab opens.
// A song is data (SONGS): tempo, key, scale, one chord per bar, 16-step patterns for the drums, bass, keys and arpeggio, a
// melody in scale degrees and a form (sections that switch the parts on and off). After its form a song hands over to another.
//   melody tokens (one per 16th): 1..7 a scale degree (' an octave up, , an octave down), - hold the note, . rest
//   bass tokens (bass.vol: its level, 1 = default): R root, O root an octave up, 5 fifth, 3 the chord's third, 7 its seventh, - hold, . rest
//   arpeggio tokens: 0..4 the chord's notes from the bottom, . rest;  keys tokens: x play the chord, - hold, . rest
//   drum tokens: x hit, X accent, o soft, . rest;  form parts: k kick, s snare, c clap, h hat, o open hat, b bass, p keys,
//   a arpeggio, l lead
"use strict";

const Music = (() => {
  const MAJOR = [0, 2, 4, 5, 7, 9, 11], MINOR = [0, 2, 3, 5, 7, 8, 10], DORIAN = [0, 2, 3, 5, 7, 9, 10];
  const SONGS = [
    { name: "Kickoff", bpm: 120, key: 60, scale: MAJOR, swing: 0, pump: true,
      chords: ["C", "G", "Am", "F"],
      drums: { k: "x...x...x...x...", c: "....x.......x...", h: "o.o.o.o.o.o.o.o.", o: "..x...x...x...x." },
      bass: { pat: "..R...R...R.R.O.", cut: 900 },
      keys: { inst: "pad" }, arp: { pat: "0.2.1.3.0.2.1.3.", inst: "pluck" },
      lead: { inst: "lead", oct: 12, mel: [
        "5 - - 3 - - 1 - 2 - 3 - 5 - - -", "5 - - 2 - - 7, - 2 - 4 - 2 - - -", "3 - - 1 - - 6, - 1 - 3 - 6 - - -", "6 - 5 - 4 - 3 - 1 - - - . . . .",
        "5 - - 3 - - 1' - - - 7 - 5 - - -", "7 - - 5 - - 2' - - - 1' - 7 - 5 -", "6 - - - 1' - 6 - 5 - 3 - 5 - - -", "4 - - - 3 - - - 2 - - - 1 - - -"] },
      form: [[4, "hopa"], [8, "kchobpl"], [4, "hopab"], [8, "kchobpal"], [4, "khp"]] },
    { name: "Golden Hour", bpm: 84, key: 65, scale: MAJOR, swing: 0.2, crackle: true,
      chords: ["Bbmaj7", "Am7", "Gm7", "C7"],
      drums: { k: "x.....x...x.....", s: "....x.......x...", h: "x.o.x.o.x.o.x.oo" },
      bass: { pat: "R-----..R---5-..", cut: 520, vol: 0.5 },
      keys: { inst: "ep", pat: "x-------..x-----" },
      lead: { inst: "ep", oct: 0, mel: [
        "3' - - - - - 1' - 6 - - - 4 - - -", "5 - - - 3 - - - 2 - 3 - - - - -", "4 - - - 2 - - - 1 - - - 6, - - -", "7, - - - 2 - - - 5 - 4 - 3 - 2 -",
        "6 - 1' - 3' - - - 2' - 1' - 6 - - -", "5 - - - - - 3 - 5 - 7 - - - - -", "6 - - - 4 - - - 2 - 4 - 6 - - -", "5 - - - - - - - . . . . . . . ."] },
      form: [[4, "hpb"], [8, "kshbpl"], [4, "khpb"], [8, "kshbpl"], [4, "hp"]] },
    { name: "Terrace", bpm: 126, key: 57, scale: MINOR, swing: 0, pump: true,
      chords: ["Am", "F", "C", "G"],
      drums: { k: "x...x...x...x...", c: "....x.......x...", h: "xoxoxoxoxoxoxoxo" },
      bass: { pat: "R.R.O.R.R.R.O.R.", cut: 1300 },
      keys: { inst: "pad" }, arp: { pat: "0.1.2.1.0.1.2.1.", inst: "pluck" },
      lead: { inst: "lead", oct: 12, mel: [
        "5 - - - 5 - 3 - 5 - 6 - 5 - 3 -", "1' - - - 6 - - - 5 - - - 3 - - -", "5 - - - 5 - 3 - 5 - 7 - 1' - 7 -", "7 - - - 5 - - - 4 - - - 2 - - -",
        "1' - - - 7 - 5 - 1' - - - 7 - 5 -", "6 - - - 5 - 3 - 1 - - - 3 - - -", "3 - 5 - 7 - 5 - 3 - 5 - 7 - 1' -", "2' - - - 1' - - - 7 - - - 5 - - -"] },
      form: [[4, "khap"], [8, "kchbpl"], [4, "hpa"], [8, "kchbpal"], [4, "kchbp"]] },
    { name: "Sunday League", bpm: 104, key: 62, scale: DORIAN, swing: 0.12,
      chords: ["Dm7", "G7", "Dm7", "G7"],
      drums: { k: "x..x..x...x..x..", s: "....x..o....x...", h: "xoxoxoxoxoxoxoxo" },
      bass: { pat: "R..R..O.R.R...7.", cut: 1100 },
      keys: { inst: "stab", pat: "..x...x...x..x.." },
      lead: { inst: "lead", oct: 12, mel: [
        ". . 5 - 7 - 5 - 3 - 1 - . . 3 4", "6 - - - 4 - 6 - 1' - - - 6 - - -", ". . 5 - 7 - 1' - 7 - 5 - 3 - 5 -", "4 - - - - - 3 - 1 - - - . . . .",
        "1' - . 1' 7 - 5 - 7 - . 7 5 - 3 -", "4 - 6 - 1' - 6 - 4 - - - 3 - 1 -", "5 - - 5 7 - 5 - 3 - 5 - 7 - 1' -", "6 - - - - - - - 4 - - - . . . ."] },
      form: [[4, "khbs"], [8, "kshbpl"], [4, "khbp"], [8, "kshbpl"], [4, "kshb"]] },
  ];
  const NOTE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const QUAL = { "": [0, 4, 7], m: [0, 3, 7], "7": [0, 4, 7, 10], maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10], sus4: [0, 5, 7], add9: [0, 4, 7, 14] };
  function chord(name) {
    const m = /^([A-G])([#b]?)(.*)$/.exec(name);
    return { root: (NOTE[m[1]] + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0) + 12) % 12, iv: QUAL[m[3]] || QUAL[""] };
  }
  const win = (n, lo) => lo + (((n - lo) % 12) + 12) % 12;                 // the note n moved into [lo, lo + 12)
  const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);
  const tokens = (s) => s.trim().split(/\s+/);
  // a melody bar to notes: [[step, midi, steps held], ...]
  function melody(bar, S) {
    const tk = tokens(bar), out = [];
    tk.forEach((x, i) => {
      const m = /^([1-7])(['’,]*)$/.exec(x);
      if (!m) return;
      let n = 1; while (tk[i + n] === "-") n++;
      const deg = Number(m[1]) - 1, sh = [...m[2]].reduce((a, c) => a + (c === "," ? -12 : 12), 0);
      out.push([i, S.key + S.lead.oct + S.scale[deg] + sh, n]);
    });
    return out;
  }
  for (const S of SONGS) {                                                   // parse once (and say so if a bar is malformed)
    S.ch = S.chords.map(chord);
    S.mel = S.lead.mel.map((b) => { if (tokens(b).length !== 16) console.warn("music: a melody bar of", S.name, "is not 16 steps:", b); return melody(b, S); });
    S.bars = S.form.reduce((a, f) => a + f[0], 0);
  }

  let ac = null, out = null, timer = 0, cur = null, want = false, startT = 0, last = -1, hidden = false;
  const LOOK = 0.2, TICK = 40;

  // ---------- one song playing ----------
  function begin(i, at) {
    const S = SONGS[i], g = ac.createGain(), pump = ac.createGain(), dl = ac.createDelay(1), fb = ac.createGain(), dlf = ac.createBiquadFilter(), dlo = ac.createGain();
    g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(1, at + 1.2); g.connect(out);
    pump.connect(g);
    const beat = 60 / S.bpm;
    dl.delayTime.value = beat * 0.75; fb.gain.value = 0.32; dlf.type = "lowpass"; dlf.frequency.value = 2400; dlo.gain.value = 0.5;
    dl.connect(dlf); dlf.connect(fb); fb.connect(dl); dlf.connect(dlo); dlo.connect(g);
    Sound.send(g, 0.18);
    last = i;
    return { i, S, g, pump, dl, step: 0, next: at, st: beat / 4 };
  }
  function end(c, fade = 1) {
    if (!c) return;
    const t = ac.currentTime;
    c.g.gain.cancelScheduledValues(t); c.g.gain.setValueAtTime(Math.max(c.g.gain.value, 0.0001), t); c.g.gain.exponentialRampToValueAtTime(0.0001, t + fade);
    setTimeout(() => { try { c.g.disconnect(); } catch (e) {} }, (fade + 3) * 1000);
  }
  function section(S, bar) {                                                 // [the section's parts, bar inside it, its length]
    let b = bar % S.bars;
    for (const [n, parts] of S.form) { if (b < n) return [parts, b, n]; b -= n; }
    return [S.form[0][1], 0, S.form[0][0]];
  }
  function tick() {
    if (!cur || !ac) return;
    while (cur.next < ac.currentTime + LOOK) {
      const c = cur, bar = Math.floor(c.step / 16);
      if (bar >= c.S.bars) {                                                 // the song is over: the next one, after a breath
        end(c, 0.5);
        cur = begin(pick(c.i), c.next + c.st * 4);
        continue;
      }
      play(c, c.step % 16, bar, c.next + (c.step % 2 ? c.S.swing * c.st : 0));
      c.step++; c.next += c.st;
    }
  }
  function pick(not) { let i; do i = Math.floor(Math.random() * SONGS.length); while (SONGS.length > 1 && i === not); return i; }

  // ---------- one 16th ----------
  function play(c, s, bar, t) {
    const S = c.S, [parts, inBar, len] = section(S, bar), has = (p) => parts.includes(p), D = S.drums, ch = S.ch[bar % S.ch.length];
    const fill = inBar === len - 1 && s >= 12 && (has("s") || has("c"));
    const hit = (pat) => pat && pat[s] !== "." && pat[s] !== undefined ? ({ x: 0.8, X: 1, o: 0.4 }[pat[s]] || 0.8) : 0;
    if (s === 0 && inBar === 0 && bar > 0 && has("k")) crash(c, t);
    let v;
    if (has("k") && (v = hit(D.k))) kickD(c, t, v);
    if (has("s") && (v = hit(D.s)) && !fill) snareD(c, t, v);
    if (has("c") && (v = hit(D.c)) && !fill) clapD(c, t, v);
    if (fill) snareD(c, t, 0.35 + 0.15 * (s - 12));
    if (has("h") && (v = hit(D.h))) hatD(c, t, v, false);
    if (has("o") && (v = hit(D.o))) hatD(c, t, v, true);
    if (S.crackle && Math.random() < 0.4) crackle(c, t);
    const st = c.st;
    if (has("b")) {
      const x = S.bass.pat[s];
      if (x && x !== "." && x !== "-") {
        let n = 1; while (S.bass.pat[s + n] === "-") n++;
        const iv = { R: 0, O: 12, 5: 7, 3: ch.iv[1], 7: ch.iv[3] ?? 10 }[x] ?? 0;
        bassI(c, t, win(ch.root, 33) + iv, n * st);
      }
    }
    const tones = ch.iv.map((iv) => win(ch.root + iv, 55)).sort((a, b) => a - b);
    if (has("p")) {
      if (S.keys.inst === "pad") { if (s === 0) padI(c, t, tones, 16 * st); }
      else {
        const x = S.keys.pat[s];
        if (x === "x") {
          let n = 1; while (S.keys.pat[s + n] === "-") n++;
          if (S.keys.inst === "ep") for (const m of tones) epI(c, t, m, n * st, 0.55);
          else for (const m of tones) stabI(c, t, m + 12);
        }
      }
    }
    if (has("a") && S.arp) {
      const x = S.arp.pat[s];
      if (x && x !== ".") { const k = Number(x), up = tones.map((m) => win(m, 67)).sort((a, b) => a - b); pluckI(c, t, up[k % up.length] + 12 * Math.floor(k / up.length), st * 1.5); }
    }
    if (has("l")) {
      const mel = S.mel[inBar % S.mel.length];
      for (const [i, m, n] of mel) if (i === s) (S.lead.inst === "ep" ? epI(c, t, m, n * st, 0.9) : leadI(c, t, m, n * st));
    }
  }

  // ---------- the instruments (all send into the song's gain c.g; bass, keys and arpeggio through c.pump) ----------
  function envG(t, peak, a, d, dest) { const g = ac.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + d); g.connect(dest); return g; }
  function osc(type, f, t, dur, dest, detune = 0) { const o = ac.createOscillator(); o.type = type; o.frequency.value = f; o.detune.value = detune; o.connect(dest); o.start(t); o.stop(t + dur + 0.1); return o; }
  function noise(t, dur, type, f, q, dest) {
    const s = ac.createBufferSource(), fl = ac.createBiquadFilter(); s.buffer = Sound.noise(); s.loop = true;
    fl.type = type; fl.frequency.value = f; fl.Q.value = q; s.connect(fl); fl.connect(dest); s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05);
  }
  function kickD(c, t, v) {
    const g = envG(t, 0.9 * v, 0.002, 0.3, c.g), o = osc("sine", 150, t, 0.35, g);
    o.frequency.setValueAtTime(150, t); o.frequency.exponentialRampToValueAtTime(46, t + 0.11);
    noise(t, 0.008, "highpass", 4000, 0.7, envG(t, 0.15 * v, 0.001, 0.008, c.g));
    if (c.S.pump) { const p = c.pump.gain; p.setValueAtTime(1, t); p.linearRampToValueAtTime(0.35, t + 0.01); p.linearRampToValueAtTime(1, t + 0.24); }
  }
  function snareD(c, t, v) {
    const g = envG(t, 0.35 * v, 0.001, 0.16, c.g); noise(t, 0.2, "bandpass", 1900, 0.7, g); Sound.send(g, 0.12);
    const o = osc("triangle", 190, t, 0.1, envG(t, 0.25 * v, 0.001, 0.08, c.g)); o.frequency.exponentialRampToValueAtTime(150, t + 0.08);
  }
  function clapD(c, t, v) {
    for (const d of [0, 0.011, 0.022]) noise(t + d, 0.012, "bandpass", 1300, 1.2, envG(t + d, 0.3 * v, 0.001, 0.01, c.g));
    const g = envG(t + 0.03, 0.28 * v, 0.002, 0.14, c.g); noise(t + 0.03, 0.16, "bandpass", 1300, 1.2, g); Sound.send(g, 0.2);
  }
  function hatD(c, t, v, open) { noise(t, open ? 0.25 : 0.05, "highpass", 7500, 0.7, envG(t, (open ? 0.1 : 0.12) * v, 0.001, open ? 0.2 : 0.035, c.g)); }
  function crash(c, t) { const g = envG(t, 0.1, 0.002, 1.3, c.g); noise(t, 1.4, "highpass", 5200, 0.5, g); Sound.send(g, 0.2); }
  function crackle(c, t) { const u = t + Math.random() * c.st; noise(u, 0.004, "highpass", 2500, 0.5, envG(u, 0.02 + Math.random() * 0.03, 0.0005, 0.003, c.g)); }
  function bassI(c, t, m, dur) {
    const f = ac.createBiquadFilter(), cut = c.S.bass.cut, d = Math.max(0.08, dur * 0.92);
    f.type = "lowpass"; f.Q.value = 5; f.frequency.setValueAtTime(cut * 2.2, t); f.frequency.exponentialRampToValueAtTime(cut * 0.5, t + 0.18);
    const g = ac.createGain(), pk = 0.3 * (c.S.bass.vol ?? 1); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(pk, t + 0.006);
    g.gain.setValueAtTime(pk, t + d - 0.05); g.gain.exponentialRampToValueAtTime(0.0001, t + d); f.connect(g); g.connect(c.pump);
    osc("sawtooth", hz(m), t, d, f); osc("sine", hz(m), t, d, g);
  }
  function padI(c, t, notes, dur) {
    const f = ac.createBiquadFilter(), g = ac.createGain();
    f.type = "lowpass"; f.frequency.setValueAtTime(700, t); f.frequency.linearRampToValueAtTime(1500, t + dur * 0.6); f.Q.value = 0.7;
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.045, t + 0.35); g.gain.setValueAtTime(0.045, t + dur - 0.1); g.gain.linearRampToValueAtTime(0.0001, t + dur + 0.5);
    f.connect(g); g.connect(c.pump); Sound.send(g, 0.4);
    for (const m of notes) for (const det of [-7, 7]) osc("sawtooth", hz(m), t, dur + 0.5, f, det);
  }
  // an electric piano: a sine bent by another at the same pitch whose depth dies away (bright attack, round sustain)
  function epI(c, t, m, dur, v) {
    const f0 = hz(m), car = ac.createOscillator(), mod = ac.createOscillator(), idx = ac.createGain(), d = dur + 0.4;
    const g = envG(t, 0.11 * v, 0.004, d, c.pump); Sound.send(g, 0.25);
    if (v > 0.8) { const x = ac.createGain(); x.gain.value = 0.25; g.connect(x); x.connect(c.dl); }   // the melody gets an echo
    car.frequency.value = f0; mod.frequency.value = f0; idx.gain.setValueAtTime(f0 * 1.6, t); idx.gain.exponentialRampToValueAtTime(f0 * 0.15, t + 0.5);
    mod.connect(idx); idx.connect(car.frequency); car.connect(g);
    car.start(t); mod.start(t); car.stop(t + d + 0.1); mod.stop(t + d + 0.1);
  }
  function stabI(c, t, m) {
    const f = ac.createBiquadFilter(); f.type = "lowpass"; f.Q.value = 3; f.frequency.setValueAtTime(3200, t); f.frequency.exponentialRampToValueAtTime(600, t + 0.12);
    f.connect(envG(t, 0.05, 0.003, 0.16, c.pump));
    osc("sawtooth", hz(m), t, 0.2, f); osc("square", hz(m), t, 0.2, f, 5);
  }
  function pluckI(c, t, m, dur) {
    const f = ac.createBiquadFilter(); f.type = "lowpass"; f.Q.value = 2; f.frequency.setValueAtTime(4200, t); f.frequency.exponentialRampToValueAtTime(700, t + 0.16);
    const g = envG(t, 0.06, 0.002, Math.max(0.15, dur), c.pump); f.connect(g);
    const x = ac.createGain(); x.gain.value = 0.45; g.connect(x); x.connect(c.dl);
    osc("square", hz(m), t, Math.max(0.15, dur) + 0.05, f);
  }
  function leadI(c, t, m, dur) {
    const f = ac.createBiquadFilter(), g = ac.createGain(), d = Math.max(0.1, dur * 0.95);
    f.type = "lowpass"; f.Q.value = 1.4; f.frequency.setValueAtTime(1800, t); f.frequency.exponentialRampToValueAtTime(3400, t + 0.04); f.frequency.exponentialRampToValueAtTime(2200, t + 0.3);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.075, t + 0.015); g.gain.exponentialRampToValueAtTime(0.055, t + 0.15);
    g.gain.setValueAtTime(0.055, t + d - 0.04); g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.12);
    f.connect(g); g.connect(c.g); Sound.send(g, 0.25);
    const x = ac.createGain(); x.gain.value = 0.3; g.connect(x); x.connect(c.dl);
    const vib = ac.createOscillator(), vd = ac.createGain(); vib.frequency.value = 5.5;
    vd.gain.setValueAtTime(0, t); vd.gain.linearRampToValueAtTime(0, t + 0.18); vd.gain.linearRampToValueAtTime(14, t + 0.45); vib.connect(vd);
    for (const [type, det] of [["sawtooth", -9], ["sawtooth", 9], ["triangle", 0]]) { const o = osc(type, hz(m), t, d + 0.15, f, det); vd.connect(o.detune); }
    vib.start(t); vib.stop(t + d + 0.25);
  }

  // ---------- control ----------
  function canPlay() { return want && !hidden && Sound.on && Sound.musicOn && Sound.running; }
  function startNow(i) {
    ac = Sound.ctx(); if (!ac) return;
    if (!out) out = Sound.bus("music");
    if (cur) end(cur, 1.2);
    cur = begin(i ?? pick(last), ac.currentTime + 0.1);
    if (!timer) timer = setInterval(tick, TICK);
    tick();
  }
  function halt(fade) {
    clearTimeout(startT); startT = 0;
    if (cur) end(cur, fade);
    cur = null;
    if (timer) { clearInterval(timer); timer = 0; }
  }
  // start (or keep) the music if it may play now; stop it if it may not. Called after every switch / route / unlock.
  function refresh() {
    if (!canPlay()) { if (cur || startT) halt(0.8); return; }
    if (cur || startT) return;
    startT = setTimeout(() => { startT = 0; if (canPlay() && !cur) startNow(); }, 350);   // a page that only flashes by stays quiet
  }
  document.addEventListener("visibilitychange", () => {
    hidden = document.hidden;
    if (hidden) halt(0.3);
    else refresh();
  });
  Sound.onChange(() => refresh());

  return {
    play() { want = true; refresh(); },                                       // the Game pages around a match
    stop(fade = 0.8) { want = false; halt(fade); },                          // a match, or the Lab
    next() { want = true; if (Sound.running && Sound.musicOn) startNow(); },   // another song now
    song(i) { want = true; if (Sound.running) startNow(i); },                // a given song (the sound test page)
    refresh,
    get songs() { return SONGS.map((s) => s.name); },
    get playing() { return cur ? cur.S.name : ""; },
  };
})();
