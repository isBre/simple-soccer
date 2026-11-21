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
Everything is written to exp/ (see lab/tracker.py). After a reboot the runner resumes the running experiment from its last checkpoint.

  ~/rl-venv/bin/python lab/exp_runner.py --loop [--viewer]        (installed as the systemd service soccer-exp.service)

While the queue is empty (--loop) it plays rounds of the Elo ranking (lab/ladder.py round: 6 pairs, 2 matches each, 3 niced
workers, a few minutes on the Pi) and looks at the queue again after each round. `touch exp/ladder_off` stops that.
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

ROOT, EXP = tracker.ROOT, tracker.EXP
CKPT = os.path.join(ROOT, "out_5v5", "ckpt")
MINIMAL, DEFAULTS = tracker.MINIMAL, tracker.DEFAULTS
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
    """Leftovers of a killed trainer or evaluation (they would hold the ports and the CPU). Training workers end on their own
    when their trainer is gone (their pipe closes)."""
    for pat in ("rl/eval_checkpoint.py", "rl/evaluate.py", "rl/net_server.py --port", "lab/live.py --tag"):
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
    rewards, args = tracker.effective(spec)
    cmd = [sys.executable, os.path.join(ROOT, "rl", "selfplay.py"), "--obs", spec.get("obs", "team"), "--start", start, "--start_update", str(start_update),
           "--tag", tag, "--eval_every", "0", "--log_every", "2", "--fast_ref", json_of(spec["start"]),
           "--baseline", os.path.join(ROOT, spec["start"])]          # the frozen benchmark is always the net the experiment started from (also after a resume)
    for k, v in {**args, **rewards}.items():
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


KIOSK_PROFILE = os.path.expanduser("~/.config/soccer-kiosk")          # own Chromium profile: no keyring prompt, no restore bubble
KIOSK_URL = "http://127.0.0.1:8080/?kiosk=1#/live"


def start_viewer(tag, model):
    """--viewer: the live demo match (lab/live.py: the newest checkpoint on the match core, streamed to the dashboard) and the
    dashboard full screen on the Pi's touch screen (Chromium kiosk)."""
    procs = [viewer_window(tag, model)]
    ensure_kiosk()
    return procs


