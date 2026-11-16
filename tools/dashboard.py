"""Web dashboard of the experiment pipeline, for the local network: open http://<pi-address>:8080 from another computer.

The page (tools/dashboard/: index.html, app.js, style.css) is a small single-page app that polls the JSON API below every 10 s.
  /api/overview       Pi state, the running experiment (progress, ETA), queue, every run with its latest evaluation, Pi health
  /api/run/<name>     one run: spec and settings, training curve, PPO health, reward terms, every evaluation, heatmaps
  /api/health         Pi health log (throttling, temperature, load, memory) of the last hours
  /results.md         the tracker's table as text
Standard library only and no internet needed (the charts are drawn in the browser as SVG). It reads exp/ and logs/, never writes.
There is NO login: use it on a trusted network only.

  python3 tools/dashboard.py [--port 8080]                 (service soccer-dashboard, tools/systemd/)
"""
import argparse
import glob
import json
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "exp")
LOGS = os.path.join(ROOT, "logs")
STATIC = os.path.join(ROOT, "tools", "dashboard")
TRAIN_RE = re.compile(r"^\[(\d+:\d+:\d+)\] sp upd (\d+) \| pts/m vs rules (\S+?)(?:\((\d+)\))? \| vs frozen benchmark (\S+?)(?:\(\d+\))? \| "
                      r"vs league (\S+?)(?:\(\d+\))? \| rew/step (\S+) \| ent (\S+) \| pool \d+ \| (\d+) dec/s sim (\S+)s learn (\S+)s \| (\d+)s")


