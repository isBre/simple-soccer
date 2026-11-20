"""Training data from the user's recorded play (data/human/, game/recorder.py) for the ML / DL leagues (docs/imitation_plan.md).

  X        the 46-number observation of the controlled player (the nets' input)
  move     the move label 0..8 (soccer.match.DIRS, the player's own frame), taken `lag` decisions LATER than the observation: the
           user reacts to what they see with a delay, so the key they press at t+lag answers the picture at t
  kick     the kick label (same lag)
  match    the index of the match each row comes from (splits are always by match: neighbouring rows are near copies)

Mirror augmentation (`mirror=True`): the pitch is symmetric top / bottom, so every row also exists upside down: every y position
and y speed in the observation changes sign, up and down moves swap. Sorting by distance does not change.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from il import human_data                     # noqa: E402
from soccer.match import AI_PERIOD            # noqa: E402

N_OBS = 46
Y_INDEX = [4 * k + j for k in range(11) for j in (1, 3)]      # y position and y speed of me, 4 mates, 5 opponents, the ball
MIRROR_MOVE = np.array([0, 5, 4, 3, 2, 1, 8, 7, 6])           # up <-> down in the own frame (DIRS)


def load(folder=None, lag=0, control=None):
    """All matches -> dict(X, move, kick, match, names). Rows without a label `lag` decisions later in the same play
    (end of match, a goal celebration in between) are dropped."""
    Xs, ms, ks, ids, names = [], [], [], [], []
    for i, f in enumerate(human_data.files(folder)):
        d = human_data.load(f)
        if control and d["meta"]["control"] != control:
            continue
        if d["obs"].shape[1] != N_OBS:                            # another team size: another observation length
            continue
        tick = d["tick"].astype(np.int64)
        n = len(tick)
        src = np.arange(n - lag)
        ok = tick[src + lag] - tick[src] == lag * AI_PERIOD       # the same stretch of play
        src = src[ok]
        Xs.append(d["obs"][src].astype(np.float32))
        ms.append(d["move"][src + lag].astype(np.int64))
        ks.append(d["kick"][src + lag].astype(np.float32))
        ids.append(np.full(len(src), len(names)))
        names.append(os.path.basename(f)[:-4])
    if not Xs:
        return {"X": np.zeros((0, N_OBS), np.float32), "move": np.zeros(0, np.int64), "kick": np.zeros(0, np.float32),
                "match": np.zeros(0, np.int64), "names": []}
    return {"X": np.concatenate(Xs), "move": np.concatenate(ms), "kick": np.concatenate(ks), "match": np.concatenate(ids), "names": names}


def mirror(X, move, kick):
    Xm = X.copy()
    Xm[:, Y_INDEX] *= -1.0
    return Xm, MIRROR_MOVE[move], kick


def subset(d, sel):
    return {k: (v[sel] if isinstance(v, np.ndarray) else v) for k, v in d.items()}
