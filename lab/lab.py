"""Soccer Lab CLI: the experiment pipeline as compact JSON, for agents (and people). Standard library only; reads the files directly,
so it works even when the dashboard is down. Every command prints one JSON object ({"schema_version", "generated_at", "data"}),
--pretty indents it. Exit code 1 on errors ({"error", "hint"}). The dashboard serves the same data under /api/v1/ (read-only).

  python3 lab/lab.py status                          machine (Pi or Mac), runner, running experiment (progress, ETA, stalled?), last reboot
  python3 lab/lab.py runs [--state done]             one row per run: settings changed, progress, verdict, cost
  python3 lab/lab.py run NAME [--tail 20]            one run: status, evaluations (summaries), training / PPO tail
  python3 lab/lab.py evals [--run R] [--kind full] [--protocol full/g1/d90]
  python3 lab/lab.py best [--protocol full/g1/d90] [--k 5]       checkpoints ranked by the lower 95% bound of league points
  python3 lab/lab.py compare A B [--kind full] [--group league|greedy|h2h]   paired difference, z, p, MDE, verdict (same protocol only)
  python3 lab/lab.py ablation [--kind full]          every run vs its reference, Holm-corrected over the batch
  python3 lab/lab.py events [--since 2026-11-16T20:00]   runs started/resumed/finished, evaluations, reboots
  python3 lab/lab.py ranking [--size 5] [--league rl]  ratings of one size (elo/, this machine): players, teams, checkpoints, 95% intervals
  python3 lab/lab.py estimates [--run NAME]          estimated Elo of the checkpoints during training (lab/ladder.py estimate)
  python3 lab/lab.py queue list | validate F | add F [--position N] | cancel NAME | move NAME N
  python3 lab/lab.py schema                          what every metric means (unit, direction, protocol)
  python3 lab/lab.py ladder archive [--label L] [--yes]   start the Elo ranking over (only when the user asks; matches kept)
Definitions: AGENTS.md and exp/schema.json.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project root BEFORE lab/ (lab/lab.py would hide the lab package)
from lab import tracker  # noqa: E402

ROOT, EXP = tracker.ROOT, tracker.EXP
LOGS = os.path.join(ROOT, "logs")

class LabError(Exception):
    def __init__(self, error, hint=""):
        super().__init__(error)
        self.error, self.hint = error, hint


def iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def jl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def latest_segment(rows, key="upd"):
    """Rows of a log appended to across restarts: a restart from update N repeats the updates after N, so every row replaces the
    earlier rows at or after its update. Returns the rows in update order."""
    out, last = {}, None
    for r in rows:
        u = r.get(key)
        if u is None:
            continue
        if last is not None and u <= last:
            out = {k: v for k, v in out.items() if k < u}
        out[u] = r
        last = u
    return [out[k] for k in sorted(out)]


def thin(rows, n):
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    out = [rows[int(i * step)] for i in range(n)]
    out[-1] = rows[-1]
    return out


def tag_of(run, st=None):
    st = st if st is not None else tracker.run_status(run)
    if st.get("tag"):
        return st["tag"]
    if run.startswith("old_"):
        return run[4:]
    if run.startswith("start:"):
        return re.sub(r"_u\d+$", "", run[6:])
    return "x_" + run


def training(tag):
    """Per logged update: training points vs rule bots / frozen start net / own snapshots, reward per step, entropy, speed, seconds
    since the trainer's (re)start (tracker.train_rows)."""
    return latest_segment(tracker.train_rows(tag))


def speed(tr):
    """Seconds per update over the trainer's current start (elapsed restarts at 0 with every restart)."""
    seg = tr[-1:]
    for r in reversed(tr[:-1]):
        if r["elapsed"] >= seg[0]["elapsed"]:
            break
        seg.insert(0, r)
    if len(seg) < 2:
        return None
    a, b = seg[max(0, len(seg) - 30)], seg[-1]
    return (b["elapsed"] - a["elapsed"]) / max(b["upd"] - a["upd"], 1)