def viewer_window(tag, model):
    """The match shown live: lab/live.py (restarted by the runner if it stops)."""
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "lab", "live.py"), "--tag", tag, "--start", model],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_kiosk():
    """The web dashboard full screen on the Pi's screen (1024x600 touch screen, layout ?kiosk=1). It is not tied to an experiment:
    it stays open between experiments and is started again if it was closed."""
    if subprocess.run(["pgrep", "-f", "user-data-dir=" + KIOSK_PROFILE], stdout=subprocess.DEVNULL).returncode == 0:
        return
    # native Wayland (the Pi's desktop is labwc): under X11 compatibility the touch screen arrives as a mouse and a finger drag selects
    # instead of scrolling
    env = {**os.environ, "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/%d" % os.getuid(), "DISPLAY": ":0",
           "XAUTHORITY": os.path.expanduser("~/.Xauthority")}
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    subprocess.Popen(["chromium", "--ozone-platform=wayland", "--kiosk", "--app=" + KIOSK_URL, "--user-data-dir=" + KIOSK_PROFILE, "--password-store=basic",
                      "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble", "--disable-translate",
                      "--disable-features=Translate,TranslateUI", "--overscroll-history-navigation=0", "--disable-pinch", "--touch-events=enabled",
                      "--check-for-update-interval=31536000"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def viewer_target():
    """(tag, start model) the live demo should show: the running experiment, else the most recently updated one (status files
    written here or copied from another computer that trains, see lab/MAC.md). (None, None) when there is none."""
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


def view_only():
    """--viewer-only: no training and no ladder here (the experiments run on another computer, lab/mac_sync.py copies their files
    in); only the live demo match and the kiosk, following whichever experiment is current."""
    stop_stale_workers()
    live, cur = None, None
    while True:
        tag, model = viewer_target()
        if tag and (tag != cur or live is None or live.poll() is not None):
            if live is not None and live.poll() is None:
                live.terminate()
            live, cur = viewer_window(tag, model), tag
            log("viewer: live demo follows %s" % tag)
        ensure_kiosk()
        time.sleep(30)


def reference_for(spec, base_name, rows):
    """(name, record) a finished run is judged against: the control run's full evaluation at the closest update (same protocol)
    when the spec names a "control", otherwise the start net's full evaluation."""
    ctrl = spec.get("control")
    if ctrl:
        cands = [r for r in rows if r["run"] == ctrl and r["kind"] == "full"]
        if cands:
            target = int(spec.get("updates", DEFAULTS["updates"]))
            return ctrl, min(cands, key=lambda r: abs(r["update"] - target))
    return base_name, tracker.latest(base_name, "full", rows=rows)


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
    rewards, args = tracker.effective(spec)
    start_json = json_of(spec["start"])
    base_name = baseline(start_json)
    base_fast = tracker.latest(base_name, "fast")
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
        start, start_update = spec["start"], 0
    commit, dirty = tracker.git_commit()
    tracker.set_status(name, state="running", spec=spec, baseline_run=base_name, started=st.get("started", int(time.time())), tag=tag,
                       target_updates=upd_end, effective_rewards=rewards, effective_args=args, seed=args.get("seed"), git_commit=commit,
                       git_dirty=dirty, boot_id=boot, restarts=restarts, control=spec.get("control"), net=tracker.net_info(spec["start"]))
    done = set(st.get("recorded", []))
    base_train = st.get("base_train")
    bad_checks = st.get("bad_checks", 0)
    train_s = st.get("train_s", 0.0)
    stop_reason = "budget"
    procs = []
    cancel_flag = os.path.join(EXP, "running", name + ".cancel")
    if start_update < upd_end:
        if viewer:
            procs += start_viewer(tag, start_json)
        out = open(os.path.join(ROOT, "logs", tag + ".out"), "a")
        proc = subprocess.Popen(selfplay_cmd(spec, tag, os.path.join(ROOT, start), start_update), cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
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
            if viewer:
                ensure_kiosk()
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
                    bad_checks = bad_checks + 1 if c["z"] < -REGRESS_SE else 0
                    log("%s u%d fast: pts %.2f, vs start %+.2f ± %.2f (%s, z %.1f)" % (name, u, rec["league"]["all"]["pts"], c["pts"], c["pts_se"],
                                                                                     "paired" if c["paired"] else "unpaired", c["z"]))
            tracker.set_status(name, update=upd, train_pts=pts, base_train=base_train, bad_checks=bad_checks, recorded=sorted(done), train_s=round(train_s))
            if os.path.exists(cancel_flag):
                stop_reason = "cancelled"
            elif bad_checks >= 2:
                stop_reason = "regressed"
            elif pts is not None and base_train and upd >= start_update + 60 and n >= 96 and pts < DIVERGE_FRACTION * base_train:
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
    for p in procs:                                                    # the live match (the kiosk stays open)
        p.terminate()
    stop_stale_workers()
    final_update, final_ckpt = last_checkpoint(tag)
    full_evals = []
    if stop_reason == "budget" and final_ckpt:
        cands = {final_update}
        rows = tracker.load_results()
        fasts = [r for r in rows if r["run"] == name and r["kind"] == "fast" and r["league"].get("all")]
        if fasts:                                                      # also the best fast check, if it is another checkpoint
            best = max(fasts, key=lambda r: r["league"]["all"]["pts"])
            if os.path.exists(os.path.join(CKPT, "%s_u%d.json" % (tag, best["update"]))):
                cands.add(best["update"])
        for u in sorted(cands):
            model = "out_5v5/ckpt/%s_u%d.json" % (tag, u)
            out = "logs/sp_eval/%s_u%d.txt" % (tag, u)
            log("%s: full evaluation of update %d" % (name, u))
            if evaluate(model, out, "full", refs=[("start", start_json)]):
                full_evals.append(tracker.add_result(name, u, "full", os.path.join(ROOT, out)))
    verdict = None
    final = next((r for r in full_evals if r["update"] == final_update), None)
    if final:
        ref_name, ref = reference_for(spec, base_name, tracker.load_results())
        verdict = {**tracker.compare(final, ref), "reference": ref_name, "update": final_update}
    eval_s = sum(r.get("seconds") or 0 for r in tracker.load_results() if r["run"] == name)
    state = {"budget": "done", "error": "failed"}.get(stop_reason, stop_reason)
    tracker.set_status(name, state=state, stop_reason=stop_reason, finished=int(time.time()), final_update=final_update, verdict=verdict,
                       cost_hours={"train": round(train_s / 3600, 2), "eval": round(eval_s / 3600, 2)})
    shutil.move(spec_path, os.path.join(EXP, "failed" if state == "failed" else "done", os.path.basename(spec_path)))
    if os.path.exists(cancel_flag):
        os.remove(cancel_flag)
    log("%s finished: %s %s" % (name, state, json.dumps(verdict) if verdict else ""))


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


def ladder_round():
    """One round of the Elo ranking while nothing else runs. True if it played (so the loop looks at the queue right away)."""
    if os.path.exists(os.path.join(EXP, "ladder_off")):
        return False
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "lab", "ladder.py"), "round", "--pairs", str(LADDER_PAIRS), "--workers", "3"],
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
    ap.add_argument("--viewer", action="store_true", help="play the live match (headless) and show the dashboard on the Pi's screen")
    ap.add_argument("--viewer-only", action="store_true", help="no training: only the live demo and the kiosk (experiments run on another computer)")
    a = ap.parse_args()
    if a.viewer_only:
        view_only()
        return
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
