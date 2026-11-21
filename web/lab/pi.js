// The Lab (web/lab/core.js has the overview): the Pi page.
"use strict";

function viewPi() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  if (!state.health || state.health.hours !== state.piHours) loadHealth();
  const pi = o.status.pi, th = powerState(pi), H = state.health, cores = pi.cores || 4, mac = pi.kind === "mac", name = machineName(pi);
  const rows = (H?.rows || []).filter((r) => r.t && r.t.includes("T"));
  const vl = (H?.reboots || []).map((r) => ({ x: parseT(r.back), label: "reboot (last seen " + r.last_seen.slice(11, 16) + ")" }));
  const mk = (k) => rows.map((r) => ({ x: parseT(r.t), y: r[k] }));
  const opt = { height: 180, time: true, vlines: vl, gap: 120 };
  const win = [3, 12, 48].map((h) => `<button class="pill ${state.piHours === h ? "on" : ""}" data-hours="${h}">${h} h</button>`).join("");
  const last = rows[rows.length - 1];
  const lastChart = mac
    ? `<section class="card"><div class="card-h"><h3>Thermal pressure <span class="muted small">0 nominal · 1 moderate · 2 heavy</span></h3></div>${lineChart([{ name: "thermal", color: css("--c4"), points: mk("thermal") }], { ...opt, yMin: 0, refs: [{ y: 1, label: "CPU slowed from here" }], key: "pc", emptyText: "no dated samples yet" })}</section>`
    : `<section class="card"><div class="card-h"><h3>CPU clock MHz</h3></div>${lineChart([{ name: "clock", color: css("--c4"), points: mk("clock_mhz") }], { ...opt, yMin: 0, key: "pc", emptyText: "no dated samples yet" })}</section>`;
  return `<div class="head"><div><h1>${esc(name)}${pi.chip ? ` <span class="muted">${esc(pi.chip)}</span>` : ""}</h1><p>One sample every 10 s (<span class="mono">logs/pi_health.log</span>). Red lines mark reboots; the last sample before one shows what the machine was doing.${mac ? " macOS gives no CPU temperature without admin rights: the temperature is the battery's, which on a fanless MacBook follows the chassis." : ""}</p></div><div class="pills">${win}</div></div>
    <div class="kpis">${kpi(pi.temp_label || "Temperature", `${f(pi.temp_c, 1)}<small>°C</small>`)}${kpi("CPU load", `${f(pi.load_1m, 1)}<small>/ ${cores}</small>`)}${kpi("Free memory", `${f(pi.mem_free_mb == null ? null : pi.mem_free_mb / 1024, 2)}<small>${pi.mem_total_mb ? "/ " + f(pi.mem_total_mb / 1024, 0) + " " : ""}GB</small>`)}${kpi(mac ? "Thermal" : "Power", esc(th.text), esc(th.sub || ""), th.cls)}${kpi("Uptime", dur(pi.uptime_hours * 3600), "boot " + esc(pi.boot_id || ""))}${kpi("Last sample", last ? ago(last.t) : "–", pi.watchdog ? "watchdog: reboot after 15 s frozen" : "")}</div>
    <div class="grid g2">
      <section class="card"><div class="card-h"><h3>${esc(pi.temp_label || "Temperature")} °C</h3></div>${lineChart([{ name: "temperature", color: css("--c2"), points: mk("temp") }], { ...opt, refs: mac ? [] : [{ y: 80, label: "throttles at 80" }], key: "pt", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU load (1 min)</h3></div>${lineChart([{ name: "load", color: css("--c1"), points: mk("load") }], { ...opt, yMin: 0, refs: [{ y: cores, label: cores + " cores" }], key: "pl", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>Free memory MB</h3></div>${lineChart([{ name: "free", color: css("--c3"), points: mk("mem_mb") }], { ...opt, yMin: 0, key: "pm", emptyText: "no dated samples yet" })}</section>
      ${lastChart}
    </div>`;
}