# ---------------------------------------------------------------- machine health
def health(hours=12.0):
    """Health samples (every 10 s) of the last hours: time (ISO), boot id, throttle flags, temperature, load, free memory, clock."""
    path = os.path.join(LOGS, "health.log")
    if not os.path.exists(path):
        return []
    rows = []
    for l in open(path, errors="replace").read().splitlines()[-int(hours * 360):]:
        parts = l.split(" ", 1)
        if len(parts) < 2:
            continue
        d = dict(re.findall(r"(\w+)=([^\s]*)", parts[1]))
        rows.append({"t": parts[0], "boot": d.get("boot"), "throttled": d.get("throttled"), "temp": num(d.get("temp", "").rstrip("'C")),
                     "load": num(d.get("load")), "mem_mb": num(d.get("memfree", "").rstrip("MB")), "clock_mhz": num(d.get("clock", "").rstrip("MHz")),
                     "swap_mb": num(d.get("swapused", "").rstrip("MB")), "thermal": num(d.get("thermal")), "battery": num(d.get("battery")),
                     "power": d.get("power"), "kind": d.get("kind"), "machine": (d.get("machine") or "").replace("_", " ") or None,
                     "chip": (d.get("chip") or "").replace("_", " ") or None, "cores": num(d.get("cores")),
                     "mem_total_mb": num(d.get("memtotal", "").rstrip("MB")), "temp_src": d.get("temp_src")})
    return rows


THERMAL = ["nominal", "moderate", "heavy", "trapping", "sleeping"]       # macOS thermal pressure levels (CPU slowed from "moderate" up)


def machine(last):
    """What the health box describes: the machine of the last health sample (the Pi when the sample has no machine keys)."""
    kind = last.get("kind") or ("mac" if sys.platform == "darwin" else "pi")
    mac = kind == "mac"
    boot = None
    if mac:
        m = re.search(r"sec = (\d+)", subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True).stdout)
        boot = int(m.group(1)) if m else None
    th = last.get("thermal")
    return {"kind": kind, "name": last.get("machine") or ("Mac" if mac else "Raspberry Pi"), "chip": last.get("chip"),
            "cores": int(last.get("cores") or os.cpu_count() or 4), "mem_total_mb": last.get("mem_total_mb") or (None if mac else 3800),
            "temp_label": "Battery temp" if last.get("temp_src") == "battery" else "Temperature", "temp_warn": 40 if last.get("temp_src") == "battery" else 75,
            "thermal": int(th) if th is not None else None, "thermal_text": THERMAL[int(th)] if th is not None and 0 <= th < len(THERMAL) else None,
            "power": last.get("power"), "battery_pct": last.get("battery"), "boot_time": boot, "watchdog": kind == "pi"}


def reboots(rows=None):
    """Boot changes seen in the health log: [{boot, last_seen (before), first_seen (after)}] (only for samples with a boot id)."""
    rows = rows if rows is not None else health(48)
    out = []
    for a, b in zip(rows, rows[1:]):
        if a["boot"] and b["boot"] and a["boot"] != b["boot"]:
            out.append({"from_boot": a["boot"], "to_boot": b["boot"], "last_seen": a["t"], "back": b["t"], "last_sample": a})
    return out


