"""Experiment tracker: parses evaluation files, keeps one record per evaluation in exp/results.jsonl and writes exp/results.md.

The tracker is plain files on purpose: the runner, the web dashboard and the agent that reads the results all use the same ones.
  exp/queue/<NN>_<name>.json   specs waiting          exp/runs/<name>/status.json   state of a run (queued/running/done/...)
  exp/results.jsonl            one line per evaluation (run, update, kind fast|full, pts, se, gd, h2h, behaviour, ...)
  exp/results.md               table for humans and for the agent, regenerated after every evaluation
Optional mirror to MLflow (no server needed, `pip install mlflow-skinny`): set EXP_MLFLOW=1; the standard exp/mlruns/ folder can be
copied to another machine and browsed with `mlflow ui`.
"""
import json
import math
import os
import re
import time

from client import ROOT

EXP = os.path.join(ROOT, "exp")
RESULTS = os.path.join(EXP, "results.jsonl")


def _num(pattern, text, cast=float):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


def parse_eval(path):
    """Evaluation text file (rl/eval_checkpoint.py) -> dict. Missing parts are simply absent."""
    r = {"league": {}, "greedy": {}, "h2h": {}, "behaviour": {}}
    for line in open(path).read().splitlines():
        m = re.match(r"^(greedy )?SUMMARY (\w+)\s*: pts/m (\S+)\s+GF (\S+) GA (\S+)\s+\((\d+) matches\) se (\S+)(?: gd (\S+) gdse (\S+))?", line)
        if m:
            g, gf, ga = m.group(1), float(m.group(4)), float(m.group(5))
            d = {"pts": float(m.group(3)), "se": float(m.group(7)), "gf": gf, "ga": ga, "n": int(m.group(6)),
                 "gd": float(m.group(8)) if m.group(8) else round(gf - ga, 3), "gd_se": float(m.group(9)) if m.group(9) else None}
            (r["greedy"] if g else r["league"])[m.group(2)] = d
        m = re.match(r"^H2H (.+?): W (\d+) D (\d+) L (\d+) \| pts/m (\S+) \| GF/GA (\S+)/(\S+) \| (\d+) matches \| se (\S+)(?: \| gd (\S+) gdse (\S+))?", line)
        if m:
            gf, ga = float(m.group(6)), float(m.group(7))
            r["h2h"][m.group(1)] = {"pts": float(m.group(5)), "se": float(m.group(9)), "gf": gf, "ga": ga, "n": int(m.group(8)),
                                    "w": int(m.group(2)), "d": int(m.group(3)), "l": int(m.group(4)),
                                    "gd": float(m.group(10)) if m.group(10) else round(gf - ga, 3), "gd_se": float(m.group(11)) if m.group(11) else None}
        m = re.match(r"^(greedy )?RL Team: (.*)", line)
        if m and not m.group(1):
            t = m.group(2)
            vals = {"dir_changes_s": _num(r"dir changes/s ([\d.]+)", t), "idle_pct": _num(r"idle (\d+)%", t),
                    "spacing_px": _num(r"teammates spacing (\d+) px", t)}
            r["behaviour"].update({k: v for k, v in vals.items() if v is not None})
        m = re.match(r"^RL Team: players within 250px.*", line)
        if m:
            t = line
            r["behaviour"].update({"passes_match": _num(r"passes/match ([\d.]+)", t), "shots_match": _num(r"shots/match ([\d.]+)", t),
                                   "xa_match": _num(r"xA/match ([\d.]+)", t)})
    m = re.search(r"^DONE (\d+)", open(path).read(), re.M)
    r["seconds"] = int(m.group(1)) if m else None
    return r


def add_result(run, update, kind, path, extra=None):
    """Appends one evaluation to exp/results.jsonl (kind: 'fast' | 'full'), regenerates results.md, mirrors to MLflow if enabled."""
    rec = {"time": int(time.time()), "run": run, "update": update, "kind": kind, "file": os.path.relpath(os.path.abspath(path), ROOT),
           **parse_eval(path), **(extra or {})}
    os.makedirs(EXP, exist_ok=True)
    with open(RESULTS, "a") as f:
        f.write(json.dumps(rec) + "\n")
    write_markdown()
    if os.environ.get("EXP_MLFLOW") == "1":
        _mlflow(rec)
    return rec


def load_results():
    if not os.path.exists(RESULTS):
        return []
    return [json.loads(l) for l in open(RESULTS) if l.strip()]


