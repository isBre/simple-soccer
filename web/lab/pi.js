// The Lab (web/lab/core.js has the overview): the Pi page.
"use strict";

function viewPi() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  if (!state.health || state.health.hours !== state.piHours) loadHealth();
  const pi = o.status.pi, th = throttle(pi.throttled), H = state.health;
  const rows = (H?.rows || []).filter((r) => r.t && r.t.includes("T"));
  const vl = (H?.reboots || []).map((r) => ({ x: parseT(r.back), label: "reboot (last seen " + r.last_seen.slice(11, 16) + ")" }));
  const mk = (k) => rows.map((r) => ({ x: parseT(r.t), y: r[k] }));
  const opt = { height: 180, time: true, vlines: vl, gap: 120 };
  const win = [3, 12, 48].map((h) => `<button class="pill ${state.piHours === h ? "on" : ""}" data-hours="${h}">${h} h</button>`).join("");
  const last = rows[rows.length - 1];
  return `<div class="head"><div><h1>Raspberry Pi</h1><p>One sample every 10 s (<span class="mono">logs/pi_health.log</span>). Red lines mark reboots; the last sample before one shows what the Pi was doing.</p></div><div class="pills">${win}</div></div>
    <div class="kpis">${kpi("Temperature", `${f(pi.temp_c, 1)}<small>°C</small>`)}${kpi("CPU load", `${f(pi.load_1m, 1)}<small>/ 4</small>`)}${kpi("Free memory", `${f(pi.mem_free_mb == null ? null : pi.mem_free_mb / 1024, 2)}<small>GB</small>`)}${kpi("Power", esc(th.text), esc(th.sub || ""), th.cls)}${kpi("Uptime", dur(pi.uptime_hours * 3600), "boot " + esc(pi.boot_id || ""))}${kpi("Last sample", last ? ago(last.t) : "–", "watchdog: reboot after 15 s frozen")}</div>
    <div class="grid g2">
      <section class="card"><div class="card-h"><h3>Temperature °C</h3></div>${lineChart([{ name: "temperature", color: css("--c2"), points: mk("temp") }], { ...opt, refs: [{ y: 80, label: "throttles at 80" }], key: "pt", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU load (1 min)</h3></div>${lineChart([{ name: "load", color: css("--c1"), points: mk("load") }], { ...opt, yMin: 0, refs: [{ y: 4, label: "4 cores" }], key: "pl", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>Free memory MB</h3></div>${lineChart([{ name: "free", color: css("--c3"), points: mk("mem_mb") }], { ...opt, yMin: 0, key: "pm", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU clock MHz</h3></div>${lineChart([{ name: "clock", color: css("--c4"), points: mk("clock_mhz") }], { ...opt, yMin: 0, key: "pc", emptyText: "no dated samples yet" })}</section>
    </div>`;
}