def cmd_status(_a):
    up = num(open("/proc/uptime").read().split()[0]) if os.path.exists("/proc/uptime") else None
    mem = dict(re.findall(r"(\w+):\s+(\d+)", open("/proc/meminfo").read())) if os.path.exists("/proc/meminfo") else {}
    hl = health(48)
    last = hl[-1] if hl else {}
    mc = machine(last)
    guard = {}
    try:                                                # lab/thermal_guard.py (fanless laptop): the run is paused to cool down
        guard = json.load(open(os.path.join(LOGS, "thermal_guard.json")))
        guard = guard if time.time() - guard.get("updated", 0) < 120 else {}
    except (OSError, ValueError):
        pass
    if up is None and mc["boot_time"]:
        up = time.time() - mc["boot_time"]
    try:
        active = subprocess.run(["systemctl", "is-active", "soccer-exp"], capture_output=True, text=True).stdout.strip() or None
    except OSError:                                    # no systemd (not the Pi): the runner service is not installed here
        active = None
    running, fresh = None, None
    for p in glob.glob(os.path.join(EXP, "runs", "*", "status.json")):
        st = tracker.run_status(os.path.basename(os.path.dirname(p)))
        if st.get("state") == "running":
            tag = st.get("tag", "x_" + st["name"])
            log_path = os.path.join(LOGS, tag + ".out")
            seen = max(os.path.getmtime(log_path) if os.path.exists(log_path) else 0, os.path.getmtime(p))
            if fresh is not None and seen <= fresh:     # two "running" states (one copied from another computer): the newest output wins
                continue
            fresh = seen
            tr = training(tag)
            spu = speed(tr) if tr else None
            age = time.time() - os.path.getmtime(log_path) if os.path.exists(log_path) else None
            ev = os.path.exists(os.path.join(LOGS, tag + "_eval_running.json"))
            running = {"run": st["name"], "update": st.get("update"), "target": st.get("target_updates"), "sec_per_update": round(spu, 1) if spu else None,
                       "eta_hours": round(spu * max(st.get("target_updates", 0) - (st.get("update") or 0), 0) / 3600, 2) if spu else None,
                       "train_pts_vs_rules": st.get("train_pts"), "train_pts_at_start": st.get("base_train"), "evaluating": ev,
                       "log_age_s": round(age) if age is not None else None, "stalled": bool(age is not None and age > 900 and not ev and not guard.get("paused")),
                       "thermal_pause": guard if guard.get("paused") else None,
                       "bad_checks": st.get("bad_checks", 0), "restarts": st.get("restarts", []), "started": iso(st.get("started"))}
    queue = sorted(os.path.basename(p) for p in glob.glob(os.path.join(EXP, "queue", "*.json")))
    rb = reboots(hl)
    return {"machine": {"uptime_hours": round(up / 3600, 2) if up else None, "boot_id": tracker.boot_id() or last.get("boot"), "last_sample": last.get("t"),
                   "temp_c": last.get("temp"), "load_1m": last.get("load"),
                   "mem_free_mb": int(mem["MemAvailable"]) // 1024 if "MemAvailable" in mem else last.get("mem_mb"), **mc,
                   "throttled": last.get("throttled"), "throttled_meaning": throttle_text(last.get("throttled"))},
            "runner": {"service": active, "running": running, "queue": queue},
            "last_reboot": rb[-1] if rb else None}


def throttle_text(hex_):
    if not hex_:
        return None
    v = int(hex_, 16)
    names = {0x1: "under-voltage now", 0x2: "frequency capped now", 0x4: "throttled now", 0x8: "soft temperature limit now",
             0x10000: "under-voltage since boot", 0x20000: "frequency capped since boot", 0x40000: "throttled since boot", 0x80000: "soft temperature limit since boot"}
    return [t for bit, t in names.items() if v & bit] or ["ok"]


# ---------------------------------------------------------------- runs and evaluations
def eval_row(r):
    a = r["league"].get("all", {})
    g = r.get("greedy", {}).get("all", {})
    return {"id": r.get("id"), "run": r["run"], "update": r["update"], "kind": r["kind"], "protocol": r.get("protocol"),
            "pts": a.get("pts"), "se": a.get("se"), "lcb95": round(a["pts"] - 1.96 * a["se"], 3) if a else None, "gd": a.get("gd"),
            "gd_se": a.get("gd_se"), "gf": a.get("gf"), "ga": a.get("ga"), "n": a.get("n"),
            "greedy_pts": g.get("pts"), "greedy_ga": g.get("ga"),
            "h2h": {k: {"pts": v["pts"], "se": v["se"], "gd": v["gd"], "n": v["n"]} for k, v in r.get("h2h", {}).items()},
            "style": {k: v for k, v in (r.get("scout") or {}).items() if not isinstance(v, (list, dict))},
            "behaviour": r.get("behaviour", {}), "behaviour_rule_bots": r.get("behaviour_rule", {}), "paired_matches": len(r.get("matches", [])), "git_commit": r.get("git_commit"),
            "checkpoint": r.get("checkpoint"), "file": r.get("file"), "eval_seconds": r.get("seconds"), "time": iso(r.get("time"))}