def latest(run, kind="full", update=None):
    rows = [r for r in load_results() if r["run"] == run and r["kind"] == kind and (update is None or r["update"] == update)]
    return rows[-1] if rows else None


def compare(a, b):
    """Difference a - b of two evaluation records on the league (all teams): points and goal difference, with a verdict that
    uses the combined standard error. Differences below 1.96 standard errors are called 'no difference'."""
    out = {}
    for key, label in (("pts", "pts"), ("gd", "gd")):
        x, y = a["league"].get("all"), b["league"].get("all")
        if not x or not y:
            return {"verdict": "unknown"}
        se_x = x["se"] if key == "pts" else (x.get("gd_se") or x["se"] * 1.6)       # goal difference has a larger spread than points; fallback if the old file has no gd se
        se_y = y["se"] if key == "pts" else (y.get("gd_se") or y["se"] * 1.6)
        out[label] = round(x[key] - y[key], 2)
        out[label + "_se"] = round(math.sqrt(se_x ** 2 + se_y ** 2), 2)
    z = out["pts"] / max(out["pts_se"], 1e-9)
    out["verdict"] = "better" if z > 1.96 else ("worse" if z < -1.96 else "no difference")
    return out


def run_status(name):
    p = os.path.join(EXP, "runs", name, "status.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def set_status(name, **kw):
    d = os.path.join(EXP, "runs", name)
    os.makedirs(d, exist_ok=True)
    st = run_status(name)
    st.update(kw)
    st["name"] = name
    st["updated"] = int(time.time())
    tmp = os.path.join(d, "status.json.tmp")
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(d, "status.json"))
    write_markdown()


def write_markdown():
    rows = load_results()
    runs = sorted({r["run"] for r in rows} | {d for d in os.listdir(os.path.join(EXP, "runs"))} if os.path.isdir(os.path.join(EXP, "runs")) else {r["run"] for r in rows})
    lines = ["# Experiment results", "", "Updated %s. pts = league points per match (all 16 rule teams, both sides), gd = goal difference per match, "
             "values are mean ± standard error. A difference smaller than about 2 standard errors is noise." % time.strftime("%Y-%m-%d %H:%M"), "",
             "| run | state | update | kind | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | spacing px | verdict vs start |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for run in runs:
        st = run_status(run)
        base = latest(st.get("baseline_run", ""), "full") if st.get("baseline_run") else None
        for kind in ("full", "fast"):
            r = latest(run, kind)
            if not r:
                continue
            a = r["league"].get("all", {})
            h = r["h2h"]
            b = r["behaviour"]
            ver = compare(r, base)["verdict"] if base and kind == "full" and base is not r else ""
            lines.append("| %s | %s | %s | %s | %s ± %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                run, st.get("state", "imported"), r["update"], kind, a.get("pts", "-"), a.get("se", "-"), a.get("gd", "-"), a.get("ga", "-"),
                (h.get("RL Team 4") or {}).get("pts", "-"), (h.get("RL Team 5") or {}).get("pts", "-"),
                b.get("dir_changes_s", "-"), b.get("idle_pct", "-"), b.get("spacing_px", "-"), ver))
    lines += ["", "Runs: " + ", ".join("%s (%s)" % (r, run_status(r).get("state", "imported")) for r in runs), ""]
    os.makedirs(EXP, exist_ok=True)
    tmp = os.path.join(EXP, "results.md.tmp")
    open(tmp, "w").write("\n".join(lines))
    os.replace(tmp, os.path.join(EXP, "results.md"))


def _mlflow(rec):
    try:
        import mlflow
    except ImportError:
        return
    mlflow.set_tracking_uri("file://" + os.path.join(EXP, "mlruns"))
    mlflow.set_experiment("simple-soccer")
    with mlflow.start_run(run_name="%s_u%d_%s" % (rec["run"], rec["update"], rec["kind"])):
        mlflow.log_params({"run": rec["run"], "update": rec["update"], "kind": rec["kind"]})
        for k, v in rec["league"].get("all", {}).items():
            mlflow.log_metric("league_" + k, v)
        for name, h in rec["h2h"].items():
            mlflow.log_metric("h2h_%s_pts" % name.replace(" ", "_"), h["pts"])
        for k, v in rec["behaviour"].items():
            if v is not None:
                mlflow.log_metric(k, v)
