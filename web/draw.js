// Drawing shared by the game pages: colours, team logos and kits (a port of the Godot game's LogoDraw), star ratings.
// Logos are procedural: {shape: shield|circle|hex|diamond, pattern: solid|stripes|halves|chevron|band|quarters,
// symbol: none|star|bolt|crown|ring|cross, c1, c2, c3}.
"use strict";

const Draw = (() => {
  // ---------- colours (Godot Color semantics, components 0..1) ----------
  const rgb = (hex) => { const v = parseInt(String(hex).replace("#", "").slice(0, 6), 16); return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255]; };
  const css = (c, a = 1) => `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${a})`;
  const darkened = (c, k) => c.map((x) => x * (1 - k));
  const lightened = (c, k) => c.map((x) => x + (1 - x) * k);
  const mix = (a, b, k) => a.map((x, i) => x + (b[i] - x) * k);
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  const luminance = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];

  // a team's goal colour: the kit colour that stands out most from the pitch, brightened if it is still too close to it
  function goalColour(kit, pitch) {
    let best = kit[0], bestD = -1;
    for (const c of kit) { const d = dist(c, pitch); if (d > bestD + 0.08) { bestD = d; best = c; } }
    if (bestD < 0.5) best = mix(best, luminance(pitch) < 0.6 ? [1, 1, 1] : [0, 0, 0], 0.65);
    return best;
  }

  // ---------- logos ----------
  function shapePoints(shape, cx, cy, s) {
    const pts = [];
    if (shape === "circle") for (let i = 0; i < 40; i++) { const a = (2 * Math.PI * i) / 40; pts.push([cx + Math.cos(a) * s, cy + Math.sin(a) * s]); }
    else if (shape === "hex") for (let i = 0; i < 6; i++) { const a = (2 * Math.PI * i) / 6 + Math.PI / 6; pts.push([cx + Math.cos(a) * s, cy + Math.sin(a) * s]); }
    else if (shape === "diamond") for (const [x, y] of [[0, -1], [0.8, 0], [0, 1], [-0.8, 0]]) pts.push([cx + x * s, cy + y * s]);
    else for (const [x, y] of [[-0.9, -0.85], [0.9, -0.85], [0.9, 0.1], [0.55, 0.62], [0, 1], [-0.55, 0.62], [-0.9, 0.1]]) pts.push([cx + x * s, cy + y * s]);
    return pts;
  }
  const rect = (cx, cy, s, x0, y0, x1, y1) => [[cx + x0 * s, cy + y0 * s], [cx + x1 * s, cy + y0 * s], [cx + x1 * s, cy + y1 * s], [cx + x0 * s, cy + y1 * s]];
  function patternPolys(p, cx, cy, s) {
    switch (p) {
      case "stripes": return [rect(cx, cy, s, -0.62, -1.2, -0.28, 1.2), rect(cx, cy, s, 0.28, -1.2, 0.62, 1.2)];
      case "halves": return [rect(cx, cy, s, 0, -1.2, 1.2, 1.2)];
      case "band": return [rect(cx, cy, s, -1.2, -0.22, 1.2, 0.22)];
      case "quarters": return [rect(cx, cy, s, -1.2, -1.2, 0, 0), rect(cx, cy, s, 0, 0, 1.2, 1.2)];
      case "chevron": return [[[-1.2, 0], [0, -0.55], [1.2, 0], [1.2, 0.4], [0, -0.15], [-1.2, 0.4]].map(([x, y]) => [cx + x * s, cy + y * s])];
      default: return [];
    }
  }
  function path(ctx, pts, close = true) { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); if (close) ctx.closePath(); }
  function fillOutlined(ctx, pts, fill) {
    path(ctx, pts); ctx.fillStyle = fill; ctx.fill();
    ctx.lineWidth = 1.2; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.stroke();
  }
  function symbol(ctx, cx, cy, s, sym, col) {
    const P = (list) => list.map(([x, y]) => [cx + x * s, cy + y * s]);
    switch (sym) {
      case "star": { const pts = []; for (let i = 0; i < 10; i++) { const r = i % 2 === 0 ? s : s * 0.42, a = -Math.PI / 2 + (2 * Math.PI * i) / 10; pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); } fillOutlined(ctx, pts, col); break; }
      case "bolt": fillOutlined(ctx, P([[0.25, -1], [-0.6, 0.15], [-0.05, 0.15], [-0.3, 1], [0.65, -0.2], [0.1, -0.2]]), col); break;
      case "crown": fillOutlined(ctx, P([[-1, 0.7], [-1, -0.5], [-0.5, 0.1], [0, -0.8], [0.5, 0.1], [1, -0.5], [1, 0.7]]), col); break;
      case "ring":
        ctx.beginPath(); ctx.arc(cx, cy, s * 0.8, 0, 2 * Math.PI); ctx.lineWidth = s * 0.55; ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.stroke();
        ctx.lineWidth = s * 0.35; ctx.strokeStyle = col; ctx.stroke(); break;
      case "cross": fillOutlined(ctx, P([[-0.3, -1], [0.3, -1], [0.3, -0.3], [1, -0.3], [1, 0.3], [0.3, 0.3], [0.3, 1], [-0.3, 1], [-0.3, 0.3], [-1, 0.3], [-1, -0.3], [-0.3, -0.3]]), col); break;
    }
  }
  function logo(ctx, cx, cy, s, spec) {
    spec = spec || {};
    const c1 = "#" + (spec.c1 || "e56e56"), c2 = "#" + (spec.c2 || "ffffff"), c3 = "#" + (spec.c3 || "ffffff");
    const shape = shapePoints(spec.shape || "shield", cx, cy, s);
    path(ctx, shape); ctx.fillStyle = c1; ctx.fill();
    ctx.save(); path(ctx, shape); ctx.clip();
    for (const pp of patternPolys(spec.pattern || "solid", cx, cy, s)) { path(ctx, pp); ctx.fillStyle = c2; ctx.fill(); }
    ctx.restore();
    symbol(ctx, cx, cy - s * 0.02, s * 0.42, spec.symbol || "none", c3);
    path(ctx, shape); ctx.lineJoin = "round"; ctx.lineWidth = Math.max(1.5, s * 0.07); ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.stroke();
  }
  // a <canvas> with a team logo of `px` CSS pixels (sharp on high-density screens)
  function logoCanvas(spec, px, cls = "") {
    const cv = document.createElement("canvas"), dpr = window.devicePixelRatio || 1;
    cv.width = cv.height = Math.round(px * dpr); cv.style.width = cv.style.height = px + "px"; cv.className = "g-logo " + cls;
    const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
    logo(ctx, px / 2, px / 2, px * 0.46, spec);
    return cv;
  }
  // HTML of a logo placeholder; fill() turns every [data-logo] into a canvas (logos are drawn, not images)
  const logoTag = (team, px) => `<span class="g-logo-slot" data-logo="${team}" data-px="${px}" style="width:${px}px;height:${px}px"></span>`;
  function fillLogos(root, teamsById) {
    for (const el of root.querySelectorAll("[data-logo]")) {
      const t = teamsById[el.dataset.logo]; if (!t) continue;
      el.replaceWith(logoCanvas(t.logo, Number(el.dataset.px)));
    }
  }

  // ---------- kits (a disc with the team's pattern) ----------
  function kit(ctx, x, y, r, primary, secondary, pattern) {
    ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fillStyle = primary; ctx.fill(); ctx.clip();
    ctx.fillStyle = secondary;
    if (pattern === "stripes") { ctx.fillRect(x - 0.55 * r, y - r, 0.35 * r, 2 * r); ctx.fillRect(x + 0.2 * r, y - r, 0.35 * r, 2 * r); }
    else if (pattern === "halves") ctx.fillRect(x, y - r, r, 2 * r);
    else if (pattern === "hoops") { ctx.fillRect(x - r, y - 0.55 * r, 2 * r, 0.35 * r); ctx.fillRect(x - r, y + 0.2 * r, 2 * r, 0.35 * r); }
    else if (pattern === "band") ctx.fillRect(x - 0.3 * r, y - r, 0.6 * r, 2 * r);
    ctx.restore();
  }

  // ---------- star rating (0..5 in half steps), as SVG ----------
  function stars(n, size = 22) {
    const pts = (cx, cy, r) => Array.from({ length: 10 }, (_, i) => { const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 === 0 ? r : r * 0.42; return `${(cx + Math.cos(a) * rr).toFixed(2)},${(cy + Math.sin(a) * rr).toFixed(2)}`; }).join(" ");
    const r = size / 2, w = size * 5 + 16, id = "st" + Math.random().toString(36).slice(2, 8);
    let out = `<svg class="g-stars" width="${w}" height="${size + 2}" viewBox="0 0 ${w} ${size + 2}">`;
    for (let i = 0; i < 5; i++) {
      const cx = r + i * (size + 4), fill = Math.max(0, Math.min(1, n - i)), p = pts(cx, r + 1, r);
      out += `<polygon points="${p}" fill="var(--g-panel3)"/>`;
      if (fill >= 1) out += `<polygon points="${p}" fill="var(--g-accent)"/>`;
      else if (fill > 0) out += `<clipPath id="${id}${i}"><rect x="${cx - r - 1}" y="0" width="${2 * r * fill + 1}" height="${size + 2}"/></clipPath><polygon points="${p}" fill="var(--g-accent)" clip-path="url(#${id}${i})"/>`;
    }
    return out + "</svg>";
  }

  return { rgb, css, darkened, lightened, mix, dist, luminance, goalColour, logo, logoCanvas, logoTag, fillLogos, kit, stars, path };
})();
