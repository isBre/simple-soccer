"""Complete evaluation of one checkpoint, cheap enough to run next to training.

Runs rl/evaluate.py (the nets are loaded in its worker processes):
  1. league_eval      all 16 rule-based teams, both sides (pts/m, GF/GA per team, per tier, trained-against vs held-out teams)
  2. behaviour_stats  direction changes/s, kick presses, spacing, keeper distance, passes, key passes (RL net vs rule bots)
  3. h2h_eval         head to head against RL Team 4 and against the weights the run started from (RL Team 5)
  and, to see what the net's sampling costs, the same net playing its BEST move (greedy): the league on every 2nd team and
  the behaviour numbers, written with a "greedy " prefix. The behaviour pass also writes HEAT lines (position heatmaps per slot).
and writes everything to --out (text, one block per part, last line "DONE <seconds>") and the same numbers as JSON to
<out without .txt>.json (record(): what lab/tracker.py stores in exp/results.jsonl). Run at low priority.

  python3 rl/eval_checkpoint.py --model out_5v5/ckpt/jit6_u100.json --out logs/sp_eval/jit6_u100.txt [--games 1] [--duration 90]
"""
import argparse
import json
import os
import shutil
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REFERENCES = [("RL Team 4", "data/models/rl_5v5_arena_v4.json"), ("RL Team 5", "data/models/rl_5v5_arena_v5.json")]


def run_eval(scene, args, timeout=3 * 3600):
    """Output lines of an evaluation (rl/evaluate.py: league_eval, behaviour_stats, h2h_eval; played by the Python match core
    in parallel processes). A hung run is killed after `timeout` (otherwise it would block every later evaluation)."""
    cmd = [sys.executable, os.path.join(ROOT, "rl", "evaluate.py"), scene] + args
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return out.stdout.splitlines()
    except subprocess.TimeoutExpired:
        return ["TIMEOUT %s after %d s" % (scene, timeout)]


def results_of(lines):
    """The RESULT lines of an evaluation part (rl/evaluate.py result_line) as dicts."""
    return [json.loads(l[7:]) for l in lines if l.startswith("RESULT ")]


def record(model, mode, games, duration, h2h_games, parts, seconds):
    """The evaluation as one dict: checkpoint, protocol, league / greedy / h2h summaries, behaviour (RL team and rule bots),
    scout, every match [group, opponent, side, seed, goals for, goals against], seconds. parts: [(group, RESULT dict)] in the
    order they ran, group = "league" | "greedy" | "behaviour" | "h2h"."""
    r = {"checkpoint": model, "protocol": "%s/g%d/d%.0f" % (mode, games, duration), "h2h_games": h2h_games,
         "league": {}, "greedy": {}, "h2h": {}, "behaviour": {}, "matches": [], "seconds": int(seconds)}
    for group, d in parts:
        if d["part"] == "league":
            r[group] = d["summary"]
            r["matches"] += [[group] + m for m in d["matches"]]
        elif d["part"] == "h2h":
            r["h2h"][d["name"]] = d["summary"]
            r["matches"] += [["h2h", d["name"]] + m for m in d["matches"]]
        elif d["part"] == "behaviour" and group == "behaviour":     # the greedy behaviour pass only goes to the text file
            r["behaviour"] = d.get("rl", {})
            if "rule" in d:
                r["behaviour_rule"] = d["rule"]
            if "scout" in d:
                r["scout"] = d["scout"]
    return r


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
    ap.add_argument("--mode", choices=["full", "fast", "scout"], default="full",
                    help="fast: 24 short matches vs every 3rd rule team (sampled moves only) + head to head vs the --ref nets, to catch a collapse in minutes; full: everything")
    ap.add_argument("--ref", action="append", default=[], metavar="NAME=MODEL", help="extra head-to-head opponent (game-model JSON), e.g. the net the run started from; repeatable")
    ap.add_argument("--paused", action="store_true", help="training is paused while this runs (shown by the viewer's banner)")
    a = ap.parse_args()
    fast = a.mode == "fast"
    scout = a.mode == "scout"                   # behaviour + scouting only (8 matches of 60 s, ~2 min): style of any net
    if fast:                                    # fixed, small, comparable between checkpoints
        a.games, a.duration, a.h2h_games = 2, 60.0, 4
    refs = ([] if fast and a.ref else REFERENCES[:1] if fast else REFERENCES) + [tuple(r.split("=", 1)) for r in a.ref]
    model = os.path.relpath(os.path.abspath(a.model), ROOT)
    if not os.path.isfile(os.path.join(ROOT, model)):
        sys.exit("no such model: " + a.model)
    res_model = "res://" + model
    t0 = time.time()
    tag, upd = run_tag(model)
    flag = os.path.join(ROOT, "logs", "%s_eval_running.json" % tag) if tag else None
    if flag:                                    # the viewer shows an "evaluation running" banner while this file exists
        json.dump({"pid": os.getpid(), "checkpoint": os.path.basename(model)[:-5], "started": int(t0), "paused": a.paused}, open(flag, "w"))
    lines = ["EVAL %s | mode %s | league games/side %d | duration %.0fs | h2h games/side %d" % (model, a.mode, a.games, a.duration, a.h2h_games)]
    parts = []

    def part(group, what, args, keep, prefix=""):
        out = run_eval(what, args)
        parts.extend((group, d) for d in results_of(out))
        return [prefix + l for l in out if keep(l)]

    try:
        league_re = re.compile(r"^(LEAGUE|team |SUMMARY|MATCH |\S+\s+(weak|average|strong|elite)\s)").match
        behaviour_re = re.compile(r"^(RL Team|rule-based|scores|HEAT|SCOUT)").match
        league = ["--model", res_model, "--games", str(a.games), "--duration", str(a.duration)]
        if scout:
            refs = []
        else:
            lines += ["# league"] + part("league", "league_eval", league + (["--stride", "3"] if fast else []), league_re)
        if not fast:
            lines += ["# behaviour"] + part("behaviour", "behaviour_stats", ["--model", res_model], behaviour_re)
        if not fast and not scout:
            lines += ["# greedy (best move instead of sampling)"]
            lines += part("greedy", "league_eval", league + ["--stride", "2", "--greedy"], league_re, "greedy ")
            lines += part("greedy behaviour", "behaviour_stats", ["--model", res_model, "--greedy"],
                          re.compile(r"^(RL Team|rule-based)").match, "greedy ")
        lines += ["# head to head"]
        for name, ref in refs:
            lines += part("h2h", "h2h_eval", ["--a", res_model, "--b", os.path.join(ROOT, ref), "--name", name, "--games", str(a.h2h_games),
                                              "--duration", str(a.duration)], lambda l: l.startswith(("H2H", "MATCH ")))
    finally:
        if flag and os.path.exists(flag):
            os.remove(flag)
    if a.mode == "full":
        update_best(model, lines)
    seconds = time.time() - t0
    lines.append("DONE %d" % seconds)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rec = record(model, a.mode, a.games, a.duration, a.h2h_games, parts, seconds)
    for path, text in ((json_path(a.out), json.dumps(rec) + "\n"), (a.out, "\n".join(lines) + "\n")):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, path)           # the text file appears last, only once the evaluation (and its JSON) is complete


def json_path(out):
    """logs/sp_eval/x_u100.txt -> logs/sp_eval/x_u100.json"""
    return os.path.splitext(out)[0] + ".json"


if __name__ == "__main__":
    main()
