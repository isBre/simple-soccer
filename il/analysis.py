"""What the Lab's Dataset page shows about the user's recorded play (data/human/, game/recorder.py): served by lab/dashboard.py
as /api/dataset (everything below, cached until a file changes) and /api/dataset/match/<id> (one match for the replay).

All positions are normalised to [-1, 1] in the user's attacking frame (the user's team always attacks to the right), as the
scouting page does. The behaviour numbers use the definitions of rl/evaluate.py behaviour_stats (per decision, 30 per second), so
they compare directly with the nets' and the rule bots' numbers of the full evaluations:
  direction changes/s  the move differs from the previous decision's (start / stop included)
  180-turns/s          two moving decisions in a row pointing more than 120 degrees apart
  kick presses/s       kick pressed after a decision without it
  idle %               no direction held
Only consecutive decisions count for changes (a goal celebration or a pause in between breaks the chain).

  python3 il/analysis.py           prints the summary as JSON"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from il import human_data                                   # noqa: E402
from soccer.match import AI_PERIOD, DIRS                    # noqa: E402

GX, GY = 14, 8                       # heatmap grid, as rl/evaluate.py
PER_SEC = 60.0 / AI_PERIOD           # decisions per second
ON_BALL = 40.0                       # px: close enough to play the ball
DIST_EDGES = [ON_BALL, 150.0, 300.0]
DIST_LABELS = ["on the ball (< 40 px)", "close (40-150 px)", "mid (150-300 px)", "far (> 300 px)"]
RANKS = ["deepest", "2nd deepest", "middle", "2nd most advanced", "most advanced"]   # among the user's 5, keeper included
UNIT = np.array([[0.0, 0.0]] + [[d.real / abs(d), d.imag / abs(d)] for d in DIRS[1:]])
_cache = {"key": None, "data": None}


def _frame(d):
    """Per-row arrays of one match in the user's attacking frame."""
    meta = d["meta"]
    n = len(meta["players"])
    N = len(d["tick"])
    h = meta["human_team"]
    s = 1.0 if h == 0 else -1.0
    hw, hh = meta["pitch"]["half_w"], meta["pitch"]["half_h"]
    st = d["state"].astype(np.float64)
    P = st[:, :4 * n].reshape(N, n, 4)
    ball = st[:, 4 * n:4 * n + 4]
    uid_k = {p["uid"]: k for k, p in enumerate(meta["players"])}
    k = np.array([uid_k[int(u)] for u in d["ctrl"]])
    rows = np.arange(N)
    me = P[rows, k]
    team = np.array([p["team"] for p in meta["players"]])
    mine = team == h
    dist = np.hypot(me[:, 0] - ball[:, 0], me[:, 1] - ball[:, 1])
    depth = P[:, :, 0] * s                                       # how far up the pitch, for every player
    rank = (depth[:, mine] < (me[:, 0] * s)[:, None]).sum(1)      # 0 = the deepest of the user's team
    d_all = np.hypot(P[:, :, 0] - ball[:, None, 0], P[:, :, 1] - ball[:, None, 1])
    ours = team[np.argmin(d_all, 1)] == h                         # the user's team is nearest the ball ("in possession")
    to_ball = np.stack([(ball[:, 0] - me[:, 0]) * s, ball[:, 1] - me[:, 1]], 1)
    to_ball /= np.maximum(np.hypot(to_ball[:, 0], to_ball[:, 1]), 1e-9)[:, None]
    move = d["move"].astype(np.int64)
    kick = d["kick"].astype(bool)
    chain = np.diff(d["tick"]) == AI_PERIOD                       # consecutive decisions
    return {
        "N": N, "x": me[:, 0] * s / hw, "y": me[:, 1] / hh, "bx": ball[:, 0] * s / hw, "by": ball[:, 1] / hh, "dist": dist,
        "rank": rank, "ours": ours, "move": move, "kick": kick, "chain": chain,
        "toward": (UNIT[move] * to_ball).sum(1) > 0.7, "moving": move > 0,
    }


def _behaviour(F):
    m, kick, chain = F["move"], F["kick"], F["chain"]
    pairs = max(1, int(chain.sum()))
    changed = (m[1:] != m[:-1]) & chain
    u0, u1 = UNIT[m[:-1]], UNIT[m[1:]]
    turn = (m[:-1] > 0) & (m[1:] > 0) & ((u0 * u1).sum(1) < -0.5) & chain
    rise = kick[1:] & ~kick[:-1] & chain
    return {"dir_changes_s": float(changed.sum()) / pairs * PER_SEC, "turn180_s": float(turn.sum()) / pairs * PER_SEC,
            "kick_presses_s": float(rise.sum()) / pairs * PER_SEC, "kick_held_pct": 100.0 * float(kick.mean()),
            "idle_pct": 100.0 * float((m == 0).mean()), "toward_ball_pct": 100.0 * float(F["toward"][F["moving"]].mean()) if F["moving"].any() else None}


