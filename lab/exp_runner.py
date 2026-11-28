"""Experiment runner: takes experiment specs from exp/queue/, trains each one with rl/selfplay.py, evaluates it, decides, repeats.

An experiment is one small JSON file (exp/queue/<NN>_<name>.json), run in file-name order:
  {"name": "win_bonus", "start": "out_5v5/team46_start.pt", "updates": 300, "lr": 5e-5,
   "rewards": {"w_win": 3.0, "w_draw": 1.0}, "notes": "does the win/draw bonus help on top of the minimal set?"}
`rewards` overrides MINIMAL below (goals, passing, cooperation, spacing while attacking, kick discipline); any selfplay option can be given
in "args" (e.g. {"workers_rule": 2}). Per experiment the runner:
  1. estimates the start net's Elo (update 0 of the run); with `fast_rules` 1 also its fixed rule-bot checks (fast + full, cached),
  2. trains; every `fast_every` updates selfplay pauses for a check: an estimated Elo (lab/ladder.py estimate: `elo_pairs` pairs
     of matches against mixed ladder entries, exp/elo_estimates.jsonl), plus the fixed rule-bot matches when `fast_rules` is 1,
  3. stops early: `diverged` (training points vs the rule bots fall under 70% of their start value, for a run that starts at 1
     point per match or more; a spec with "diverge": false switches it off, e.g. to see whether a new size recovers from a dip)
     or `regressed`
     (two estimated Elos in a row below the start net's by more than 2 standard errors of the difference),
  4. otherwise runs a FULL evaluation (behaviour, scouting) of the last checkpoint and of the one with the highest estimated Elo,
     keeps the better of the two by estimated Elo as the run's best checkpoint (x_<run>_best) and places it in the Elo ladder.
     There is no better / worse verdict: a run is judged by its Elo in the ladder, which keeps updating as more matches are played.
Curricula (phase D): a spec may train another team size ("size" 1..5, "obs": "slots"), on an empty pitch ("opp": "none", the 1v0
stage), from a fresh net ("start": "scratch") or from an earlier run's best checkpoint ("start": "best:<run>"), and stop on a
plateau ("plateau": K = stop once K estimated Elos in a row have not beaten the best one by PLATEAU_GAIN, after "min_updates").
`lab.py queue add` turns a curriculum spec ({"name", "stages": [...]}) into one such spec per stage (tracker.expand). Below 5v5
there is no full evaluation: the best checkpoint is the one with the highest estimated Elo at the stage's size (the last one on
an empty pitch), and it is placed in that size's ratings.
Everything is written to exp/ (see lab/tracker.py). After a reboot the runner resumes the running experiment from its last checkpoint.

  lab/run.sh                                         (the usual way: background QoS, health sampler, thermal guard; lab/SETUP.md)
  python3 lab/exp_runner.py --loop [--viewer]          (with the venv active, lab/SETUP.md)

While the queue is empty (--loop) it plays rounds of the Elo ranking (lab/ladder.py round: 6 pairs, 2 matches each, 3 niced
workers, a few minutes) and looks at the queue again after each round. `touch local/refine_off` stops that (and the web
app's refining); a finished run is still placed.
"""
import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

if os.path.realpath(sys.path[0]) == os.path.dirname(os.path.realpath(__file__)):
    del sys.path[0]                 # run as lab/<script>.py: lab/ would come first and lab/lab.py would hide the lab package
from lab import tracker

ROOT, EXP = tracker.ROOT, tracker.EXP
CKPT = os.path.join(ROOT, "out_5v5", "ckpt")
MINIMAL, DEFAULTS = tracker.MINIMAL, tracker.DEFAULTS
DIVERGE_FRACTION = 0.7          # training points vs the rule bots below this share of their starting value: stop
DIVERGE_MIN = 1.0               # ... only for a run that starts at least this strong (points per match): near 0 the share is noise
REGRESS_SE = 2.0                # estimated Elo below the start net's by more than this many standard errors, twice in a row: stop
PLATEAU_GAIN = 25.0             # Elo: an estimate counts as progress only when it beats the best one so far by this much


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(EXP, "runner.log"), "a") as f:
        f.write(line + "\n")


