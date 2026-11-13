"""Complete evaluation of one checkpoint, cheap enough to run next to training on a Raspberry Pi.

Starts numpy net servers (tools/net_server.py) for the checkpoint and for the reference nets, then runs headless Godot:
  1. league_eval      all 16 rule-based teams, both sides (pts/m, GF/GA per team, per tier, trained-against vs held-out teams)
  2. behaviour_stats  direction changes/s, kick presses, spacing, keeper distance, passes, key passes (RL net vs rule bots)
  3. h2h_eval         head to head against RL Team 4 and against the weights the run started from (RL Team 5)
and writes everything to --out (text, one block per part, last line "DONE <seconds>"). Run at low priority.

  python3 rl/eval_checkpoint.py --model out_5v5/ckpt/jit6_u100.json --out logs/sp_eval/jit6_u100.txt [--games 1] [--duration 90]
"""
import argparse
import os
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


def godot(scene, args):
    cmd = [GODOT, "--headless", "--path", ROOT, "res://rl/%s.tscn" % scene, "--"] + args
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "GODOT_SILENCE_ROOT_WARNING": "1"})
    return out.stdout.splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="game-model JSON of the checkpoint (relative to the project or absolute)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", type=int, default=1, help="league games per team and side (1 = 32 matches)")
    ap.add_argument("--duration", type=float, default=90.0, help="seconds per match (the league metric of the shipped teams used 180)")
    ap.add_argument("--h2h_games", type=int, default=3, help="head-to-head games per side and reference")
    a = ap.parse_args()
    model = os.path.relpath(os.path.abspath(a.model), ROOT)
    res_model = "res://" + model
    t0 = time.time()
    servers = []
    lines = ["EVAL %s | league games/side %d | duration %.0fs | h2h games/side %d" % (model, a.games, a.duration, a.h2h_games)]
    try:
        proc, port = start_server(model)
        servers.append(proc)
        keep = re.compile(r"^(LEAGUE|team |SUMMARY|\S+\s+(weak|average|strong|elite)\s)")
        lines += ["# league"] + [l for l in godot("league_eval", ["--model", res_model, "--remote", str(port), "--games", str(a.games), "--duration", str(a.duration)]) if keep.match(l)]
        lines += ["# behaviour"] + [l for l in godot("behaviour_stats", ["--remote", str(port)]) if re.match(r"^(RL Team|rule-based|scores)", l)]
        lines += ["# head to head"]
        for name, ref in REFERENCES:
            rproc, rport = start_server(ref)
            servers.append(rproc)
            lines += [l for l in godot("h2h_eval", ["--a", str(port), "--b", str(rport), "--name", name, "--games", str(a.h2h_games), "--duration", str(a.duration)]) if l.startswith("H2H")]
    finally:
        for p in servers:
            p.terminate()
    lines.append("DONE %d" % (time.time() - t0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, a.out)              # the file only exists once the evaluation is complete


if __name__ == "__main__":
    main()
