// The Lab (web/lab/core.js has the overview): the Docs page: the project's Markdown files.
"use strict";

// ---- Docs: the project's Markdown files, rendered here (a small Markdown renderer: headings, tables, lists, code, links; no libraries)
const docs = { list: null, text: {}, loading: new Set() };
function loadDocs(id) {
  const key = id || "*";
  if (docs.loading.has(key)) return;
  docs.loading.add(key);
  (id ? fetch("/api/docs/" + encodeURIComponent(id)).then((r) => (r.ok ? r.text() : Promise.reject())).then((t) => { docs.text[id] = t; })
      : fetch("/api/docs").then((r) => r.json()).then((d) => { docs.list = d.docs; }))
    .catch(() => { if (id) docs.text[id] = null; else docs.list = []; })
    .finally(() => { docs.loading.delete(key); rerender(); });
}
function resolveDoc(href, base) {          // a relative link of a document -> a path from the project root
  const dir = base.includes("/") ? base.slice(0, base.lastIndexOf("/") + 1) : "";
  return (dir + href).split("/").reduce((a, p) => { if (p === "..") a.pop(); else if (p && p !== ".") a.push(p); return a; }, []).join("/");
}
// ---------- maths in the docs: a small TeX subset ($inline$, $$display$$) rendered to HTML, no external library ----------
// Only for documents with a display formula (a line starting with $$), so a stray $ elsewhere is never touched.
let mdMath = false;
const TEX_SYM = { alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", theta: "θ", lambda: "λ", mu: "μ", pi: "π", sigma: "σ",
  tau: "τ", phi: "φ", Sigma: "Σ", sum: "Σ", le: "≤", leq: "≤", ge: "≥", geq: "≥", cdot: "·", times: "×", sim: "∼", in: "∈",
  propto: "∝", leftarrow: "←", rightarrow: "→", to: "→", infty: "∞", approx: "≈", ne: "≠", pm: "±", top: "⊤", ldots: "…",
  lfloor: "⌊", rfloor: "⌋", ln: "ln", log: "log", exp: "exp", min: "min", max: "max", cos: "cos", sin: "sin",
  quad: "\u2003", qquad: "\u2003\u2003", ",": "\u2009", ";": "\u2005", " ": " ", "!": "", "{": "{", "}": "}", "|": "‖", "%": "%" };