def json_of(path):
    """game-model JSON next to a checkpoint (.pt) or a model (.json), relative to the project"""
    p = path[:-3] + ".json" if path.endswith(".pt") else path
    return os.path.relpath(os.path.abspath(os.path.join(ROOT, p)), ROOT)


def stop_stale_workers():
    """Leftovers of a killed trainer or evaluation (they would hold the ports and the CPU). Training workers end on their own
    when their trainer is gone (their pipe closes)."""
    for pat in ("rl/eval_checkpoint.py", "rl/evaluate.py", "lab/live.py --tag"):
        out = subprocess.run(["pgrep", "-f", pat], stdout=subprocess.PIPE, text=True).stdout.split()
        for pid in out:
            if int(pid) != os.getpid():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass


def evaluate(model, out, mode, refs=None, extra=()):
    """Runs rl/eval_checkpoint.py (blocking). refs: [(name, model)] extra head-to-head opponents. Returns True if the file was written."""
    if os.path.exists(os.path.join(ROOT, out)):
        os.remove(os.path.join(ROOT, out))
    cmd = [sys.executable, os.path.join(ROOT, "rl", "eval_checkpoint.py"), "--model", os.path.join(ROOT, model), "--out", os.path.join(ROOT, out), "--mode", mode, "--paused"]
    for name, ref in refs or []:
        cmd += ["--ref", "%s=%s" % (name, ref)]
    subprocess.run(cmd + list(extra), cwd=os.path.join(ROOT, "rl"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(os.path.join(ROOT, out))


def baseline(start_json):
    """Fast + full evaluation of the start net, done once per start file. Returns its name in exp/results.jsonl."""
    name = "start:" + os.path.basename(start_json)[:-5]
    for kind in ("fast", "full"):
        if tracker.latest(name, kind):
            continue
        out = "logs/sp_eval/%s_%s.txt" % (name.replace(":", "_"), kind)
        log("baseline %s evaluation of %s" % (kind, start_json))
        if evaluate(start_json, out, kind):
            tracker.add_result(name, 0, kind, os.path.join(ROOT, out))
    return name


def selfplay_cmd(spec, tag, start, start_update, started=None):
    """start: the checkpoint to continue from (a resume) or the spec's start (None: a fresh net)."""
    rewards, args = tracker.effective(spec, started)
    first = tracker.start_model(spec)
    cmd = [sys.executable, os.path.join(ROOT, "rl", "selfplay.py"), "--obs", spec.get("obs", "team"), "--start", start or "scratch",
           "--start_update", str(start_update), "--tag", tag, "--eval_every", "0", "--log_every", "2",
           "--size", str(spec.get("size", 5)), "--opp_mode", spec.get("opp", "rules")]
    if first:                                                        # the frozen benchmark is always the net the experiment started from
        cmd += ["--fast_ref", json_of(first), "--baseline", os.path.join(ROOT, first)]
    if spec.get("opp") == "none" and "workers_self" not in args:
        cmd += ["--workers_self", "0"]
    for k, v in {**args, **rewards}.items():
        cmd += ["--" + k, str(v)]
    return cmd


def last_checkpoint(tag):
    found = [(int(re.search(r"_u(\d+)\.pt$", p).group(1)), p) for p in glob.glob(os.path.join(CKPT, tag + "_u*.pt"))]
    return max(found) if found else (0, None)


def progress(tag):
    """(update, training points per match vs the rule bots, number of matches) of the last logged update."""
    rows = tracker.train_rows(tag)
    if not rows:
        return 0, None, 0
    r = rows[-1]
    return int(r["upd"]), r.get("rules"), int(r.get("n_rules") or 0)


def start_viewer(tag, model):
    """--viewer: the live demo match (lab/live.py: the newest checkpoint on the match core, streamed to the dashboard's Live page)."""
    return [viewer_window(tag, model)]


def viewer_window(tag, model):
    """The match shown live: lab/live.py (restarted by the runner if it stops)."""
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "lab", "live.py"), "--tag", tag, "--start", model],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def viewer_target():
    """(tag, start model) the live demo should show: the running experiment, else the most recently updated one.
    (None, None) when there is none."""
    best = None
    for f in glob.glob(os.path.join(EXP, "runs", "*", "status.json")):
        try:
            st = json.load(open(f))
            key = (st.get("state") == "running", os.path.getmtime(f))
            if st.get("tag") and (best is None or key > best[0]):
                best = (key, st["tag"], json_of(st["spec"]["start"]))
        except (OSError, ValueError, KeyError):
            continue
    return (best[1], best[2]) if best else (None, None)


