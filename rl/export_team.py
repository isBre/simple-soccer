"""Turns a checkpoint of a run into a new playable team: copies the model to data/models/rl_5v5_arena_v<N>.json and writes
data/teams/rl_team_<N>.json (a copy of RL Team 5 with the new name and model).

  python3 rl/export_team.py --tag jit8 --number 6                      # the best checkpoint of the run (logs/jit8_best.json)
  python3 rl/export_team.py --tag jit8 --number 6 --checkpoint jit8_u300
"""
import argparse
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--number", type=int, required=True, help="team number: RL Team <number>")
    ap.add_argument("--checkpoint", default="best", help="'best' (default) or a checkpoint name like jit8_u300")
    a = ap.parse_args()
    if a.checkpoint == "best":
        best = os.path.join(ROOT, "logs", a.tag + "_best.json")
        if not os.path.exists(best):
            raise SystemExit("no best checkpoint yet (%s): an evaluation has to finish first" % best)
        info = json.load(open(best))
        src = os.path.join(ROOT, info["model"])
        print("best checkpoint of %s: %s (%.2f points/match league)" % (a.tag, info["checkpoint"], info["pts"]))
    else:
        src = os.path.join(ROOT, "out_5v5", "ckpt", a.checkpoint + ".json")
    model_rel = "data/models/rl_5v5_arena_v%d.json" % a.number
    shutil.copy(src, os.path.join(ROOT, model_rel))
    team = json.load(open(os.path.join(ROOT, "data", "teams", "rl_team_5.json")))
    team.update({"id": "rl_team_%d" % a.number, "name": "RL Team %d" % a.number, "short": "RL%d" % a.number, "ml_model": "res://" + model_rel})
    json.dump(team, open(os.path.join(ROOT, "data", "teams", "rl_team_%d.json" % a.number), "w"), indent=2)
    print("wrote %s and data/teams/rl_team_%d.json: pick RL Team %d in Quick match (5v5)" % (model_rel, a.number, a.number))


if __name__ == "__main__":
    main()