def all_runs():
    rows = tracker.load_results()
    names = list(dict.fromkeys([r["run"] for r in rows] + sorted(os.listdir(os.path.join(EXP, "runs")) if os.path.isdir(os.path.join(EXP, "runs")) else [])))
    return rows, names


def run_row(name, rows):
    st = tracker.run_status(name)
    spec = st.get("spec") or {}
    ev = [r for r in rows if r["run"] == name]
    full = next((r for r in reversed(ev) if r["kind"] == "full"), None)
    fast = next((r for r in reversed(ev) if r["kind"] == "fast"), None)
    from lab import ladder
    est = ladder.estimates(run=name)
    rewards = st.get("effective_rewards") or {}
    mn = tracker.minimal_for(st.get("started"))
    changed = {k: v for k, v in rewards.items() if mn.get(k) != v}
    return {"name": name, "state": st.get("state", "imported" if name.startswith(("old_", "start:")) else "reference" if name.startswith("team:") else "unknown"),
            "notes": spec.get("notes", ""), "start": spec.get("start"), "control": spec.get("control"),
            "net": (st.get("net") or tracker.net_info(spec.get("start") or ("out_5v5/ckpt/" + name[6:] if name.startswith("start:") else None)) or {}).get("label"),
            "rewards_changed_vs_minimal": changed if rewards else spec.get("rewards", {}), "seed": st.get("seed"),
            "update": st.get("update"), "target": st.get("target_updates"), "stop_reason": st.get("stop_reason"),
            "restarts": len(st.get("restarts", [])), "verdict": st.get("verdict"), "cost_hours": st.get("cost_hours"),
            "started": iso(st.get("started")), "finished": iso(st.get("finished")),
            "latest_full": eval_row(full) if full else None, "latest_fast": eval_row(fast) if fast else None,
            "elo_estimate": est_row(est[-1]) if est else None, "elo_estimates": len(est)}


def est_row(e, matches=False):
    """An estimated-Elo record without its match list (unless matches)."""
    return {k: v for k, v in e.items() if matches or k != "matches"}


def cmd_estimates(a):
    from lab import ladder
    return [est_row(e, a.matches) for e in ladder.estimates(run=a.run)]


def cmd_runs(a):
    rows, names = all_runs()
    out = [run_row(n, rows) for n in names]
    if a.state:
        out = [r for r in out if r["state"] == a.state]
    return out


def cmd_run(a):
    rows, names = all_runs()
    if a.name not in names:
        raise LabError("unknown run %r" % a.name, "python3 lab/lab.py runs lists the runs")
    st = tracker.run_status(a.name)
    tag = tag_of(a.name, st)
    tr = training(tag)
    ppo = latest_segment(jl(os.path.join(LOGS, tag + "_ppo.jsonl")))
    terms = latest_segment([{"upd": t["upd"], **t["terms"]} for t in jl(os.path.join(LOGS, tag + "_terms.jsonl"))])
    return {**run_row(a.name, rows), "status": st, "tag": tag, "config": json.load(open(os.path.join(LOGS, tag + "_config.json")))
            if os.path.exists(os.path.join(LOGS, tag + "_config.json")) else None,
            "evals": [eval_row(r) for r in rows if r["run"] == a.name], "training_tail": tr[-a.tail:], "ppo_tail": ppo[-a.tail:],
            "reward_terms_tail": terms[-a.tail:], "sec_per_update": speed(tr) if tr else None}


def cmd_evals(a):
    rows = tracker.load_results()
    return [eval_row(r) for r in rows if (not a.run or r["run"] == a.run) and (not a.kind or r["kind"] == a.kind)
            and (not a.protocol or r.get("protocol") == a.protocol)]


def cmd_best(a):
    rows = [r for r in tracker.load_results() if r.get("protocol") == a.protocol and r["league"].get("all")]
    ranked = sorted((eval_row(r) for r in rows), key=lambda e: e["lcb95"], reverse=True)
    return {"protocol": a.protocol, "ranked_by": "lcb95 = pts - 1.96 se (league, all 16 rule teams)", "top": ranked[:a.k]}


