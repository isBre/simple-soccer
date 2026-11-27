"""Turns a checkpoint of a run into a new net player (data/players/<id>.json, model copied to data/models/<id>.json) and,
with --team, a team of five copies of it (data/teams/<team id>.json, RL Team 5's colours and crest).

  python3 rl/export_team.py --tag jit8 --id ada_moss --name "Ada Moss"                     # the run's best checkpoint
  python3 rl/export_team.py --tag jit8 --id ada_moss --name "Ada Moss" --checkpoint jit8_u300 --team rl_team_6 --team-name "RL Team 6"
"""
import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="the run whose checkpoint becomes the player")
    ap.add_argument("--id", required=True, help="player id (file name), e.g. ada_moss")
    ap.add_argument("--name", required=True, help="the player's name")
    ap.add_argument("--description", default="", help="how it was made / how it plays")
    ap.add_argument("--checkpoint", default="best", help="'best' (default) or a checkpoint name like jit8_u300")
    ap.add_argument("--team", default="", help="also write a team of five copies of the player with this id")
    ap.add_argument("--team-name", default="")
    a = ap.parse_args()
    if a.checkpoint == "best":
        best = os.path.join(ROOT, "logs", a.tag + "_best.json")
        if not os.path.exists(best):
            raise SystemExit("no best checkpoint yet (%s): an evaluation has to finish first" % best)
        info = json.load(open(best))
        src = os.path.join(ROOT, info["model"])
        ckpt = info["checkpoint"]
    else:
        src = os.path.join(ROOT, "out_5v5", "ckpt", a.checkpoint + ".json")
        ckpt = a.checkpoint
    model_rel = "data/models/%s.json" % a.id
    shutil.copy(src, os.path.join(ROOT, model_rel))
    player = {"id": a.id, "name": a.name, "kind": "net", "model": model_rel,
              "description": a.description or "Neural net from run %s (checkpoint %s)." % (a.tag, ckpt),
              "origin": {"made": time.strftime("%Y-%m-%d"), "run": a.tag, "checkpoint": ckpt}}
    with open(os.path.join(ROOT, "data", "players", a.id + ".json"), "w") as f:
        json.dump(player, f, indent=1)
        f.write("\n")
    print("wrote data/players/%s.json and %s" % (a.id, model_rel))
    if a.team:
        team = json.load(open(os.path.join(ROOT, "data", "teams", "rl_team_5.json")))
        name = a.team_name or a.name + " XI"
        team.update({"id": a.team, "name": name, "short": name[:3].upper(), "lineup": [a.id] * 5, "league": "rl", "rl_eval": False})
        with open(os.path.join(ROOT, "data", "teams", a.team + ".json"), "w") as f:
            json.dump(team, f, indent=2)
            f.write("\n")
        print("wrote data/teams/%s.json: pick %s in Quick match (5v5)" % (a.team, name))


if __name__ == "__main__":
    main()
