"""Experiment tracker: parses evaluation files, keeps one record per evaluation in exp/results.jsonl and writes exp/results.md.

Plain files on purpose: the runner, the web dashboard (lab/dashboard.py), the agent CLI (lab/lab.py) and people all read the same ones.
Standard library only, so every one of them can import it.
  exp/queue/<NN>_<name>.json   specs waiting        exp/running/   the spec being trained     exp/done/ exp/failed/ exp/parked/
  exp/runs/<name>/status.json  state of a run (state, update, stop_reason, restarts, effective settings, verdict, cost)
  exp/results.jsonl            one record per evaluation: run, update, kind fast|full, protocol, provenance (git commit, checkpoint hash),
                               league / greedy / head-to-head summaries, behaviour, and every match (paired comparisons)
  exp/results.md               table for humans, regenerated after every evaluation
Comparisons (compare()) are only made within one evaluation protocol (fast and full are never mixed). When both records have the
per-match results they are PAIRED (same opponent, side and seed), which removes most of the noise; otherwise unpaired with a floor
on the standard error. Optional MLflow mirror (`pip install mlflow-skinny`, no server): EXP_MLFLOW=1 writes exp/mlruns/.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "exp")
RESULTS = os.path.join(EXP, "results.jsonl")
SCHEMA_VERSION = 2
MIN_SE_PER_MATCH = 0.5          # floor of the per-match spread of points (3/1/0) when a sample shows none (e.g. 8 wins out of 8)


# the experiment defaults (lab/exp_runner.py): every spec's "rewards" override MINIMAL, its "args" override DEFAULTS
MINIMAL = {"pass_individual": 1, "w_recv": 0.1, "w_open": 0.003, "w_key_pass": 0.25, "w_xa": 2.5, "coop_cap": 8, "random_start": 0.6,
           "shaping": 0, "w_keeper": 0, "w_jitter": 0, "w_far": 0, "w_xg": 0, "w_xga": 0, "w_win": 0, "w_draw": 0, "w_tackle": 0,
           "w_goalside": 0, "w_opp_half": 0, "w_compact": 0, "w_wall": 0.02, "w_corner": 0}
WALL_ON = 1795001830             # since this moment (2026-11-18, user decision after `anchor_wall_strong`) the minimal set includes w_wall 0.02; earlier runs had 0


def minimal_for(started):
    """The minimal reward set as it was when a run started (so older runs do not show w_wall as a change)."""
    m = dict(MINIMAL)
    if not started or started < WALL_ON:
        m["w_wall"] = 0
    return m

DEFAULTS = {"lr": 5e-5, "updates": 300, "workers_rule": 2, "workers_self": 1, "envs_per_worker": 16, "rollout": 128, "minibatch": 4096,
            "ckpt_every": 25, "fast_every": 50, "learn_threads": 2, "seed": 7}
FINISHED = ("done", "diverged", "regressed", "cancelled", "failed")


def selfplay_options():
    """Option names rl/selfplay.py accepts (read from its source, so this stays in sync without importing torch)."""
    return set(re.findall(r'add_argument\("--(\w+)"', open(os.path.join(ROOT, "rl", "selfplay.py")).read()))


def net_info(model):
    """The network a run starts from (and trains), read from the game-model JSON next to the checkpoint: {"sizes": [46, 128, 128, 10],
    "label": "46-128-128-10", "params": 24.4k}. None when the file is missing."""
    if not model:
        return None
    path = model if os.path.isabs(model) else os.path.join(ROOT, model)
    path = os.path.splitext(path)[0] + ".json"
    try:
        sizes = json.load(open(path))["sizes"]
    except (OSError, ValueError, KeyError):
        return None
    params = sum(a * b + b for a, b in zip(sizes, sizes[1:]))
    return {"sizes": sizes, "label": "-".join(str(x) for x in sizes), "params": params}


def validate_spec(spec):
    """List of problems of an experiment spec (empty = fine)."""
    errs = []
    name = spec.get("name", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,40}", str(name)):
        errs.append("name must be 2-41 chars of a-z, 0-9, _")
    elif run_status(name).get("state") in FINISHED or os.path.exists(os.path.join(EXP, "runs", name)) and run_status(name).get("state") != "running":
        errs.append("name %r is already used by a run (pick a new name)" % name)
    start = spec.get("start", "")
    if not start or not os.path.isfile(os.path.join(ROOT, start)):
        errs.append("start checkpoint %r not found" % start)
    elif not os.path.isfile(os.path.join(ROOT, start[:-3] + ".json" if start.endswith(".pt") else start)):
        errs.append("start needs its game-model JSON next to it")
    opts = selfplay_options()
    for k in list(spec.get("rewards", {})) + list(spec.get("args", {})):
        if k not in opts:
            errs.append("unknown selfplay option %r" % k)
    if not 1 <= int(spec.get("updates", DEFAULTS["updates"])) <= 20000:
        errs.append("updates must be 1..20000")
    if spec.get("control") and not (run_status(spec["control"]) or latest_any(spec["control"])):
        errs.append("control run %r does not exist" % spec["control"])
    return errs


def effective(spec):
    """(rewards, args) a spec really trains with: the defaults merged with its overrides."""
    rewards = {**MINIMAL, **spec.get("rewards", {})}
    args = {**DEFAULTS, **{k: spec[k] for k in ("lr", "updates") if k in spec}, **spec.get("args", {})}
    return rewards, args


def latest_any(run):
    return next((r for r in reversed(load_results()) if r["run"] == run), None)


def boot_id():
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip()[:8]
    except OSError:
        return None


def _num(pattern, text, cast=float):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


def parse_eval(path):
    """Evaluation text file (rl/eval_checkpoint.py) -> dict. Missing parts are simply absent."""
    text = open(path).read()
    r = {"league": {}, "greedy": {}, "h2h": {}, "behaviour": {}, "matches": []}
    for line in text.splitlines():
        m = re.match(r"^EVAL (\S+)(?: \| mode (\w+))? \| league games/side (\d+) \| duration (\d+)s \| h2h games/side (\d+)", line)
        if m:
            r["checkpoint"] = m.group(1)
            r["protocol"] = "%s/g%s/d%s" % (m.group(2) or "full", m.group(3), m.group(4))      # what makes league numbers comparable
            r["h2h_games"] = int(m.group(5))
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
        m = re.match(r"^(greedy )?MATCH (\S+) (\d) (\d+) (\d+) (\d+)", line)
        if m:                                   # [group, opponent, side, seed, goals for, goals against]
            opp = m.group(2)
            group = "h2h" if opp.startswith("h2h:") else ("greedy" if m.group(1) else "league")
            r["matches"].append([group, opp[4:].replace("_", " ") if group == "h2h" else opp, int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6))])
        if line.startswith("SCOUT "):                          # scouting summary (rl/evaluate.py behaviour_stats): shape, roles, pressing, events
            try:
                r["scout"] = json.loads(line[6:])
            except ValueError:
                pass
        m = re.match(r"^rule-based: (.*)", line)                # the rule bots' numbers in the same matches: the reference
        if m:
            t = m.group(1)
            r.setdefault("behaviour_rule", {}).update({k: v for k, v in {
                "dir_changes_s": _num(r"dir changes/s ([\d.]+)", t), "idle_pct": _num(r"idle (\d+)%", t), "spacing_px": _num(r"teammates spacing (\d+) px", t),
                "keeper_dist_px": _num(r"keeper dist from own goal (\d+) px", t), "passes_match": _num(r"passes/match ([\d.]+)", t),
                "shots_match": _num(r"shots/match ([\d.]+)", t), "key_passes_match": _num(r"key passes/match ([\d.]+)", t),
                "xa_match": _num(r"xA/match ([\d.]+)", t)}.items() if v is not None})
        m = re.match(r"^(greedy )?RL Team: (.*)", line)
        if m and not m.group(1):
            t = m.group(2)
            vals = {"dir_changes_s": _num(r"dir changes/s ([\d.]+)", t), "idle_pct": _num(r"idle (\d+)%", t),
                    "spacing_px": _num(r"teammates spacing (\d+) px", t), "keeper_dist_px": _num(r"keeper dist from own goal (\d+) px", t)}
            r["behaviour"].update({k: v for k, v in vals.items() if v is not None})
        if line.startswith("RL Team: players within 250px"):
            r["behaviour"].update({k: v for k, v in {"passes_match": _num(r"passes/match ([\d.]+)", line), "shots_match": _num(r"shots/match ([\d.]+)", line),
                                                    "key_passes_match": _num(r"key passes/match ([\d.]+)", line), "xa_match": _num(r"xA/match ([\d.]+)", line)}.items() if v is not None})
    m = re.search(r"^DONE (\d+)", text, re.M)
    r["seconds"] = int(m.group(1)) if m else None
    return r


def git_commit():
    """(short commit, dirty) of the project, or (None, None)."""
    try:
        c = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        d = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=no", "--", "soccer", "rl", "lab"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        return c or None, bool(d)
    except (OSError, subprocess.SubprocessError):
        return None, None


def file_hash(path):
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]
    except OSError:
        return None


def add_result(run, update, kind, path, extra=None):
    """Appends one evaluation to exp/results.jsonl (kind: 'fast' | 'full'), regenerates results.md, mirrors to MLflow if enabled."""
    parsed = parse_eval(path)
    commit, dirty = git_commit()
    ck = parsed.get("checkpoint")
    rec = {"schema": SCHEMA_VERSION, "id": "%s@u%d:%s:%d" % (run, update, kind, int(time.time())), "time": int(time.time()), "run": run,
           "update": update, "kind": kind, "file": os.path.relpath(os.path.abspath(path), ROOT), "git_commit": commit, "git_dirty": dirty,
           "checkpoint_sha1": file_hash(os.path.join(ROOT, ck)) if ck else None, **parsed, **(extra or {})}
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
    out = []
    for line in open(RESULTS):
        if line.strip():
            rec = json.loads(line)
            rec.setdefault("protocol", "full/g1/d90" if rec.get("kind") == "full" else "fast/g2/d60")
            rec.setdefault("matches", [])
            out.append(rec)
    return out


def latest(run, kind="full", update=None, rows=None):
    rows = [r for r in (rows if rows is not None else load_results()) if r["run"] == run and r["kind"] == kind and (update is None or r["update"] == update)]
    return rows[-1] if rows else None


def _pts(gf, ga):
    return 3.0 if gf > ga else (1.0 if gf == ga else 0.0)


def _mean_se(xs):
    n = len(xs)
    if n == 0:
        return None, None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / max(n - 1, 1)
    return m, math.sqrt(var / n)


def p_two_sided(z):
    return math.erfc(abs(z) / math.sqrt(2.0))


def compare(a, b, group="league", subset="all"):
    """Difference a - b of two evaluation records (a = the candidate, b = the reference) in points and goal difference.
    Same protocol only. Paired over identical matches (opponent, side, seed) when both records have them, else unpaired.
    Returns {pts, pts_se, z, p, gd, gd_se, z_gd, n, paired, mde, verdict}; verdict at |z| > 1.96 (no multiple-comparison correction:
    use holm() over a batch of arms)."""
    if a is None or b is None:
        return {"verdict": "unknown", "reason": "missing evaluation"}
    if a.get("protocol") != b.get("protocol"):
        return {"verdict": "incomparable", "reason": "different protocols: %s vs %s" % (a.get("protocol"), b.get("protocol"))}
    ma = {(m[1], m[2], m[3]): m for m in a.get("matches", []) if m[0] == group}
    mb = {(m[1], m[2], m[3]): m for m in b.get("matches", []) if m[0] == group}
    keys = sorted(set(ma) & set(mb))
    if group == "league" and subset != "all":
        keys = []                                              # tiers: per-match tiers are not stored, use the summaries
    out = {}
    if len(keys) >= 8:
        dp = [_pts(ma[k][4], ma[k][5]) - _pts(mb[k][4], mb[k][5]) for k in keys]
        dg = [(ma[k][4] - ma[k][5]) - (mb[k][4] - mb[k][5]) for k in keys]
        (mp, sp), (mg, sg) = _mean_se(dp), _mean_se(dg)
        floor = MIN_SE_PER_MATCH / math.sqrt(len(keys))
        out = {"pts": mp, "pts_se": max(sp, floor), "gd": mg, "gd_se": max(sg, floor), "n": len(keys), "paired": True}
    else:
        src = a["league"] if group == "league" else a.get(group, {})
        ref = b["league"] if group == "league" else b.get(group, {})
        x, y = src.get(subset), ref.get(subset)
        if not x or not y:
            return {"verdict": "unknown", "reason": "no %s/%s summary" % (group, subset)}
        se = lambda s: max(s["se"], MIN_SE_PER_MATCH / math.sqrt(max(s["n"], 1)))
        gse = lambda s: max(s.get("gd_se") or s["se"] * 1.6, MIN_SE_PER_MATCH / math.sqrt(max(s["n"], 1)))
        out = {"pts": x["pts"] - y["pts"], "pts_se": math.hypot(se(x), se(y)), "gd": x["gd"] - y["gd"], "gd_se": math.hypot(gse(x), gse(y)),
               "n": min(x["n"], y["n"]), "paired": False}
    out["z"] = out["pts"] / out["pts_se"]
    out["z_gd"] = out["gd"] / out["gd_se"]
    out["p"] = p_two_sided(out["z"])
    out["mde"] = 2.8 * out["pts_se"]                           # smallest difference detectable at 5% two-sided, 80% power
    out["verdict"] = "better" if out["z"] > 1.96 else ("worse" if out["z"] < -1.96 else "no difference")
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def holm(pvals, alpha=0.05):
    """Holm-Bonferroni over a batch of comparisons that share a reference: list of booleans 'significant' in input order."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    sig = [False] * len(pvals)
    for rank, i in enumerate(order):
        if pvals[i] <= alpha / (len(pvals) - rank):
            sig[i] = True
        else:
            break
    return sig