def pick(rows, run, kind, update=None):
    cands = [r for r in rows if r["run"] == run and r["kind"] == kind and (update is None or r["update"] == update)]
    if not cands:
        raise LabError("no %s evaluation of %r%s" % (kind, run, "" if update is None else " at update %d" % update),
                       "python3 lab/lab.py evals --run %s" % run)
    return cands[-1]


def cmd_compare(a):
    rows = tracker.load_results()
    x, y = pick(rows, a.a, a.kind, a.ua), pick(rows, a.b, a.kind, a.ub)
    return {"a": {"run": x["run"], "update": x["update"]}, "b": {"run": y["run"], "update": y["update"]}, "protocol": x.get("protocol"),
            "group": a.group, "difference_a_minus_b": tracker.compare(x, y, a.group if a.group != "h2h" else "h2h"),
            "a_summary": eval_row(x), "b_summary": eval_row(y)}


def cmd_ablation(a):
    rows, names = all_runs()
    out = []
    for n in names:
        st = tracker.run_status(n)
        v = st.get("verdict")
        if not v or v.get("p") is None:
            continue
        out.append({"run": n, "reference": v.get("reference"), "update": v.get("update"), "rewards_changed": run_row(n, rows)["rewards_changed_vs_minimal"],
                    "d_pts": v.get("pts"), "se": v.get("pts_se"), "z": v.get("z"), "p": v.get("p"), "d_gd": v.get("gd"), "paired": v.get("paired"),
                    "mde": v.get("mde"), "cost_hours": st.get("cost_hours")})
    sig = tracker.holm([r["p"] for r in out])
    for r, s in zip(out, sig):
        r["significant_holm"] = s
        r["verdict"] = ("better" if r["d_pts"] > 0 else "worse") if s else "no difference"
    return {"note": "each run vs its reference (control run or start net), Holm-corrected over these %d comparisons" % len(out), "rows": out}


