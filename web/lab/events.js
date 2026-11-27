// The Lab (web/lab/core.js has the overview): events. What the runner, the evaluations and the machine did (lab.py events), as one
// readable line each: the 5 newest on Now, every one on the Events page (#/events: filters, pages, day separators).
"use strict";

const ev = { data: null, t: 0, run: "", kind: "", days: 7 };
function loadEvents(force) {
  if (pending._ev || (!force && ev.data && Date.now() - ev.t < POLL_MS)) return;
  pending._ev = true;
  const since = new Date(Date.now() - ev.days * 86400000).toISOString().slice(0, 16);
  getJSON("/api/v1/events?since=" + since).then((d) => { ev.data = d.data.slice().reverse(); ev.t = Date.now(); render(); })
    .catch(() => { ev.data = []; ev.t = Date.now(); render(); }).finally(() => { delete pending._ev; });
}
// the run an event is about (the first word of most lines)
function eventRun(e) { const m = /^(?:started |resuming )?([A-Za-z0-9_:.-]+?)(?::| |$)/.exec(e.text || ""); return m && !["ladder", "viewer"].includes(m[1]) ? m[1] : ""; }
// one event -> {cls, html, group?}: the runner's own "fast check" / "full eval started" lines are dropped (the recorded evaluations say the same)
function eventItem(e) {
  const t = e.text || "", run = runLink;
  let m;
  if (e.kind === "eval_recorded" && (m = /^(\S+) u(\d+) (\w+) \S+ pts (\S+)/.exec(t)))
    return m[3] === "fast" ? { cls: "fast", group: "fast:" + m[1], html: `${run(m[1])} fast check at u${m[2]}: <b>${f(parseFloat(m[4]))}</b> pts` }
      : m[3] === "full" ? { cls: "full", html: `${run(m[1])} full evaluation at u${m[2]} <span class="muted">behaviour, scouting</span>` } : null;
  if (e.kind === "estimate" && (m = /^(\S+) u(\d+) estimated Elo (\d+) ± (\d+), vs start ([+-]\d+) \(z (\S+)\), GF (\S+) GA (\S+)/.exec(t)))
    return { cls: "full", html: `${run(m[1])} u${m[2]} checkpoint Elo <b>~${m[3]}</b><span class="muted"> ±${m[4]}</span> · <span class="${tone(+m[5])}">${m[5]}</span> vs start · GF ${m[7]} · GA ${m[8]}` };
  if (e.kind === "fast_check" || e.kind === "full_eval") return null;
  if (e.kind === "started" && (m = /^started (\S+)/.exec(t))) return { cls: "started", html: `${run(m[1])} started` };
  if (e.kind === "resumed" && (m = /^resuming (\S+) from update (\d+) \((.*)\)$/.exec(t))) return { cls: "started", html: `${run(m[1])} resumed at u${m[2]} <span class="muted">${esc(m[3])}</span>` };
  if (e.kind === "finished" && (m = /^(\S+) finished: (\S+)/.exec(t))) return { cls: m[2] === "done" ? "finished" : "stopped", html: `${run(m[1])} finished: ${esc(m[2])}` };
  if (e.kind === "stopped" && (m = /^(\S+): (\S+) at update (\d+)/.exec(t))) return { cls: "stopped", html: `${run(m[1])} stopped at u${m[3]}: ${esc(m[2])}` };
  if (e.kind === "reboot") return { cls: "reboot", html: `${esc((/^(.*?) rebooted/.exec(t) || [, "the machine"])[1])} rebooted <span class="muted">${esc(t.replace(/^.*? rebooted\s*/, ""))}</span>` };
  if (/^ladder: /.test(t)) return { cls: "info", group: "ladder", html: "rating round" };
  if (/^viewer closed/.test(t)) return { cls: "info", group: "viewer", html: "live match restarted" };
  return { cls: e.kind === "error" ? "error" : "info", html: esc(t) };
}
// events (newest first) -> readable items; consecutive lines of one group on one day become one item ("×3")
function eventList(events) {
  const items = [];
  for (const e of events) {
    const it = eventItem(e); if (!it) continue;
    const prev = items[items.length - 1];
    if (it.group && prev && prev.group === it.group && prev.t.slice(0, 10) === (e.t || "").slice(0, 10)) { prev.n++; prev.t0 = e.t; continue; }
    items.push({ ...it, t: e.t || "", t0: e.t || "", n: 1, kind: e.kind, run: eventRun(e) });
  }
  return items;
}
const dayName = (iso) => { const d = new Date(iso.slice(0, 10) + "T12:00:00"), today = new Date(); today.setHours(12, 0, 0, 0); const k = Math.round((today - d) / 86400000); return k === 0 ? "Today" : k === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" }); };
function eventLi(it) {
  const time = it.n > 1 && it.t0 !== it.t ? `${it.t0.slice(11, 16)}–${it.t.slice(11, 16)}` : it.t.slice(11, 16);
  return `<li class="ev ${esc(it.cls)}"><time>${esc(time)}</time><span>${it.html}${it.n > 1 ? ` <span class="muted">×${it.n}</span>` : ""}</span></li>`;
}

// ---------- the Events page ----------
onSeg.evdays = (v) => { ev.days = +v; state.page.events = 0; loadEvents(true); };
onSeg.evkind = (v) => { ev.kind = v; state.page.events = 0; rerender(); };
onSeg.evrun = (v) => { ev.run = v; state.page.events = 0; rerender(); };
const EV_KINDS = [["", "All"], ["checks", "Checks"], ["runs", "Starts and stops"], ["machine", "Machine"]];
const evKindOf = (it) => (["estimate", "eval_recorded"].includes(it.kind) ? "checks" : ["started", "resumed", "finished", "stopped"].includes(it.kind) ? "runs" : ["reboot", "error"].includes(it.kind) ? "machine" : "other");
function viewEvents() {
  loadEvents();
  const head = `<div class="head"><div><h1>Events</h1><p>What the runner, the evaluations and the machine did, newest first (<span class="mono">python3 lab/lab.py events</span>).</p></div>
    ${seg("evdays", [[1, "24 h"], [7, "7 days"], [30, "30 days"]], ev.days)}</div>`;
  if (!ev.data) return head + '<div class="empty">Loading…</div>';
  const all = eventList(ev.data), runs = [...new Set(all.map((it) => it.run).filter(Boolean))].sort();
  const rows = all.filter((it) => (!ev.kind || evKindOf(it) === ev.kind) && (!ev.run || it.run === ev.run));
  const pg = pager("events", rows, 40);
  let out = "", lastDay = "";
  for (const it of pg.rows) { const dd = it.t.slice(0, 10); if (dd !== lastDay) { out += `<li class="day">${esc(dayName(it.t))}</li>`; lastDay = dd; } out += eventLi(it); }
  return head + `<div class="fbar">${seg("evkind", EV_KINDS, ev.kind)}
      <label class="fsel ${ev.run ? "on" : ""}"><span>Run</span><select data-sel="evrun"><option value="">any</option>${runs.map((r) => `<option ${r === ev.run ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></label>
      <span class="fcount">${rows.length} events</span></div>
    <section class="card"><ul class="events">${out || '<li class="muted">nothing matches</li>'}</ul>${pg.html}</section>`;
}
