#!/usr/bin/env python3
"""Runs on the computer that TRAINS (the Mac). Keeps the Pi's dashboard and kiosk in step with it, over ssh + rsync, every --interval s:

  1. pushes results, run states, logs and checkpoints to the Pi (exp/, logs/x_*.out, logs/sp_eval/, out_5v5/ckpt/*.pt|json; never the
     big *.train_state files, the queue, the audit log or the cancel flags);
  2. deletes from the Pi's queue every spec this computer already started or finished;
  3. pulls the Pi's queue (agents / people add, move and cancel specs there with lab/lab.py) and the Pi's cancel flags, so the runner here
     sees them. Specs already started here are never pulled again.

  python3 lab/mac_sync.py --pi isbre@10.0.0.75            # loop (Ctrl-C to stop)
  python3 lab/mac_sync.py --pi isbre@10.0.0.75 --once

Needs only the standard library, rsync and ssh (key login to the Pi). Details: lab/MAC.md."""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "exp")


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print("  failed (%d): %s\n%s" % (p.returncode, " ".join(cmd)[:160], p.stdout.strip()[-400:]), flush=True)
    return p.returncode == 0


def spec_names(folder):
    names = set()
    for f in os.listdir(folder) if os.path.isdir(folder) else []:
        if f.endswith(".json"):
            try:
                names.add(json.load(open(os.path.join(folder, f)))["name"])
            except (OSError, ValueError, KeyError):
                pass
    return names


def started_here():
    """spec names that left the queue on this computer: running, done, failed (parked ones were cancelled on the Pi)"""
    return {d: spec_names(os.path.join(EXP, d)) for d in ("running", "done", "failed")}


def sync(pi, pi_root):
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", pi]
    rs = ["rsync", "-a", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=15"]
    ok = True
    # 1. push
    ok &= run(rs + ["--exclude=/queue/", "--exclude=*.cancel", "--exclude=/audit.jsonl", "--exclude=/hidden_runs.json",
                    "--exclude=/ladder_off", "--exclude=*.tmp", EXP + "/", "%s:%s/exp/" % (pi, pi_root)])
    ok &= run(rs + ["--include=x_*.out", "--include=sp_eval/", "--include=sp_eval/***", "--include=check/", "--include=check/***",
                    "--exclude=*", os.path.join(ROOT, "logs") + "/", "%s:%s/logs/" % (pi, pi_root)])
    ckpt = os.path.join(ROOT, "out_5v5", "ckpt")
    if os.path.isdir(ckpt):
        ok &= run(rs + ["--include=*.pt", "--include=*.json", "--exclude=*", ckpt + "/", "%s:%s/out_5v5/ckpt/" % (pi, pi_root)])
    # 2. the Pi's queue forgets what started here (a spec file is named NN_name.json; the name is inside)
    gone = set().union(*started_here().values())
    if gone:
        script = ("cd %s/exp/queue 2>/dev/null && for f in *.json; do n=$(python3 -c \"import json,sys;print(json.load(open(sys.argv[1]))['name'])\" \"$f\" 2>/dev/null); "
                  "case \" %s \" in *\" $n \"*) rm -f \"$f\";; esac; done" % (pi_root, " ".join(sorted(gone))))
        run(ssh + [script])
    # 3. pull the queue (the Pi is the authority) and the cancel flags
    os.makedirs(os.path.join(EXP, "queue"), exist_ok=True)
    ok &= run(rs + ["--delete", "--include=*.json", "--exclude=*", "%s:%s/exp/queue/" % (pi, pi_root), os.path.join(EXP, "queue") + "/"])
    for f in os.listdir(os.path.join(EXP, "queue")):                  # never run a spec twice
        try:
            n = json.load(open(os.path.join(EXP, "queue", f)))["name"]
        except (OSError, ValueError, KeyError):
            continue
        if any(n in names for names in started_here().values()):
            os.remove(os.path.join(EXP, "queue", f))
    os.makedirs(os.path.join(EXP, "running"), exist_ok=True)
    ok &= run(rs + ["--remove-source-files", "--include=*.cancel", "--exclude=*", "%s:%s/exp/running/" % (pi, pi_root),
                    os.path.join(EXP, "running") + "/"])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", required=True, help="user@address of the Pi, e.g. isbre@10.0.0.75")
    ap.add_argument("--pi-root", default="/home/isbre/simple-soccer", help="the project folder on the Pi")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        t = time.time()
        ok = sync(a.pi, a.pi_root)
        print("[%s] sync %s (%.0f s)" % (time.strftime("%H:%M:%S"), "ok" if ok else "with errors", time.time() - t), flush=True)
        if a.once:
            sys.exit(0 if ok else 1)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
