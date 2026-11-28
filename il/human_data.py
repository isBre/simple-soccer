"""Reads the dataset of the user's play (data/human/*.npz, written by game/recorder.py; format in its docstring).

  python3 il/human_data.py                 one line per recorded match and the totals
  python3 il/human_data.py --check         also rebuilds every row's observation from the stored raw state and compares it
                                           with the stored one (the raw state is enough to compute any observation later)

In code: `files()`, `load(path)` -> dict of arrays + "meta", `observation(d, i)` -> the 46 numbers of row i recomputed from the
state, `snapshot(d, i)` -> a light match-like object of row i for any feature function of soccer/ai/obs.py."""
import argparse
import glob
import json
import os
import sys

import numpy as np

from game.recorder import data_dir
from soccer.ai.obs import features_team

MOVES = ["stand", "up", "up-fwd", "fwd", "down-fwd", "down", "down-back", "back", "up-back"]   # soccer.match.DIRS, own frame


def files(folder=None):
    return sorted(glob.glob(os.path.join(folder or data_dir(), "*.npz")))


def load(path):
    with np.load(path, allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["meta"] = json.loads(str(d["meta"]))
    return d


class _P:
    __slots__ = ("pos", "vel", "uid", "team")


class _Pitch:
    def __init__(self, p):
        self.out_x, self.out_y = p["out_x"], p["out_y"]


class Snapshot:
    """What the feature functions read from a Match (attack_dir, pitch, team_lists, ball, kickoff, state), rebuilt from one row."""

    def __init__(self, d, i):
        meta = d["meta"]
        self.pitch = _Pitch(meta["pitch"])
        st = d["state"][i].astype(np.float64)
        self.team_lists = [[], []]
        self.by_uid = {}
        for k, pl in enumerate(meta["players"]):
            p = _P()
            x, y, vx, vy = st[4 * k:4 * k + 4]
            p.pos, p.vel, p.uid, p.team = complex(x, y), complex(vx, vy), pl["uid"], pl["team"]
            self.team_lists[p.team].append(p)
            self.by_uid[p.uid] = p
        b = st[4 * len(meta["players"]):]
        self.ball_pos, self.ball_vel = complex(b[0], b[1]), complex(b[2], b[3])
        self.kickoff_active = bool(d["kickoff"][i])
        self.state = 0                              # rows are only taken in play
        self.controlled = self.by_uid[int(d["ctrl"][i])]

    @staticmethod
    def attack_dir(team):
        return 1.0 if team == 0 else -1.0


def snapshot(d, i):
    return Snapshot(d, i)


def observation(d, i):
    s = Snapshot(d, i)
    return features_team(s, s.controlled)


def summary(path, d):
    m = d["meta"]
    n = len(d["tick"])
    teams = m["teams"]
    res = m["result"]
    score = "%d-%d" % tuple(res["scores"]) if res else "%d-%d (left early)" % tuple(m["scores_at_save"])
    moves = np.bincount(d["move"].astype(np.int64), minlength=9) / max(1, n)
    changes = int(np.count_nonzero(np.diff(d["move"].astype(np.int64)))) / max(1e-9, n / 30.0)
    return ("%-44s %-6s %-12s vs %-12s %-18s rows %5d  stand %3.0f%%  kick %3.0f%%  changes/s %.1f" %
            (os.path.basename(path), m["control"], teams[m["human_team"]]["id"], teams[1 - m["human_team"]]["id"], score, n,
             100 * moves[0], 100 * d["kick"].mean(), changes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    fs = files(a.dir)
    total, worst = 0, 0.0
    for f in fs:
        d = load(f)
        print(summary(f, d))
        total += len(d["tick"])
        if a.check:
            for i in range(len(d["tick"])):
                err = float(np.max(np.abs(np.asarray(observation(d, i), np.float32) - d["obs"][i])))
                worst = max(worst, err)
    print("%d matches, %d decisions (%.1f min of play)" % (len(fs), total, total / 30.0 / 60.0))
    if a.check:
        ok = worst < 1e-5
        print("observation rebuilt from state: max difference %.2g -> %s" % (worst, "OK" if ok else "MISMATCH"))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