def elo_estimate(model, tag, update, pairs, size=5):
    """lab/ladder.py estimate of one checkpoint at a team size (blocking). The record, or None."""
    if pairs <= 0:
        return None
    p = subprocess.run([sys.executable, os.path.join(ROOT, "lab", "ladder.py"), "estimate", "--model", os.path.join(ROOT, model), "--tag", tag,
                        "--update", str(update), "--pairs", str(pairs), "--workers", "3", "--size", str(size)], cwd=ROOT, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        log("estimated Elo of %s u%d failed: %s" % (tag, update, p.stdout.strip()[-300:]))
        return None


def keep_best(tag, update):
    """Makes checkpoint `update` the run's best (out_5v5/ckpt/<tag>_best.json/.pt, logs/<tag>_best.json): the ladder entry of the run."""
    src = os.path.join(CKPT, "%s_u%d" % (tag, update))
    if not os.path.exists(src + ".json"):
        return
    shutil.copy(src + ".json", os.path.join(CKPT, tag + "_best.json"))
    if os.path.exists(src + ".pt"):
        shutil.copy(src + ".pt", os.path.join(CKPT, tag + "_best.pt"))
    with open(os.path.join(ROOT, "logs", tag + "_best.json"), "w") as f:
        json.dump({"checkpoint": "%s_u%d" % (tag, update), "update": update, "by": "estimated Elo", "model": os.path.relpath(src + ".json", ROOT)}, f)


def place_in_ladder(tag, rounds=3, size=5):
    """Plays rounds of the ratings of the run's size right after it until its best checkpoint is placed (PLACEMENT games):
    otherwise a busy queue would leave it unrated. New entries are paired first (elo/schedule.py)."""
    from lab import ladder
    for _ in range(rounds):
        rat = ladder.rows(size)
        r = rat.get("net:%s_best" % tag)
        if r is None or r["games"] >= ladder.PLACEMENT or not ladder_round(size=size, force=True):
            return


def run_experiment(spec_path, viewer=False):
    spec = json.load(open(spec_path))
    name = spec["name"]
    tag = "x_" + name
    st = tracker.run_status(name)
    if os.path.dirname(spec_path) != os.path.join(EXP, "running"):          # a new experiment: check it, then it owns exp/running/
        errs = tracker.validate_spec(spec)
        if errs:
            log("refusing %s: %s" % (os.path.basename(spec_path), "; ".join(errs)))
            shutil.move(spec_path, os.path.join(EXP, "failed", os.path.basename(spec_path)))
            if not st:
                tracker.set_status(name, state="failed", stop_reason="invalid spec", error="; ".join(errs))
            return
        dest = os.path.join(EXP, "running", os.path.basename(spec_path))
        shutil.move(spec_path, dest)
        spec_path = dest
    rewards, args = tracker.effective(spec, st.get("started"))      # a resumed run keeps the defaults it started with
    first = tracker.start_model(spec)                               # None: a fresh net
    size, opp = int(spec.get("size", 5)), spec.get("opp", "rules")
    if first and not os.path.exists(os.path.join(ROOT, first)):    # a curriculum stage whose previous stage left no best checkpoint
        log("refusing %s: its start %s does not exist" % (name, first))
        tracker.set_status(name, state="failed", stop_reason="no start", error="start %s not found" % first, spec=spec)
        shutil.move(spec_path, os.path.join(EXP, "failed", os.path.basename(spec_path)))
        return
    start_json = json_of(first) if first else None
    fast_rules = int(args.get("fast_rules", 1) or 0) if size == 5 and opp == "rules" else 0
    base_name = (baseline(start_json) if fast_rules else "start:" + os.path.basename(start_json)[:-5]) if start_json else None
    base_fast = tracker.latest(base_name, "fast") if base_name else None
    plateau, min_updates = int(spec.get("plateau", 0) or 0), int(spec.get("min_updates", 0) or 0)
    upd_end = int(spec.get("updates", DEFAULTS["updates"]))
    start_update, ckpt = last_checkpoint(tag)
    restarts = st.get("restarts", [])
    boot = tracker.boot_id()
    if ckpt and st.get("state") == "running":
        reason = "reboot" if st.get("boot_id") and st.get("boot_id") != boot else "runner restart"
        restarts.append({"at": int(time.time()), "update": start_update, "reason": reason})
        log("resuming %s from update %d (%s)" % (name, start_update, reason))
        start = os.path.relpath(ckpt, ROOT)
    else:
        start, start_update = first, 0
    elo_pairs = int(args.get("elo_pairs", 0) or 0) if opp == "rules" else 0
    from lab import ladder
    if elo_pairs and start_json and not any(e.get("update") == 0 for e in ladder.estimates(run=name)):
        log("%s: estimated Elo of the start net at %dv%d" % (name, size, size))
        elo_estimate(start_json, tag, 0, elo_pairs, size)
    commit, dirty = tracker.git_commit()
    tracker.set_status(name, state="running", spec=spec, baseline_run=base_name, started=st.get("started", int(time.time())), tag=tag,
                       target_updates=upd_end, effective_rewards=rewards, effective_args=args, seed=args.get("seed"), git_commit=commit,
                       git_dirty=dirty, boot_id=boot, restarts=restarts, control=spec.get("control"), net=tracker.net_info(first),
                       size=size, opp=opp, curriculum=spec.get("curriculum"), stage=spec.get("stage"))
    done = set(st.get("recorded", []))
    done_est = set(st.get("recorded_est", []))
    base_train = st.get("base_train")
    bad_checks = st.get("bad_checks", 0)
    train_s = st.get("train_s", 0.0)
    stop_reason = "budget"
    procs = []
    cancel_flag = os.path.join(EXP, "running", name + ".cancel")
    no_gain = st.get("no_gain", 0)
    if start_update < upd_end:
        if viewer and start_json:
            procs += start_viewer(tag, start_json)
        out = open(os.path.join(ROOT, "logs", tag + ".out"), "a")
        proc = subprocess.Popen(selfplay_cmd(spec, tag, os.path.join(ROOT, start) if start else None, start_update, st.get("started")), cwd=ROOT,
                                stdout=out, stderr=subprocess.STDOUT)
        log("started %s (pid %d)" % (name, proc.pid))
        last = time.time()
        while proc.poll() is None:
            time.sleep(30)
            now = time.time()
            if not os.path.exists(os.path.join(ROOT, "logs", tag + "_eval_running.json")):
                train_s += now - last                                    # wall time spent training (fast checks excluded)
            last = now
            if viewer and procs and procs[-1].poll() is not None:
                log("viewer closed (exit %s): starting it again" % procs[-1].returncode)
                procs[-1] = viewer_window(tag, start_json)
            upd, pts, n = progress(tag)
            if pts is not None and n >= 96 and base_train is None:
                base_train = pts
            for path in sorted(glob.glob(os.path.join(ROOT, "logs", "sp_eval", tag + "_u*_fast.txt"))):
                u = int(re.search(r"_u(\d+)_fast", path).group(1))
                if u in done:
                    continue
                done.add(u)
                rec = tracker.add_result(name, u, "fast", path)
                c = tracker.compare(rec, base_fast)
                if c.get("z") is not None:
                    log("%s u%d fast: pts %.2f, vs start %+.2f ± %.2f (%s, z %.1f)" % (name, u, rec["league"]["all"]["pts"], c["pts"], c["pts_se"],
                                                                                     "paired" if c["paired"] else "unpaired", c["z"]))
            ests = ladder.estimates(run=name)
            e0 = next((e for e in ests if e.get("update") == 0), None)
            for e in ests:                                             # the regression check: estimated Elo against the start net's
                if not e.get("update") or e["update"] in done_est:
                    continue
                done_est.add(e["update"])
                best_before = max((x["elo"] for x in ests if x.get("update") and x["update"] < e["update"]), default=None)
                no_gain = 0 if best_before is None or e["elo"] > best_before + PLATEAU_GAIN else no_gain + 1
                if e0:
                    z = (e["elo"] - e0["elo"]) / max(1e-9, (e["se"] ** 2 + e0["se"] ** 2) ** 0.5)
                    bad_checks = bad_checks + 1 if z < -REGRESS_SE else 0
                    log("%s u%d estimated Elo %.0f ± %.0f, vs start %+.0f (z %.1f), GF %.2f GA %.2f" % (name, e["update"], e["elo"], 1.96 * e["se"],
                                                                                                    e["elo"] - e0["elo"], z, e["gf"], e["ga"]))
            tracker.set_status(name, update=upd, train_pts=pts, base_train=base_train, bad_checks=bad_checks, recorded=sorted(done),
                               recorded_est=sorted(done_est), train_s=round(train_s), no_gain=no_gain)
            if os.path.exists(cancel_flag):
                stop_reason = "cancelled"
            elif plateau and no_gain >= plateau and upd >= min_updates:
                stop_reason = "plateau"
            elif bad_checks >= 2:
                stop_reason = "regressed"
            elif spec.get("diverge", True) and pts is not None and base_train and base_train >= DIVERGE_MIN and upd >= start_update + 60 \
                    and n >= 96 and pts < DIVERGE_FRACTION * base_train:
                stop_reason = "diverged"
            if stop_reason != "budget":
                log("%s: %s at update %d (training points %.2f, start %.2f) - stopping" % (name, stop_reason, upd, pts or 0, base_train or 0))
                proc.send_signal(signal.SIGINT)                        # lets selfplay close its env workers
                try:
                    proc.wait(60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
        out.close()
        if proc.returncode not in (0, None) and stop_reason == "budget" and last_checkpoint(tag)[0] < upd_end:
            stop_reason = "error"
            log("%s: trainer exited with code %s before the end" % (name, proc.returncode))
    for p in procs:                                                    # the live match
        p.terminate()
    stop_stale_workers()
    final_update, final_ckpt = last_checkpoint(tag)
    full_evals = []
    finished = stop_reason in ("budget", "plateau")
    if finished and final_ckpt and (size != 5 or opp != "rules"):   # a curriculum stage below 5v5: no full evaluation
        ests = {e["update"]: e for e in ladder.estimates(run=name) if e.get("update")}
        if elo_pairs and final_update not in ests:
            rec = elo_estimate("out_5v5/ckpt/%s_u%d.json" % (tag, final_update), tag, final_update, elo_pairs, size)
            if rec:
                ests[final_update] = rec
        have = [u for u in ests if os.path.exists(os.path.join(CKPT, "%s_u%d.json" % (tag, u)))]
        best_u = max(have, key=lambda u: ests[u]["elo"]) if have else final_update
        keep_best(tag, best_u)
        log("%s: best checkpoint u%d (%s)" % (name, best_u, "estimated Elo %.0f at %dv%d" % (ests[best_u]["elo"], size, size) if best_u in ests else "the last one"))
    elif finished and final_ckpt:
        cands = {final_update}
        rows = tracker.load_results()
        ests = {e["update"]: e for e in ladder.estimates(run=name) if e.get("update")}
        if ests:                                                       # also the checkpoint with the highest estimated Elo
            best = max(ests.values(), key=lambda e: e["elo"])
            if os.path.exists(os.path.join(CKPT, "%s_u%d.json" % (tag, best["update"]))):
                cands.add(best["update"])
        else:                                                          # older runs without estimates: the best fast check
            fasts = [r for r in rows if r["run"] == name and r["kind"] == "fast" and r["league"].get("all")]
            if fasts:
                best = max(fasts, key=lambda r: r["league"]["all"]["pts"])
                if os.path.exists(os.path.join(CKPT, "%s_u%d.json" % (tag, best["update"]))):
                    cands.add(best["update"])
        for u in sorted(cands):
            model = "out_5v5/ckpt/%s_u%d.json" % (tag, u)
            out = "logs/sp_eval/%s_u%d.txt" % (tag, u)
            log("%s: full evaluation of update %d" % (name, u))
            if evaluate(model, out, "full", refs=[("start", start_json)] if start_json else []):
                full_evals.append(tracker.add_result(name, u, "full", os.path.join(ROOT, out)))
    if full_evals and elo_pairs:
        ests = {e["update"]: e for e in ladder.estimates(run=name)}
        if final_update not in ests:
            ests[final_update] = elo_estimate("out_5v5/ckpt/%s_u%d.json" % (tag, final_update), tag, final_update, elo_pairs, size)
        ok = [u for u in {r["update"] for r in full_evals} if ests.get(u)]
        if ok:
            best_u = max(ok, key=lambda u: ests[u]["elo"])
            keep_best(tag, best_u)
            log("%s: best checkpoint u%d (estimated Elo %.0f)" % (name, best_u, ests[best_u]["elo"]))
    eval_s = sum(r.get("seconds") or 0 for r in tracker.load_results() if r["run"] == name)
    state = {"budget": "done", "plateau": "done", "error": "failed"}.get(stop_reason, stop_reason)
    tracker.set_status(name, state=state, stop_reason=stop_reason, finished=int(time.time()), final_update=final_update, verdict=None,
                       cost_hours={"train": round(train_s / 3600, 2), "eval": round(eval_s / 3600, 2)})
    shutil.move(spec_path, os.path.join(EXP, "failed" if state == "failed" else "done", os.path.basename(spec_path)))
    if os.path.exists(cancel_flag):
        os.remove(cancel_flag)
    log("%s finished: %s" % (name, state))
    if state == "done" and opp == "rules":
        place_in_ladder(tag, size=size)


def next_spec():
    """The running experiment first (resume after a reboot), else the first spec of the queue."""
    running = sorted(glob.glob(os.path.join(EXP, "running", "*.json")))
    if running:
        return running[0]
    queue = sorted(glob.glob(os.path.join(EXP, "queue", "*.json")))
    for p in queue:                                                    # older layout: the running spec stayed in the queue
        try:
            if tracker.run_status(json.load(open(p)).get("name", "")).get("state") == "running":
                dest = os.path.join(EXP, "running", os.path.basename(p))
                shutil.move(p, dest)
                return dest
        except ValueError:
            pass
    return queue[0] if queue else None


LADDER_PAIRS = 6


def ladder_round(size=None, force=False):
    """One round of the ratings (elo/: every size, the one that needs it most unless `size`) while nothing else runs. True if it
    played (so the loop looks at the queue right away). Nothing while local/refine_off exists, unless `force` (placing a run)."""
    from elo.api import rounds_off
    if rounds_off() and not force:
        return False
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "lab", "ladder.py"), "round", "--pairs", str(LADDER_PAIRS), "--workers", "3"]
                           + (["--size", str(size)] if size else []),
                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        log("ladder round timed out")
        return False
    first = (p.stdout.strip().splitlines() or [""])[0]
    if p.returncode != 0:
        log("ladder round failed: %s" % p.stdout.strip()[-300:])
        return False
    log("ladder: %s (%.0f s)" % (first, time.time() - t0))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="keep waiting for new specs (the service); default: run the queue once and exit")
    ap.add_argument("--viewer", action="store_true", help="play the live match (headless; the dashboard's Live page shows it)")
    a = ap.parse_args()
    for d in ("queue", "running", "runs", "done", "failed", "parked"):
        os.makedirs(os.path.join(EXP, d), exist_ok=True)
    tracker.write_markdown()
    stop_stale_workers()
    while True:
        spec = next_spec()
        if spec is None:
            if not a.loop:
                return
            if not ladder_round():
                time.sleep(60)
            continue
        try:
            run_experiment(spec, a.viewer)
        except Exception as e:                                 # a broken spec must not stop the queue
            log("ERROR in %s: %r" % (spec, e))
            try:
                name = json.load(open(spec)).get("name", os.path.basename(spec))
            except (OSError, ValueError):
                name = os.path.basename(spec)[:-5]
            tracker.set_status(name, state="failed", stop_reason="error", error=repr(e))
            if os.path.exists(spec):
                shutil.move(spec, os.path.join(EXP, "failed", os.path.basename(spec)))
            stop_stale_workers()
            time.sleep(30)


if __name__ == "__main__":
    main()