def cmd_events(a):
    since = a.since or (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    ev = []
    log = os.path.join(EXP, "runner.log")
    if os.path.exists(log):
        for l in open(log, errors="replace"):
            m = re.match(r"^\[(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\] (.*)", l.rstrip())
            if m:
                t = m.group(1) + "T" + m.group(2)
                kind = next((k for k, pat in (("started", r"^started "), ("resumed", r"^resuming "), ("finished", r" finished: "), ("fast_check", r" fast: "), ("estimate", r" estimated Elo \d"),
                                              ("stopped", r" - stopping"), ("error", r"^ERROR|exited with code"), ("baseline", r"^baseline "),
                                              ("full_eval", r"full evaluation")) if re.search(pat, m.group(3))), "info")
                ev.append({"t": t, "kind": kind, "text": m.group(3)})
    for r in tracker.load_results():
        ev.append({"t": iso(r.get("time")), "kind": "eval_recorded", "text": "%s u%d %s %s pts %s" % (r["run"], r["update"], r["kind"], r.get("protocol"),
                                                                                                    r["league"].get("all", {}).get("pts"))})
    for rb in reboots():
        ev.append({"t": rb["back"], "kind": "reboot", "text": "%s rebooted (last sample %s, load %s, free %s MB, temp %s)" % (
            machine(rb["last_sample"])["name"], rb["last_seen"], rb["last_sample"]["load"], rb["last_sample"]["mem_mb"], rb["last_sample"]["temp"])})
    return sorted((e for e in ev if e["t"] and e["t"] >= since), key=lambda e: e["t"])


# ---------------------------------------------------------------- queue (writes: local files only, audited)
def audit(action, **kw):
    with open(os.path.join(EXP, "audit.jsonl"), "a") as f:
        f.write(json.dumps({"t": iso(time.time()), "action": action, **kw}) + "\n")


def queue_files():
    return sorted(glob.glob(os.path.join(EXP, "queue", "*.json")))


def renumber(files):
    """Rewrites the queue order as NN_name.json (two-step rename, so names never collide)."""
    tmp = []
    for i, f in enumerate(files):
        t = os.path.join(EXP, "queue", ".tmp_%02d" % i)
        os.replace(f, t)
        tmp.append((t, json.load(open(t))["name"]))
    for i, (t, name) in enumerate(tmp):
        os.replace(t, os.path.join(EXP, "queue", "%02d_%s.json" % (i + 1, name)))


def cmd_queue(a):
    if a.action == "list":
        out = []
        for f in queue_files():
            spec = json.load(open(f))
            rewards, args = tracker.effective(spec)
            out.append({"file": os.path.basename(f), "name": spec["name"], "start": spec.get("start"), "net": (tracker.net_info(spec.get("start")) or {}).get("label"), "updates": args["updates"], "lr": args["lr"],
                        "seed": args["seed"], "rewards_changed_vs_minimal": spec.get("rewards", {}), "args": spec.get("args", {}),
                        "control": spec.get("control"), "notes": spec.get("notes", "")})
        running = [json.load(open(f))["name"] for f in glob.glob(os.path.join(EXP, "running", "*.json"))]
        return {"running": running, "queued": out, "parked": sorted(os.path.basename(f) for f in glob.glob(os.path.join(EXP, "parked", "*.json")))}
    if a.action in ("validate", "add"):
        if not a.arg:
            raise LabError("give a spec file", "python3 lab/lab.py queue %s spec.json" % a.action)
        spec = json.load(open(a.arg))
        errs = tracker.validate_spec(spec)
        if any(json.load(open(f))["name"] == spec.get("name") for f in queue_files() + glob.glob(os.path.join(EXP, "running", "*.json"))):
            errs.append("a spec named %r is already queued or running" % spec.get("name"))
        if a.action == "validate" or errs:
            if errs and a.action == "add":
                raise LabError("invalid spec: " + "; ".join(errs), "fix the spec, then python3 lab/lab.py queue validate FILE")
            return {"valid": not errs, "errors": errs, "effective": dict(zip(("rewards", "args"), tracker.effective(spec)))}
        files = queue_files()
        dest = os.path.join(EXP, "queue", "99_%s.json" % spec["name"])
        json.dump(spec, open(dest, "w"), indent=1)
        files.insert(min(max((a.position or len(files) + 1) - 1, 0), len(files)), dest)
        renumber(files)
        audit("queue_add", name=spec["name"], position=a.position)
        return cmd_queue(argparse.Namespace(action="list"))
    if a.action == "cancel":
        running = {json.load(open(f))["name"]: f for f in glob.glob(os.path.join(EXP, "running", "*.json"))}
        if a.arg in running:
            open(os.path.join(EXP, "running", a.arg + ".cancel"), "w").write(iso(time.time()))
            audit("cancel_running", name=a.arg)
            return {"cancelling": a.arg, "note": "the runner stops it within 30 s (state 'cancelled', no full evaluation)"}
        for f in queue_files():
            if json.load(open(f))["name"] == a.arg:
                shutil.move(f, os.path.join(EXP, "parked", os.path.basename(f)))
                renumber(queue_files())
                audit("park", name=a.arg)
                return {"parked": a.arg, "note": "moved to exp/parked/ (requeue with: queue add exp/parked/<file>)"}
        raise LabError("%r is neither running nor queued" % a.arg, "python3 lab/lab.py queue list")
    if a.action == "move":
        files = queue_files()
        idx = next((i for i, f in enumerate(files) if json.load(open(f))["name"] == a.arg), None)
        if idx is None or not a.position:
            raise LabError("usage: queue move NAME --position N (NAME must be queued)", "python3 lab/lab.py queue list")
        f = files.pop(idx)
        files.insert(min(max(a.position - 1, 0), len(files)), f)
        renumber(files)
        audit("queue_move", name=a.arg, position=a.position)
        return cmd_queue(argparse.Namespace(action="list"))
    raise LabError("unknown queue action %r" % a.action, "list | validate | add | cancel | move")


def cmd_ranking(a):
    """The ratings of one size (elo/, this machine's local database; 5v5 by default): rating with 95% interval, games, record."""
    from lab import ladder
    r = ladder.ranking(getattr(a, "size", None) or 5)
    rows = r["rows"] if not a.league else [x for x in r["rows"] if x["league"] == a.league]
    keep = ("rank", "id", "name", "entry", "league", "kind", "elo", "lo", "hi", "games", "w", "d", "l", "agf", "aga", "agf_se", "aga_se",
            "gf", "ga", "bonus", "via", "placed")
    return {"protocol": r["protocol"], "size": r["size"], "matches": r["matches"], "stale": r["stale"], "last": r["last"], "rounds_off": r["off"],
            "rows": [{k: x.get(k) for k in keep} for x in rows]}


def cmd_ladder(a):
    """Starts the ratings over, when the user decides: `ladder archive` shows what would move, `ladder archive --yes` moves this
    machine's database (local/elo.db) to local/elo_archive/<date>[_<label>].db (kept, no longer counted; audited)."""
    from elo import api as elo_api
    if a.action != "archive":
        raise LabError("unknown ladder action %r" % a.action, "python3 lab/lab.py ladder archive [--label NAME] [--yes]")
    info = elo_api.archive(a.label or "", dry_run=not a.yes)
    if not info["files"]:
        raise LabError("nothing to archive: no ratings database on this machine", "python3 -m elo status")
    if not a.yes:
        return {"dry_run": True, "would_archive": info,
                "hint": "this starts the ratings over (every entry back to the prior, placement games first); add --yes to do it"}
    audit("ladder_archive", folder=info["to"], matches=info["matches"], label=info["label"])
    return {"archived": info}


def cmd_schema(_a):
    return json.load(open(os.path.join(EXP, "schema.json")))


COMMANDS = {"status": cmd_status, "runs": cmd_runs, "run": cmd_run, "evals": cmd_evals, "best": cmd_best, "compare": cmd_compare,
            "ablation": cmd_ablation, "events": cmd_events, "queue": cmd_queue, "schema": cmd_schema, "ranking": cmd_ranking,
            "estimates": cmd_estimates, "ladder": cmd_ladder}


def envelope(data):
    return {"schema_version": tracker.SCHEMA_VERSION, "generated_at": iso(time.time()), "data": data}


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pretty", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("runs")
    p.add_argument("--state")
    p = sub.add_parser("run")
    p.add_argument("name")
    p.add_argument("--tail", type=int, default=20)
    p = sub.add_parser("evals")
    p.add_argument("--run")
    p.add_argument("--kind", choices=["fast", "full"])
    p.add_argument("--protocol")
    p = sub.add_parser("best")
    p.add_argument("--protocol", default="full/g1/d90")
    p.add_argument("--k", type=int, default=5)
    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--kind", default="full", choices=["fast", "full"])
    p.add_argument("--ua", type=int, help="update of A (default: latest)")
    p.add_argument("--ub", type=int, help="update of B (default: latest)")
    p.add_argument("--group", default="league", choices=["league", "greedy", "h2h"])
    sub.add_parser("ablation")
    p = sub.add_parser("events")
    p.add_argument("--since", help="ISO time, default: last 24 h")
    p = sub.add_parser("queue")
    p.add_argument("action", choices=["list", "validate", "add", "cancel", "move"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--position", type=int)
    sub.add_parser("schema")
    p = sub.add_parser("estimates")
    p.add_argument("--run")
    p.add_argument("--matches", action="store_true", help="with the match list of each estimate")
    p = sub.add_parser("ranking")
    p.add_argument("--league", help="rules | rl | mixed | mine")
    p.add_argument("--size", type=int, default=5, help="team size 1-5 (default 5)")
    p = sub.add_parser("ladder", help="ladder archive [--label NAME] [--yes]: start the Elo ranking over (only when the user asks)")
    p.add_argument("action", choices=["archive"])
    p.add_argument("--label", help="a word for the archive folder, e.g. before_v2_rewards")
    p.add_argument("--yes", action="store_true", help="really do it (without it: only show what would move)")
    return ap


def main():
    a = parser().parse_args()
    try:
        out, code = envelope(COMMANDS[a.cmd](a)), 0
    except LabError as e:
        out, code = {"error": e.error, "hint": e.hint}, 1
    except (OSError, ValueError, KeyError) as e:
        out, code = {"error": repr(e), "hint": "see python3 lab/lab.py -h"}, 1
    print(json.dumps(out, indent=1 if a.pretty else None, default=str))
    sys.exit(code)


if __name__ == "__main__":
    main()