def jl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def rj(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def tag_of(run, status):
    """Log prefix (logs/<tag>.out) of a run: experiments are x_<name>, imported runs old_t47 -> t47, a start net start:t48_u100 -> t48."""
    if status.get("tag"):
        return status["tag"]
    if run.startswith("old_"):
        return run[4:]
    if run.startswith("start:"):
        return re.sub(r"_u\d+$", "", run[6:])
    return "x_" + run


def training(tag):
    """Per logged update: training points vs rule bots / frozen benchmark / league, reward per step, entropy, speed."""
    rows = []
    path = os.path.join(LOGS, tag + ".out")
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            m = TRAIN_RE.match(line)
            if m:
                u = int(m.group(2))
                rows.append({"upd": u, "rules": num(m.group(3)), "n_rules": int(m.group(4) or 0), "bench": num(m.group(5)), "league": num(m.group(6)),
                           "rew": num(m.group(7)), "ent": num(m.group(8)), "dps": int(m.group(9)), "sim": num(m.group(10)), "learn": num(m.group(11)),
                           "elapsed": int(m.group(12)), "clock": m.group(1)})
    return latest_segment(rows)


def latest_segment(rows, key="upd"):
    """Rows of a log that was appended to across restarts: a restart from update N repeats the updates after N, so every row
    replaces the ones at or after its update that came before it. Returns the rows in update order."""
    out = {}
    last = None
    for r in rows:
        u = r.get(key)
        if u is None:
            continue
        if last is not None and u <= last:
            out = {k: v for k, v in out.items() if k < u}
        out[u] = r
        last = u
    return [out[k] for k in sorted(out)]


def thin(rows, n=400):
    """At most n rows (evenly spaced, the last one kept), so the browser gets small payloads."""
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    out = [rows[int(i * step)] for i in range(n)]
    out[-1] = rows[-1]
    return out


def heatmaps(path):
    out = []
    if path and os.path.exists(path):
        for line in open(path, errors="replace"):
            p = line.split()
            if len(p) > 5 and p[0] == "HEAT":
                out.append({"slot": p[1], "role": p[2], "w": int(p[3]), "h": int(p[4]), "v": [int(x) for x in p[5:]]})
    return out


def eval_file(rec, tag):
    if rec.get("file"):
        return os.path.join(ROOT, rec["file"])
    if rec["run"].startswith("start:"):
        cands = [os.path.join(LOGS, "sp_eval", "%s.txt" % rec["run"][6:]), os.path.join(LOGS, "sp_eval", "%s_%s.txt" % (rec["run"].replace(":", "_"), rec["kind"]))]
    else:
        cands = [os.path.join(LOGS, "sp_eval", "%s_u%d%s.txt" % (tag, rec["update"], "_fast" if rec["kind"] == "fast" else ""))]
    return next((c for c in cands if os.path.exists(c)), None)


def statuses():
    out = {}
    for p in glob.glob(os.path.join(EXP, "runs", "*", "status.json")):
        st = rj(p)
        if st:
            out[os.path.basename(os.path.dirname(p))] = st
    return out


def health(hours=6.0):
    path = os.path.join(LOGS, "pi_health.log")
    if not os.path.exists(path):
        return []
    lines = open(path, errors="replace").read().splitlines()[-int(hours * 360):]
    rows = []
    for l in lines:
        d = dict(re.findall(r"(\w+)=([^\s]+)", l))
        if not d:
            continue
        rows.append({"t": l[:8], "throttled": d.get("throttled"), "temp": num(d.get("temp", "").rstrip("'C")), "load": num(d.get("load")),
                     "mem": num(d.get("memfree", "").rstrip("MB")), "clock": num(d.get("clock", "").rstrip("MHz")), "swap": num(d.get("swapused", "").rstrip("MB"))})
    return thin(rows, 360)


def system():
    up = num(open("/proc/uptime").read().split()[0]) if os.path.exists("/proc/uptime") else None
    load = open("/proc/loadavg").read().split()[:3] if os.path.exists("/proc/loadavg") else []
    mem = dict(re.findall(r"(\w+):\s+(\d+)", open("/proc/meminfo").read())) if os.path.exists("/proc/meminfo") else {}
    temp = None
    try:
        temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
    except OSError:
        pass
    last = health(0.01)
    return {"uptime_s": up, "load": [num(x) for x in load], "mem_total_mb": int(mem.get("MemTotal", 0)) // 1024,
            "mem_avail_mb": int(mem.get("MemAvailable", 0)) // 1024, "temp": temp, "throttled": last[-1]["throttled"] if last else None, "now": int(time.time())}


def run_summary(run, st, results):
    rows = [r for r in results if r["run"] == run]
    full = next((r for r in reversed(rows) if r["kind"] == "full"), None)
    fast = next((r for r in reversed(rows) if r["kind"] == "fast"), None)
    latest = full or fast
    curve = [{"upd": r["update"], "kind": r["kind"], "pts": r["league"].get("all", {}).get("pts"), "se": r["league"].get("all", {}).get("se"),
              "gd": r["league"].get("all", {}).get("gd")} for r in rows if r["league"].get("all")]
    tag = tag_of(run, st)
    tr = training(tag)
    return {"run": run, "tag": tag, "state": st.get("state", "imported" if run.startswith(("old_", "start:")) else "unknown"),
            "notes": (st.get("spec") or {}).get("notes", ""), "rewards": (st.get("spec") or {}).get("rewards", {}),
            "update": st.get("update") or (tr[-1]["upd"] if tr else None), "target": st.get("target_updates"),
            "verdict": st.get("verdict"), "baseline": st.get("baseline_run"), "started": st.get("started"), "finished": st.get("finished"),
            "latest": {"kind": latest["kind"], "update": latest["update"], "league": latest["league"], "greedy": latest.get("greedy", {}),
                       "h2h": latest["h2h"], "behaviour": latest["behaviour"]} if latest else None,
            "evals": curve, "spark": [r["rules"] for r in thin(tr, 60) if r["rules"] is not None]}


def overview():
    results = jl(os.path.join(EXP, "results.jsonl"))
    sts = statuses()
    runs = list(dict.fromkeys([r["run"] for r in results] + sorted(sts, key=lambda k: sts[k].get("started", 0))))
    summaries = [run_summary(r, sts.get(r, {}), results) for r in runs]
    running = next((s for s in summaries if s["state"] == "running"), None)
    now = None
    if running:
        tr = training(running["tag"])
        ev = rj(os.path.join(LOGS, running["tag"] + "_eval_running.json"))
        spu = None
        if len(tr) >= 3:
            a, b = tr[max(0, len(tr) - 30)], tr[-1]
            spu = (b["elapsed"] - a["elapsed"]) / max(b["upd"] - a["upd"], 1) if b["elapsed"] > a["elapsed"] else None
        log_path = os.path.join(LOGS, running["tag"] + ".out")
        age = time.time() - os.path.getmtime(log_path) if os.path.exists(log_path) else None
        now = {**running, "sec_per_update": spu, "eta_s": spu * max((running["target"] or 0) - (running["update"] or 0), 0) if spu else None,
               "eval": ev, "log_age_s": age, "last": tr[-1] if tr else None, "base_train": sts[running["run"]].get("base_train"),
               "train_pts": sts[running["run"]].get("train_pts")}
    queue = []
    for p in sorted(glob.glob(os.path.join(EXP, "queue", "*.json"))):
        spec = rj(p, {})
        if running and spec.get("name") == running["run"]:
            continue                                            # the running experiment's spec stays in the queue until it finishes
        queue.append({"file": os.path.basename(p), "name": spec.get("name"), "rewards": spec.get("rewards", {}), "updates": spec.get("updates"),
                      "lr": spec.get("lr"), "start": spec.get("start"), "notes": spec.get("notes", "")})
    log = os.path.join(EXP, "runner.log")
    events = open(log, errors="replace").read().splitlines()[-25:] if os.path.exists(log) else []
    return {"system": system(), "now": now, "runs": summaries, "queue": queue, "events": events[::-1]}


def run_detail(run):
    results = jl(os.path.join(EXP, "results.jsonl"))
    st = statuses().get(run, {})
    tag = tag_of(run, st)
    rows = [r for r in results if r["run"] == run]
    evals = []
    for r in rows:
        evals.append({**{k: r.get(k) for k in ("update", "kind", "league", "greedy", "h2h", "behaviour", "seconds", "time")},
                      "heat": heatmaps(eval_file(r, tag)) if r["kind"] == "full" else []})
    config = rj(os.path.join(LOGS, tag + "_config.json"), {})
    terms = thin(latest_segment([{"upd": t["upd"], **t["terms"]} for t in jl(os.path.join(LOGS, tag + "_terms.jsonl"))]), 300)
    ppo = thin(latest_segment(jl(os.path.join(LOGS, tag + "_ppo.jsonl"))), 300)
    base = None
    if st.get("baseline_run"):
        b = [r for r in results if r["run"] == st["baseline_run"]]
        base = {"run": st["baseline_run"], "evals": [{k: r.get(k) for k in ("update", "kind", "league", "h2h", "behaviour")} for r in b]}
    return {"run": run, "tag": tag, "status": st, "config": config, "training": thin(training(tag), 400), "ppo": ppo, "terms": terms,
            "evals": evals, "baseline": base}


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        try:
            if path == "/api/overview":
                return self.send(json.dumps(overview()).encode(), "application/json")
            if path.startswith("/api/run/"):
                return self.send(json.dumps(run_detail(path[len("/api/run/"):])).encode(), "application/json")
            if path == "/api/health":
                return self.send(json.dumps(health(12.0)).encode(), "application/json")
            if path == "/results.md":
                return self.send(open(os.path.join(EXP, "results.md"), "rb").read(), "text/plain; charset=utf-8")
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(STATIC, name))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self.send(b"not found", "text/plain", 404)
            return self.send(open(full, "rb").read(), (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")
        except Exception as e:                                 # a half-written log must not kill the server
            return self.send(json.dumps({"error": repr(e)}).encode(), "application/json", 500)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
