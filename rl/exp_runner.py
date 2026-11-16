"""Experiment runner: takes experiment specs from exp/queue/, trains each one with rl/selfplay.py, evaluates it, decides, repeats.

An experiment is one small JSON file (exp/queue/<NN>_<name>.json), run in file-name order:
  {"name": "win_bonus", "start": "out_5v5/team46_start.pt", "updates": 300, "lr": 5e-5,
   "rewards": {"w_win": 3.0, "w_draw": 1.0}, "notes": "does the win/draw bonus help on top of the minimal set?"}
`rewards` overrides MINIMAL below (goals, passing, cooperation, spacing while attacking, kick discipline); any selfplay option can be given
in "args" (e.g. {"workers_rule": 2}). Per experiment the runner:
  1. evaluates the start net once (fast + full, cached per start file) = the baseline,
  2. trains; every `fast_every` updates selfplay pauses for a FAST check (16 short matches, same seeds, vs the start net),
  3. stops early: `diverged` (training points vs the rule bots fall under 70% of their start value) or `regressed`
     (two fast checks in a row worse than the baseline by more than 2 standard errors),
  4. otherwise runs a FULL evaluation of the last checkpoint and compares it with the baseline (tracker.compare: verdict
     better / worse / no difference, using the standard errors).
Everything is written to exp/ (see rl/tracker.py). After a reboot the runner resumes the running experiment from its last checkpoint.

  ~/rl-venv/bin/python rl/exp_runner.py --loop [--viewer]        (installed as the systemd service soccer-exp.service)
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

import tracker
from client import GODOT, ROOT

EXP = tracker.EXP
CKPT = os.path.join(ROOT, "out_5v5", "ckpt")
MINIMAL = {"pass_individual": 1, "w_recv": 0.1, "w_open": 0.003, "w_key_pass": 0.25, "w_xa": 2.5, "coop_cap": 8, "random_start": 0.6,
           "shaping": 0, "w_keeper": 0, "w_jitter": 0, "w_far": 0, "w_xg": 0, "w_xga": 0, "w_win": 0, "w_draw": 0, "w_tackle": 0,
           "w_goalside": 0, "w_opp_half": 0, "w_compact": 0}
DEFAULTS = {"lr": 5e-5, "updates": 300, "workers_rule": 2, "workers_self": 1, "envs_per_worker": 16, "rollout": 128, "minibatch": 4096,
            "ckpt_every": 25, "fast_every": 50, "learn_threads": 2}
DIVERGE_FRACTION = 0.7          # training points vs the rule bots below this share of their starting value: stop
REGRESS_SE = 2.0                # fast check worse than the baseline by more than this many standard errors, twice in a row: stop


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
    """Godot workers of a killed trainer (they would hold the ports and the CPU)."""
    for pat in ("res://rl/rl_server.tscn", "rl/eval_checkpoint.py", "tools/net_server.py --port"):
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


def selfplay_cmd(spec, tag, start, start_update):
    rewards = {**MINIMAL, **spec.get("rewards", {})}
    opts = {**DEFAULTS, **{k: spec[k] for k in ("lr", "updates") if k in spec}, **spec.get("args", {}), **rewards}
    cmd = [sys.executable, os.path.join(ROOT, "rl", "selfplay.py"), "--obs", spec.get("obs", "team"), "--start", start, "--start_update", str(start_update),
           "--tag", tag, "--eval_every", "0", "--log_every", "2", "--fast_ref", json_of(spec["start"])]
    for k, v in opts.items():
        cmd += ["--" + k, str(v)]
    return cmd


def last_checkpoint(tag):
    found = [(int(re.search(r"_u(\d+)\.pt$", p).group(1)), p) for p in glob.glob(os.path.join(CKPT, tag + "_u*.pt"))]
    return max(found) if found else (0, None)


def progress(tag):
    """(update, training points per match vs the rule bots, number of matches) from the last training log line."""
    path = os.path.join(ROOT, "logs", tag + ".out")
    if not os.path.exists(path):
        return 0, None, 0
    for line in reversed(open(path, errors="replace").read().splitlines()[-400:]):
        m = re.search(r"sp upd (\d+) \| pts/m vs rules (?:(\S+)\((\d+)\)|-)", line)
        if m:
            return int(m.group(1)), (float(m.group(2)) if m.group(2) else None), int(m.group(3) or 0)
    return 0, None, 0


def start_viewer(tag, model):
    """Optional: nets on ports 7301-7303 and the live viewer on the Pi's screen (about 900 MB and a core: off by default)."""
    procs = []
    sv = os.path.join(ROOT, "tools", "net_server.py")
    for port, extra in ((7302, ["--model", "data/models/rl_5v5_arena_v4.json"]), (7301, ["--tag", tag, "--model", model]),
                        (7303, ["--best-file", "logs/%s_best.json" % tag, "--model", model])):
        procs.append(subprocess.Popen([sys.executable, sv, "--port", str(port)] + extra, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    env = {**os.environ, "DISPLAY": ":0", "GODOT_SILENCE_ROOT_WARNING": "1"}
    procs.append(subprocess.Popen([GODOT, "--path", ROOT, "res://tools/watch_training.tscn", "--", "--tag", tag, "--start", "res://" + model],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def run_experiment(spec_path, viewer=False):
    spec = json.load(open(spec_path))
    name = spec["name"]
    tag = "x_" + name
    st = tracker.run_status(name)
    start_json = json_of(spec["start"])
    base_name = baseline(start_json)
    base_fast = tracker.latest(base_name, "fast")
    upd_end = int(spec.get("updates", DEFAULTS["updates"]))
    start_update, ckpt = last_checkpoint(tag)
    if ckpt:
        log("resuming %s from update %d" % (name, start_update))
        start = os.path.relpath(ckpt, ROOT)
    else:
        start, start_update = spec["start"], 0
    tracker.set_status(name, state="running", spec=spec, baseline_run=base_name, started=st.get("started", int(time.time())), tag=tag, target_updates=upd_end)
    done = set(st.get("recorded", []))
    base_train = st.get("base_train")
    bad_checks = 0
    verdict_state = "done"
    procs = []
    if start_update < upd_end:
        if viewer:
            procs += start_viewer(tag, start_json)
        out = open(os.path.join(ROOT, "logs", tag + ".out"), "a")
        proc = subprocess.Popen(selfplay_cmd(spec, tag, os.path.join(ROOT, start), start_update), cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
        log("started %s (pid %d)" % (name, proc.pid))
        while proc.poll() is None:
            time.sleep(30)
            upd, pts, n = progress(tag)
            if pts is not None and n >= 96 and base_train is None:
                base_train = pts
            tracker.set_status(name, update=upd, train_pts=pts, base_train=base_train)
            for path in sorted(glob.glob(os.path.join(ROOT, "logs", "sp_eval", tag + "_u*_fast.txt"))):
                u = int(re.search(r"_u(\d+)_fast", path).group(1))
                if u in done:
                    continue
                done.add(u)
                rec = tracker.add_result(name, u, "fast", path)
                tracker.set_status(name, recorded=sorted(done))
                a, b = rec["league"].get("all"), (base_fast or {}).get("league", {}).get("all")
                if a and b:
                    z = (a["pts"] - b["pts"]) / max((a["se"] ** 2 + b["se"] ** 2) ** 0.5, 1e-9)
                    bad_checks = bad_checks + 1 if z < -REGRESS_SE else 0
                    log("%s u%d fast: pts %.2f (baseline %.2f), z %.1f" % (name, u, a["pts"], b["pts"], z))
            if bad_checks >= 2:
                verdict_state = "regressed"
            elif pts is not None and base_train and upd >= start_update + 60 and n >= 96 and pts < DIVERGE_FRACTION * base_train:
                verdict_state = "diverged"
            if verdict_state != "done":
                log("%s: %s at update %d (training points %.2f, start %.2f) - stopping" % (name, verdict_state, upd, pts or 0, base_train or 0))
                proc.send_signal(signal.SIGINT)                        # lets selfplay close its Godot workers
                try:
                    proc.wait(60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
        out.close()
    for p in procs:
        p.terminate()
    stop_stale_workers()
    final_update, final_ckpt = last_checkpoint(tag)
    final = None
    if verdict_state == "done" and final_ckpt:
        model = os.path.relpath(final_ckpt[:-3] + ".json", ROOT)
        out = "logs/sp_eval/%s_u%d.txt" % (tag, final_update)
        log("%s: full evaluation of update %d" % (name, final_update))
        if evaluate(model, out, "full", refs=[("start", start_json)]):
            final = tracker.add_result(name, final_update, "full", os.path.join(ROOT, out))
    verdict = None
    base_full = tracker.latest(base_name, "full")
    if final and base_full:
        verdict = tracker.compare(final, base_full)
    tracker.set_status(name, state=verdict_state, finished=int(time.time()), final_update=final_update, verdict=verdict)
    os.makedirs(os.path.join(EXP, "done"), exist_ok=True)
    shutil.move(spec_path, os.path.join(EXP, "done", os.path.basename(spec_path)))
    log("%s finished: %s %s" % (name, verdict_state, json.dumps(verdict) if verdict else ""))


def next_spec():
    """The running experiment first (resume after a reboot), else the first spec of the queue."""
    queue = sorted(glob.glob(os.path.join(EXP, "queue", "*.json")))
    for p in queue:
        if tracker.run_status(json.load(open(p))["name"]).get("state") == "running":
            return p
    return queue[0] if queue else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="keep waiting for new specs (the service); default: run the queue once and exit")
    ap.add_argument("--viewer", action="store_true", help="show the live viewer on the Pi's screen while an experiment runs")
    a = ap.parse_args()
    for d in ("queue", "runs", "done", "failed"):
        os.makedirs(os.path.join(EXP, d), exist_ok=True)
    tracker.write_markdown()
    stop_stale_workers()
    while True:
        spec = next_spec()
        if spec is None:
            if not a.loop:
                return
            time.sleep(60)
            continue
        try:
            run_experiment(spec, a.viewer)
        except Exception as e:                                 # a broken spec must not stop the queue
            log("ERROR in %s: %r" % (spec, e))
            tracker.set_status(json.load(open(spec))["name"], state="failed", error=repr(e))
            shutil.move(spec, os.path.join(EXP, "failed", os.path.basename(spec)))
            stop_stale_workers()


if __name__ == "__main__":
    main()