def _heat(x, y):
    gx = np.clip(((x + 1) / 2 * GX).astype(int), 0, GX - 1)
    gy = np.clip(((y + 1) / 2 * GY).astype(int), 0, GY - 1)
    c = np.bincount(gy * GX + gx, minlength=GX * GY)
    return {"w": GX, "h": GY, "v": [int(round(1000.0 * v / max(1, c.sum()))) for v in c], "role": "-", "n": int(c.sum())}


def _cat(fs, key):
    return np.concatenate([F[key] for F in fs]) if fs else np.zeros(0)


def match_row(path, d, F):
    m = d["meta"]
    h = m["human_team"]
    res = m["result"]
    sc = res["scores"] if res else m["scores_at_save"]
    gf, ga = sc[h], sc[1 - h]
    setup = m["setup"]
    puzzle = setup.get("puzzle") is not None
    if res and puzzle:                                          # a puzzle round ends at the first goal (or after 60 s without one)
        outcome = "W" if gf > ga else ("L" if gf < ga else "D")
    elif res:
        w = res["winner"]
        outcome = "D" if w == -1 else ("W" if w == h else "L")
    else:
        outcome = "left"
    roles = {}
    for p in m["players"]:
        if p["rows"]:
            roles[p["role"]] = roles.get(p["role"], 0) + p["rows"]
    b = _behaviour(F)
    return {"id": os.path.basename(path)[:-4], "started": m["started"], "control": m["control"], "complete": m["complete"],
            "team": m["teams"][h], "opponent": m["teams"][1 - h], "gf": gf, "ga": ga, "outcome": outcome,
            "shootout": res["shootout"] if res else [], "rows": F["N"], "minutes": F["N"] / PER_SEC / 60.0,
            "picked": setup.get("player", ""), "roles": roles, "duration": setup.get("duration"),
            "puzzle": puzzle, "session": setup.get("session"), "round": setup.get("round"),
            "dir_changes_s": b["dir_changes_s"], "kick_presses_min": b["kick_presses_s"] * 60.0, "idle_pct": b["idle_pct"],
            "on_ball_pct": 100.0 * float((F["dist"] < ON_BALL).mean())}


