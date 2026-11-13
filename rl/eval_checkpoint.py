"""Complete evaluation of one checkpoint, cheap enough to run next to training on a Raspberry Pi.

Starts numpy net servers (tools/net_server.py) for the checkpoint and for the reference nets, then runs headless Godot:
  1. league_eval      all 16 rule-based teams, both sides (pts/m, GF/GA per team, per tier, trained-against vs held-out teams)
  2. behaviour_stats  direction changes/s, kick presses, spacing, keeper distance, passes, key passes (RL net vs rule bots)
  3. h2h_eval         head to head against RL Team 4 and against the weights the run started from (RL Team 5)
  and, to see what the net's sampling costs, the same net playing its BEST move (greedy): the league on every 2nd team and
  the behaviour numbers, written with a "greedy " prefix. The behaviour pass also writes HEAT lines (position heatmaps per slot).
and writes everything to --out (text, one block per part, last line "DONE <seconds>"). Run at low priority.

  python3 rl/eval_checkpoint.py --model out_5v5/ckpt/jit6_u100.json --out logs/sp_eval/jit6_u100.txt [--games 1] [--duration 90]
"""
import argparse
import json
import os
import shutil
import re
import socket
import subprocess
import sys
import time

from client import GODOT, ROOT

REFERENCES = [("RL Team 4", "data/models/rl_5v5_arena_v4.json"), ("RL Team 5", "data/models/rl_5v5_arena_v5.json")]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(model):
    port = free_port()
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "net_server.py"), "--port", str(port), "--model", os.path.join(ROOT, model)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc, port
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("net server did not start for " + model)


def godot(scene, args, timeout=3 * 3600):
    """Output lines of a headless eval scene. A hung scene is killed after `timeout` (otherwise it would block every later evaluation)."""
    cmd = [GODOT, "--headless", "--path", ROOT, "res://rl/%s.tscn" % scene, "--"] + args
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, env={**os.environ, "GODOT_SILENCE_ROOT_WARNING": "1"})
        return out.stdout.splitlines()
    except subprocess.TimeoutExpired:
        return ["TIMEOUT %s after %d s" % (scene, timeout)]


def run_tag(model):
    """'jit8_u200.json' -> ('jit8', 200)"""
    m = re.match(r"(.+)_u(\d+)\.json$", os.path.basename(model))
    return (m.group(1), int(m.group(2))) if m else (None, 0)


def update_best(model, out_lines):
    """Keeps the best checkpoint of the run (league points over all 16 teams): out_5v5/ckpt/<tag>_best.json/.pt and logs/<tag>_best.json.
    A new checkpoint replaces the best one only if its league points are higher (the file records the standard error)."""
    tag, upd = run_tag(model)
    if tag is None:
        return
    m = next((re.search(r"pts/m (\S+)(?:.*? se (\S+))?", l) for l in out_lines if l.startswith("SUMMARY all")), None)
    if m is None:
        return
    pts, se = float(m.group(1)), (float(m.group(2)) if m.group(2) else None)
    best_path = os.path.join(ROOT, "logs", tag + "_best.json")
    best = json.load(open(best_path)) if os.path.exists(best_path) else None
    if best is not None and best["pts"] >= pts:
        return
    ckpt_dir = os.path.dirname(os.path.join(ROOT, model))
    shutil.copy(os.path.join(ROOT, model), os.path.join(ckpt_dir, tag + "_best.json"))
    pt = os.path.join(ROOT, model[:-5] + ".pt")
    if os.path.exists(pt):
        shutil.copy(pt, os.path.join(ckpt_dir, tag + "_best.pt"))
    json.dump({"checkpoint": "%s_u%d" % (tag, upd), "update": upd, "pts": pts, "se": se, "model": model}, open(best_path, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="game-model JSON of the checkpoint (relative to the project or absolute)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", type=int, default=1, help="league games per team and side (1 = 32 matches)")
    ap.add_argument("--duration", type=float, default=90.0, help="seconds per match (the league metric of the shipped teams used 180)")
    ap.add_argument("--h2h_games", type=int, default=8, help="head-to-head games per side and reference")
    ap.add_argument("--paused", action="store_true", help="training is paused while this runs (shown by the viewer's banner)")
    a = ap.parse_args()
    model = os.path.relpath(os.path.abspath(a.model), ROOT)
    res_model = "res://" + model
    t0 = time.time()
    servers = []
    tag, upd = run_tag(model)
    flag = os.path.join(ROOT, "logs", "%s_eval_running.json" % tag) if tag else None
    if flag:                                    # the viewer shows an "evaluation running" banner while this file exists
        json.dump({"pid": os.getpid(), "checkpoint": os.path.basename(model)[:-5], "started": int(t0), "paused": a.paused}, open(flag, "w"))
    lines = ["EVAL %s | league games/side %d | duration %.0fs | h2h games/side %d" % (model, a.games, a.duration, a.h2h_games)]
    try:
        proc, port = start_server(model)
        servers.append(proc)
        keep = re.compile(r"^(LEAGUE|team |SUMMARY|\S+\s+(weak|average|strong|elite)\s)")
        lines += ["# league"] + [l for l in godot("league_eval", ["--model", res_model, "--remote", str(port), "--games", str(a.games), "--duration", str(a.duration)]) if keep.match(l)]
        lines += ["# behaviour"] + [l for l in godot("behaviour_stats", ["--remote", str(port)]) if re.match(r"^(RL Team|rule-based|scores|HEAT)", l)]
        lines += ["# greedy (best move instead of sampling)"]
        lines += ["greedy " + l for l in godot("league_eval", ["--model", res_model, "--remote", str(port), "--games", str(a.games), "--duration", str(a.duration), "--stride", "2", "--greedy"]) if keep.match(l)]
        lines += ["greedy " + l for l in godot("behaviour_stats", ["--remote", str(port), "--greedy"]) if re.match(r"^(RL Team|rule-based)", l)]
        lines += ["# head to head"]
        for name, ref in REFERENCES:
            rproc, rport = start_server(ref)
            servers.append(rproc)
            lines += [l for l in godot("h2h_eval", ["--a", str(port), "--b", str(rport), "--name", name, "--games", str(a.h2h_games), "--duration", str(a.duration)]) if l.startswith("H2H")]
    finally:
        for p in servers:
            p.terminate()
        if flag and os.path.exists(flag):
            os.remove(flag)
    update_best(model, lines)
    lines.append("DONE %d" % (time.time() - t0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, a.out)              # the file only exists once the evaluation is complete


if __name__ == "__main__":
    main()
