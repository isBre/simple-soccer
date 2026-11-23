"""Thermal guard for a fanless laptop: pauses the experiment runner and everything it started (training, env workers, evaluations,
live match) with SIGSTOP when the temperature passes --max, and resumes them with SIGCONT once it is back under --resume.

The recipe does not change (same workers, same batches): a hot room only makes the run slower. Reads the newest line of
logs/health.log (lab/health_log.py: on macOS the battery temperature, the only sensor readable without admin rights).
Writes logs/thermal_guard.json ({"paused", "since", "temp", "max", "resume", "paused_s"}) for lab.py status / the dashboard,
and appends every pause / resume to exp/runner.log. Without a fresh health sample (older than 60 s) it pauses too: no reading, no heat.
Stops on its own when the runner is gone (and always leaves the processes running).

  python3 lab/thermal_guard.py --max 33 --resume 32
"""
import argparse
import json
import os
import re
import signal
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEALTH = os.path.join(ROOT, "logs", "health.log")
STATE = os.path.join(ROOT, "logs", "thermal_guard.json")
RUNNER_LOG = os.path.join(ROOT, "exp", "runner.log")


MATCH = "lab/exp_runner.py"


def runner_pids():
    out = subprocess.run(["pgrep", "-f", MATCH], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def tree(roots):
    """The roots and all their descendants (from one ps snapshot)."""
    kids = {}
    for line in subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout.splitlines():
        pid, ppid = map(int, line.split())
        kids.setdefault(ppid, []).append(pid)
    out, todo = [], list(roots)
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def signal_all(pids, sig):
    for p in pids:
        try:
            os.kill(p, sig)
        except (ProcessLookupError, PermissionError):
            pass


def reading():
    """(temperature °C, age of the sample in s) of the newest health line, or (None, None)."""
    try:
        with open(HEALTH, "rb") as f:
            f.seek(max(0, os.path.getsize(HEALTH) - 4096))
            line = f.read().decode(errors="replace").strip().splitlines()[-1]
    except (OSError, IndexError):
        return None, None
    m = re.search(r"temp=([\d.]+)", line)
    t = time.mktime(time.strptime(line.split(" ", 1)[0], "%Y-%m-%dT%H:%M:%S"))
    return (float(m.group(1)) if m else None), time.time() - t


def log(msg):
    print(msg, flush=True)
    with open(RUNNER_LOG, "a") as f:
        f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def main():
    global MATCH, STATE, RUNNER_LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=float, default=33.0, help="pause above this temperature (°C)")
    ap.add_argument("--resume", type=float, default=32.0, help="resume at or below this temperature (°C)")
    ap.add_argument("--every", type=float, default=10.0, help="seconds between checks")
    ap.add_argument("--match", default=MATCH, help="command line of the root process to guard (tests: a dummy)")
    ap.add_argument("--state", default=STATE, help="state file (tests: a scratch path)")
    ap.add_argument("--log", default=RUNNER_LOG, help="log file of pauses / resumes (tests: a scratch path)")
    a = ap.parse_args()
    MATCH, STATE, RUNNER_LOG = a.match, a.state, a.log
    paused, since, paused_s = False, None, 0.0

    def write(temp):
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"paused": paused, "since": since, "temp": temp, "max": a.max, "resume": a.resume, "paused_s": round(paused_s),
                       "updated": time.time()}, f)
        os.replace(tmp, STATE)

    def resume(why):
        nonlocal paused, since, paused_s
        signal_all(tree(runner_pids()), signal.SIGCONT)
        if paused:
            paused_s += time.time() - since
            log("thermal guard: resumed (%s, paused %.0f min)" % (why, (time.time() - since) / 60))
        paused, since = False, None

    signal.signal(signal.SIGTERM, lambda *_: (resume("guard stopped"), write(None), os._exit(0)))
    while True:
        roots = runner_pids()
        if not roots:
            resume("runner gone")
            write(None)
            return
        temp, age = reading()
        hot = temp is None or age is None or age > 60 or temp > a.max
        if not paused and hot:
            signal_all(tree(roots), signal.SIGSTOP)
            paused, since = True, time.time()
            log("thermal guard: paused at %s (max %.1f °C, resumes at %.1f)" % ("%.1f °C" % temp if temp is not None and age is not None and age <= 60 else "no fresh reading", a.max, a.resume))
        elif paused and temp is not None and age is not None and age <= 60 and temp <= a.resume:
            resume("%.1f °C" % temp)
        elif paused:
            signal_all(tree(roots), signal.SIGSTOP)              # processes started meanwhile (none should be, but be safe)
        write(temp)
        time.sleep(a.every)


if __name__ == "__main__":
    main()
