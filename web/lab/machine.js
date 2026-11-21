// The Lab (web/lab/core.js has the overview): the Machine page (health of the computer serving the Lab: Pi or Mac).
"use strict";

function viewMachine() {
  const o = state.ov; if (!o) return '<div class="empty">Loading…</div>';
  if (!state.health || state.health.hours !== state.healthHours) loadHealth();
  const m = o.status.machine, th = powerState(m), H = state.health, cores = m.cores || 4, mac = m.kind === "mac", name = machineName(m);
  const rows = (H?.rows || []).filter((r) => r.t && r.t.includes("T"));
  const vl = (H?.reboots || []).map((r) => ({ x: parseT(r.back), label: "reboot (last seen " + r.last_seen.slice(11, 16) + ")" }));
  const mk = (k) => rows.map((r) => ({ x: parseT(r.t), y: r[k] }));
  const opt = { height: 180, time: true, vlines: vl, gap: 120 };
  const win = [3, 12, 48].map((h) => `<button class="pill ${state.healthHours === h ? "on" : ""}" data-hours="${h}">${h} h</button>`).join("");
  const last = rows[rows.length - 1];
  const lastChart = mac
    ? `<section class="card"><div class="card-h"><h3>Thermal pressure <span class="muted small">0 nominal · 1 moderate · 2 heavy</span></h3></div>${lineChart([{ name: "thermal", color: css("--c4"), points: mk("thermal") }], { ...opt, yMin: 0, refs: [{ y: 1, label: "CPU slowed from here" }], key: "pc", emptyText: "no dated samples yet" })}</section>`
    : `<section class="card"><div class="card-h"><h3>CPU clock MHz</h3></div>${lineChart([{ name: "clock", color: css("--c4"), points: mk("clock_mhz") }], { ...opt, yMin: 0, key: "pc", emptyText: "no dated samples yet" })}</section>`;
  return `<div class="head"><div><h1>${esc(name)}${m.chip ? ` <span class="muted">${esc(m.chip)}</span>` : ""}</h1><p>One sample every 10 s (<span class="mono">logs/health.log</span>). Red lines mark reboots; the last sample before one shows what the machine was doing.${mac ? " macOS gives no CPU temperature without admin rights: the temperature is the battery's, which on a fanless MacBook follows the chassis." : ""}</p></div><div class="pills">${win}</div></div>
    <div class="kpis">${kpi(m.temp_label || "Temperature", `${f(m.temp_c, 1)}<small>°C</small>`)}${kpi("CPU load", `${f(m.load_1m, 1)}<small>/ ${cores}</small>`)}${kpi("Free memory", `${f(m.mem_free_mb == null ? null : m.mem_free_mb / 1024, 2)}<small>${m.mem_total_mb ? "/ " + f(m.mem_total_mb / 1024, 0) + " " : ""}GB</small>`)}${kpi(mac ? "Thermal" : "Power", esc(th.text), esc(th.sub || ""), th.cls)}${kpi("Uptime", dur(m.uptime_hours * 3600), "boot " + esc(m.boot_id || ""))}${kpi("Last sample", last ? ago(last.t) : "–", m.watchdog ? "watchdog: reboot after 15 s frozen" : "")}</div>
    <div class="grid g2">
      <section class="card"><div class="card-h"><h3>${esc(m.temp_label || "Temperature")} °C</h3></div>${lineChart([{ name: "temperature", color: css("--c2"), points: mk("temp") }], { ...opt, refs: mac ? [] : [{ y: 80, label: "throttles at 80" }], key: "pt", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>CPU load (1 min)</h3></div>${lineChart([{ name: "load", color: css("--c1"), points: mk("load") }], { ...opt, yMin: 0, refs: [{ y: cores, label: cores + " cores" }], key: "pl", emptyText: "no dated samples yet" })}</section>
      <section class="card"><div class="card-h"><h3>Free memory MB</h3></div>${lineChart([{ name: "free", color: css("--c3"), points: mk("mem_mb") }], { ...opt, yMin: 0, key: "pm", emptyText: "no dated samples yet" })}</section>
      ${lastChart}
    </div>`;
}