def summary(folder=None):
    """Everything the Dataset page shows (cached until a file is added, removed or changed)."""
    fs = human_data.files(folder)
    key = tuple((f, os.path.getmtime(f)) for f in fs)
    if _cache["key"] == key:
        return _cache["data"]
    matches, frames = [], []
    for f in fs:
        try:
            d = human_data.load(f)
            F = _frame(d)
        except (OSError, ValueError, KeyError) as e:
            matches.append({"id": os.path.basename(f)[:-4], "error": "%s: %s" % (type(e).__name__, e)})
            continue
        frames.append(F)
        matches.append(match_row(f, d, F))
    ok = [m for m in matches if "error" not in m]
    N = sum(F["N"] for F in frames)
    out = {"matches": matches, "folder": os.path.relpath(folder or human_data.data_dir(), ROOT), "rows": N,
           "minutes": N / PER_SEC / 60.0, "files": len(fs)}
    out["record"] = {k: sum(1 for m in ok if m["outcome"] == k) for k in ("W", "D", "L", "left")}
    out["goals"] = [sum(m["gf"] for m in ok if m["complete"]), sum(m["ga"] for m in ok if m["complete"])]
    by = {}
    for m in ok:
        for key in ("control:" + m["control"], "league:" + m["opponent"].get("league", "?")):
            by[key] = by.get(key, 0.0) + m["minutes"]
    out["minutes_by"] = by
    if not frames:
        out["empty"] = True
        _cache.update(key=key, data=out)
        return out
    # behaviour: per match, then pooled over all decisions (chains never cross matches)
    pooled = {"move": _cat(frames, "move"), "kick": _cat(frames, "kick").astype(bool), "toward": _cat(frames, "toward").astype(bool),
              "moving": _cat(frames, "moving").astype(bool),
              "chain": np.concatenate([np.append(F["chain"], False) for F in frames])[:-1]}
    out["behaviour"] = _behaviour(pooled)
    mv = pooled["move"]
    out["moves"] = [100.0 * float((mv == i).mean()) for i in range(9)]
    x, y, bx, by_, dist = (_cat(frames, k) for k in ("x", "y", "bx", "by", "dist"))
    rank, ours = _cat(frames, "rank").astype(int), _cat(frames, "ours").astype(bool)
    kick_rise = np.concatenate([np.append(False, F["kick"][1:] & ~F["kick"][:-1] & F["chain"]) for F in frames])
    out["heat"] = {"player": _heat(x, y), "ball": _heat(bx, by_), "kicks": _heat(x[kick_rise], y[kick_rise])}
    out["kicks_xy"] = [[round(float(a), 3), round(float(b), 3)] for a, b in zip(x[kick_rise][:600], y[kick_rise][:600])]
    # coverage: which situations the dataset has examples of
    bucket = np.digitize(dist, DIST_EDGES)
    out["distance"] = [{"label": DIST_LABELS[i], "pct": 100.0 * float((bucket == i).mean())} for i in range(4)]
    out["phase"] = {"ours_pct": 100.0 * float(ours.mean()), "ball_own_half_pct": 100.0 * float((bx < 0).mean())}
    toward, moving, kick = pooled["toward"], pooled["moving"], pooled["kick"]
    ranks = []
    for r in range(5):
        sel = rank == r
        n = int(sel.sum())
        row = {"label": RANKS[r], "rows": n, "pct": 100.0 * n / N}
        for ph, pm in (("ours", ours), ("theirs", ~ours)):
            row[ph + "_rows"] = int((sel & pm).sum())
        if n:
            mvs = sel & moving
            row.update(idle_pct=100.0 * float((mv[sel] == 0).mean()), toward_pct=100.0 * float(toward[mvs].mean()) if mvs.any() else None,
                       kick_pct=100.0 * float(kick[sel].mean()), dist_px=float(dist[sel].mean()), x=float(x[sel].mean()), y=float(y[sel].mean()))
        ranks.append(row)
    out["ranks"] = ranks
    # moves split by situation: with / without the ball nearby, in / out of possession
    sits = [("in possession, on the ball", ours & (dist < ON_BALL)), ("in possession, off the ball", ours & (dist >= ON_BALL)),
            ("out of possession", ~ours), ("last one back (only the keeper behind), out of possession", ~ours & (rank <= 1))]
    out["situations"] = [{"label": l, "rows": int(s.sum()), "moves": [100.0 * float((mv[s] == i).mean()) if s.any() else 0.0 for i in range(9)],
                          "toward_pct": 100.0 * float(toward[s & moving].mean()) if (s & moving).any() else None,
                          "idle_pct": 100.0 * float((mv[s] == 0).mean()) if s.any() else None} for l, s in sits]
    out["thin"] = [r["label"] for r in ranks if r["rows"] < 1800] + \
                  [s["label"] for s in out["situations"] if s["rows"] < 1800]          # under one minute of examples
    _cache.update(key=key, data=out)
    return out


def match_frames(match_id, folder=None):
    """One recorded match for the replay: players, pitch, team colours, and every row (positions rounded to 0.1 px)."""
    path = next((f for f in human_data.files(folder) if os.path.basename(f)[:-4] == match_id), None)
    if path is None:
        raise KeyError(match_id)
    d = human_data.load(path)
    m = d["meta"]
    n = len(m["players"])
    st = d["state"]
    colors = []
    try:
        from soccer.data import database, resolve_kits
        db = database()
        teams = [db.teams[t["id"]] for t in m["teams"]]
        colors = ["#" + k[0] for k in resolve_kits(*teams)]
    except (KeyError, ImportError):
        colors = ["#4a9eff", "#ff6b6b"]
    pos = np.round(st[:, [4 * i + j for i in range(n) for j in (0, 1)]], 1)
    return {"id": match_id, "meta": {k: m[k] for k in ("players", "pitch", "teams", "human_team", "control", "started", "result", "complete")},
            "colors": colors, "attack": 1.0 if m["human_team"] == 0 else -1.0,
            "p": pos.tolist(), "b": np.round(st[:, 4 * n:4 * n + 2], 1).tolist(), "ctrl": d["ctrl"].tolist(), "move": d["move"].tolist(),
            "kick": d["kick"].tolist(), "score": d["score"].tolist(), "time_left": np.round(d["time_left"], 1).tolist(),
            "tick": d["tick"].tolist()}


if __name__ == "__main__":
    s = summary()
    print(json.dumps({k: v for k, v in s.items() if k not in ("heat", "kicks_xy")}, indent=1, default=float))