function tex(s) {
  let i = 0;
  const skip = () => { while (s[i] === " ") i++; };
  const raw = () => {                       // the argument as plain text (\text, \mathrm)
    skip();
    if (s[i] !== "{") return esc(s[i++] || "");
    let d = 0, j = i;
    for (; j < s.length; j++) { if (s[j] === "{") d++; else if (s[j] === "}" && --d === 0) break; }
    const t = s.slice(i + 1, j); i = j + 1; return esc(t);
  };
  const arg = () => { skip(); if (s[i] === "{") { i++; return parse(true); } if (s[i] === "\\") return cmd(); return atom(s[i++] || ""); };
  const atom = (c) => (/[a-zA-Z]/.test(c) ? `<i>${c}</i>` : esc(c));
  function cmd() {
    i++;
    let name;
    if (/[a-zA-Z]/.test(s[i])) { let j = i; while (j < s.length && /[a-zA-Z]/.test(s[j])) j++; name = s.slice(i, j); i = j; } else name = s[i++];
    switch (name) {
      case "frac": case "tfrac": case "dfrac": { const a = arg(), b = arg(); return `<span class="tx-frac"><span>${a}</span><span>${b}</span></span>`; }
      case "sqrt": return `√<span class="tx-sqrt">${arg()}</span>`;
      case "mathbf": case "boldsymbol": return `<b class="tx-bf">${arg().replace(/<\/?i>/g, "")}</b>`;
      case "mathrm": case "text": case "operatorname": return `<span class="tx-rm">${raw()}</span>`;
      case "mathcal": return `<span class="tx-cal">${raw()}</span>`;
      case "overline": case "bar": return `<span class="tx-over">${arg()}</span>`;
      case "left": case "right": case "big": case "Big": case "bigg": case "Bigg": return "";
      default: return TEX_SYM[name] !== undefined ? TEX_SYM[name] : esc("\\" + name);
    }
  }
  function parse(inGroup) {
    let out = "";
    while (i < s.length) {
      const c = s[i];
      if (c === "}") { i++; if (inGroup) return out; continue; }
      if (c === "{") { i++; out += parse(true); continue; }
      if (c === "^") { i++; out += `<sup>${arg()}</sup>`; continue; }
      if (c === "_") { i++; out += `<sub>${arg()}</sub>`; continue; }
      if (c === "\\") { out += cmd(); continue; }
      out += atom(c); i++;
    }
    return out;
  }
  return parse(false);
}
function mdInline(t, base) {
  const maths = [];
  if (mdMath) t = t.replace(/\$([^$]+?)\$/g, (_, m) => { maths.push(m); return "\u0000" + (maths.length - 1) + "\u0000"; });
  t = esc(t);
  t = t.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, "$1<i>$2</i>");
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => `<img class="md-img" loading="lazy" alt="${alt}" src="/api/docfile?path=${encodeURIComponent(resolveDoc(src.replace(/&amp;/g, "&"), base))}">`);
  t = t.replace(/&lt;br\s*\/?&gt;/g, "<br>");
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    href = href.replace(/&amp;/g, "&");
    if (/^https?:/.test(href)) return `<a href="${esc(href)}" target="_blank" rel="noopener">${label}</a>`;
    const norm = resolveDoc(href.split("#")[0], base);
    const d = (docs.list || []).find((x) => x.path === norm);
    return d ? `<a href="#/docs/${esc(d.id)}">${label}</a>` : label;
  });
  if (maths.length) t = t.replace(/\u0000(\d+)\u0000/g, (_, k) => `<span class="tx">${tex(maths[+k])}</span>`);
  return t;
}
function md(src, base) {
  src = src.replace(/<img\s[^>]*?src="([^"]+)"[^>]*?alt="([^"]*)"[^>]*>/g, "![$2]($1)").replace(/<\/?p[^>]*>/g, "");   // the few HTML tags of the READMEs
  mdMath = /^\s*\$\$/m.test(src);
  const lines = src.replace(/\r/g, "").split("\n"), out = [];
  let i = 0, para = [];
  const flush = () => { if (para.length) { out.push(`<p>${mdInline(para.join(" "), base)}</p>`); para = []; } };
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { flush(); const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push(`<pre>${esc(buf.join("\n"))}</pre>`); continue; }
    const dm = mdMath && /^\s*\$\$(.+)\$\$\s*$/.exec(l);
    if (dm) { flush(); out.push(`<div class="tx tx-display">${tex(dm[1])}</div>`); i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) { flush(); const n = h[1].length; out.push(`<h${n} id="${esc(h[2].toLowerCase().replace(/[^a-z0-9]+/g, "-"))}">${mdInline(h[2], base)}</h${n}>`); i++; continue; }
    if (/^\s*---+\s*$/.test(l)) { flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flush(); const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<div class="tbl-wrap"><table class="md">${head.some((c) => c) ? `<thead><tr>${head.map((c) => `<th>${mdInline(c, base)}</th>`).join("")}</tr></thead>` : ""}<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${mdInline(c, base)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*>/.test(l)) { flush(); const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, "")); out.push(`<blockquote>${mdInline(buf.join(" "), base)}</blockquote>`); continue; }
    const li = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(l);
    if (li) {
      flush(); const ordered = /\d/.test(li[2]), items = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (m) { items.push({ depth: Math.min(3, Math.floor(m[1].length / 2)), text: m[3] }); i++; }
        else if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1].text += " " + lines[i].trim(); i++; }
        else break;
      }
      out.push(`<${ordered ? "ol" : "ul"} class="md">${items.map((it) => `<li style="margin-left:${it.depth * 18}px">${mdInline(it.text.replace(/^\[ \]/, "☐").replace(/^\[x\]/i, "☑"), base)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l.trim()); i++;
  }
  flush();
  return out.join("\n");
}
function viewDocs(id) {
  if (docs.list === null) { loadDocs(""); return '<div class="empty">Loading…</div>'; }
  const groups = {};
  for (const d of docs.list) (groups[d.group] = groups[d.group] || []).push(d);
  const side = Object.entries(groups).map(([g, ds]) => `<div class="doc-g">${esc(g)}</div>${ds.map((d) => `<a class="doc-l${d.id === id ? " on" : ""}" href="#/docs/${esc(d.id)}">${esc(d.title)}<small>${esc(d.path)}</small></a>`).join("")}`).join("");
  let body;
  if (!id) body = `<div class="card"><h2>Docs</h2><p class="muted">The project's notes, read from the repository: the lab notebook, the reward register, how to run experiments and how the game works.</p><div class="doc-cards">${docs.list.map((d) => `<a class="doc-card" href="#/docs/${esc(d.id)}"><b>${esc(d.title)}</b><span class="muted small">${esc(d.path)} · updated ${esc(ago(d.updated))}</span></a>`).join("")}</div></div>`;
  else {
    const d = docs.list.find((x) => x.id === id);
    if (!d) body = '<div class="empty">Unknown document.</div>';
    else if (docs.text[id] === undefined) { loadDocs(id); body = '<div class="empty">Loading…</div>'; }
    else if (docs.text[id] === null) body = '<div class="empty">Could not load this document.</div>';
    else body = `<article class="card doc-body"><div class="muted small">${esc(d.path)} · updated ${esc(ago(d.updated))}</div>${md(docs.text[id], d.path)}</article>`;
  }
  return `<div class="docs-wrap"><nav class="doc-side">${side}</nav><div class="doc-main">${body}</div></div>`;
}