def run_status(name):
    p = os.path.join(EXP, "runs", name, "status.json")
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


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
    run_dir = os.path.join(EXP, "runs")
    runs = sorted({r["run"] for r in rows} | (set(os.listdir(run_dir)) if os.path.isdir(run_dir) else set()))
    lines = ["# Experiment results", "", "Updated %s. pts = league points per match (16 rule teams, both sides), gd = goal difference per match, "
             "mean ± standard error. Verdicts compare within one protocol (fast and full are never mixed), paired over identical matches "
             "when possible. `python3 lab/lab.py` gives the same data as JSON." % time.strftime("%Y-%m-%d %H:%M"), "",
             "| run | net | state | update | protocol | pts ± se | gd | GA | vs RL4 | vs RL5 | dir chg/s | idle % | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for run in runs:
        st = run_status(run)
        for kind in ("full", "fast"):
            r = latest(run, kind, rows=rows)
            if not r:
                continue
            a, h, b = r["league"].get("all", {}), r["h2h"], r["behaviour"]
            v = (st.get("verdict") or {}) if kind == "full" else {}
            lines.append("| %s | %s | %s | %s | %s | %s ± %s | %s | %s | %s | %s | %s | %s | %s |" % (
                run, (st.get("net") or net_info(st.get("spec", {}).get("start")) or {}).get("label", "-"), st.get("state", "imported"), r["update"], r.get("protocol"), a.get("pts", "-"), a.get("se", "-"), a.get("gd", "-"), a.get("ga", "-"),
                (h.get("RL Team 4") or {}).get("pts", "-"), (h.get("RL Team 5") or {}).get("pts", "-"),
                b.get("dir_changes_s", "-"), b.get("idle_pct", "-"), ("%s (vs %s)" % (v.get("verdict"), v.get("reference"))) if v.get("verdict") else ""))
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
        mlflow.log_params({"run": rec["run"], "update": rec["update"], "kind": rec["kind"], "protocol": rec.get("protocol"), "git_commit": rec.get("git_commit")})
        for k, v in rec["league"].get("all", {}).items():
            if v is not None:
                mlflow.log_metric("league_" + k, v)
        for name, h in rec["h2h"].items():
            mlflow.log_metric("h2h_%s_pts" % name.replace(" ", "_"), h["pts"])
        for k, v in rec["behaviour"].items():
            if v is not None:
                mlflow.log_metric(k, v)
