"""Tunes the Opus 5.5 High team brain (soccer/ai/opus.py constants + the style values its finisher uses) against strong trained
nets with CMA-ES. The structure (one player on the ball, jobs for the others) is not touched: only distances, margins, weights.

Fitness of a parameter set = points per match + 0.5 x goal difference per match against the nets in NETS, 5v5 arena, 90 s (the
ladder's protocol), both sides. All candidates of one generation play the same seeds (paired); the seeds change every generation.
Every VALIDATE_EVERY generations the CMA mean is played on fixed validation seeds (more matches): the best of those is the result.

  python3 tools/tune_opus.py [--gens 40] [--seeds 4] [--workers N] [--out logs/tune]   (resumes from <out>/state.pkl)
  python3 tools/tune_opus.py --show                                         best validated parameters so far
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import pickle
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NETS = ["data/models/rl_5v5_arena_v2.json", "data/models/rl_5v5_arena_v4.json", "data/models/rl_5v5_arena_v5.json",
        "models/jit8_best.json", "models/x_anchor_wall_strong_best.json", "models/x_wide_persist_best.json",
        "models/x_persist_lr_best.json", "models/x_kickstart_best.json", "models/t48_best.json", "models/team46_w256.json"]
DURATION = 90.0
VALIDATE_EVERY = 4
VAL_SEEDS = 8

# (name, default, low, high); "style." = an attribute of the opus_high style, else a module constant of soccer.ai.opus
PARAMS = [
    ("VALXG", 0.2, 0.05, 0.6), ("VALPROG", 0.03, 0.0, 0.15), ("HOLD_K", 0.5, 0.1, 1.2), ("WALL_PEN", 0.01, 0.0, 0.05),
    ("RECV_SHOT", 0.9, 0.2, 1.5), ("SHOT_READ", 24.0, 0.0, 50.0), ("KICK_REL", 0.6, 0.2, 1.0), ("PRESSED", 45.0, 25.0, 90.0),
    ("FINAL_FROM", 0.35, -0.3, 0.9), ("BOX_FROM", 0.3, -0.3, 0.9), ("BOX_DEPTH", 80.0, 30.0, 200.0), ("BOX_Y", 45.0, 0.0, 110.0),
    ("ATTACK_NEED_OWN", 12.0, 0.0, 30.0), ("REST_BACK", 330.0, 150.0, 500.0), ("SUPPORT_MIN", 110.0, 50.0, 200.0),
    ("SUPPORT_MAX", 330.0, 200.0, 480.0), ("SPACING", 170.0, 100.0, 260.0), ("COVER_FROM", 0.35, -0.5, 1.0),
    ("COVER_DIST", 115.0, 50.0, 220.0), ("MARK_GAP_FAR", 55.0, 15.0, 100.0), ("MARK_GAP_NEAR", 28.0, 12.0, 70.0),
    ("GUARD_TRIGGER", 85.0, 30.0, 170.0), ("POKE_RADIUS", 260.0, 0.0, 500.0),
    ("style.long_shot", 0.5, 0.0, 1.0), ("style.pass_bias", 0.7, 0.2, 1.0), ("style.risk", 0.5, 0.0, 1.0),
    ("style.keeper_sweep", 0.3, 0.0, 1.0),
]
N = len(PARAMS)
LO = np.array([p[2] for p in PARAMS])
HI = np.array([p[3] for p in PARAMS])
X0 = np.array([(p[1] - p[2]) / (p[3] - p[2]) for p in PARAMS])


def decode(x):
    v = LO + np.clip(x, 0.0, 1.0) * (HI - LO)
    return {PARAMS[i][0]: float(v[i]) for i in range(N)}


def apply(params):
    from soccer.ai import opus
    from soccer.data import database
    st = database().styles["opus_high"]
    for k, v in params.items():
        if k.startswith("style."):
            setattr(st, k[6:], v)
        else:
            setattr(opus, k, v)


def _nice():
    try:
        os.nice(15)                      # background priority: the machine stays responsive (and cooler)
    except OSError:
        pass


def play(job):
    params, net, seed, side = job
    apply(params)
    from soccer.match import Match, make_config
    a, b = ("opus_high", "rl_team_5") if side == 0 else ("rl_team_5", "opus_high")
    c = make_config(a, b, "arena", 5, DURATION, seed)
    c.nets = [None, None]
    c.nets[1 - side] = {"model": os.path.join(ROOT, net)}
    m = Match(c)
    m.run_to_end()
    return m.scores[side], m.scores[1 - side]


def fitness_many(pool, cands, seeds):
    """Fitness of each parameter dict in cands, all on the same (net, seed, side) set. Returns [(fitness, pts, gd)]."""
    jobs, owner = [], []
    for ci, prm in enumerate(cands):
        for net in NETS:
            for s in seeds:
                for side in (0, 1):
                    jobs.append((prm, net, s, side))
                    owner.append(ci)
    res = pool.map(play, jobs, chunksize=2)
    out = []
    for ci in range(len(cands)):
        r = [res[k] for k in range(len(res)) if owner[k] == ci]
        pts = sum(3 if g > a else (1 if g == a else 0) for g, a in r) / len(r)
        gd = sum(g - a for g, a in r) / len(r)
        out.append((pts + 0.5 * gd, pts, gd))
    return out


class CMA:
    """Plain CMA-ES (Hansen's tutorial), maximising."""

    def __init__(self, x0, sigma):
        n = len(x0)
        self.n, self.mean, self.sigma = n, np.array(x0, float), sigma
        self.lam = 4 + int(3 * math.log(n))
        self.mu = self.lam // 2
        w = np.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.w = w / w.sum()
        self.mueff = 1.0 / (self.w ** 2).sum()
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((n + 2) ** 2 + self.mueff))
        self.damps = 1 + 2 * max(0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) + self.cs
        self.pc, self.ps = np.zeros(n), np.zeros(n)
        self.B, self.D, self.C = np.eye(n), np.ones(n), np.eye(n)
        self.chiN = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        self.gen = 0

    def ask(self, rng):
        z = rng.standard_normal((self.lam, self.n))
        y = z * self.D @ self.B.T
        return self.mean + self.sigma * y

    def tell(self, xs, fits):
        order = np.argsort(-np.asarray(fits))
        xs = np.asarray(xs)[order[:self.mu]]
        old = self.mean
        self.mean = self.w @ xs
        y = (self.mean - old) / self.sigma
        Cinvsqrt = self.B @ np.diag(1 / self.D) @ self.B.T
        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * Cinvsqrt @ y
        self.gen += 1
        hsig = np.linalg.norm(self.ps) / math.sqrt(1 - (1 - self.cs) ** (2 * self.gen)) / self.chiN < 1.4 + 2 / (self.n + 1)
        self.pc = (1 - self.cc) * self.pc + hsig * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * y
        ys = (xs - old) / self.sigma
        self.C = (1 - self.c1 - self.cmu) * self.C + self.c1 * (np.outer(self.pc, self.pc) + (not hsig) * self.cc * (2 - self.cc) * self.C) \
            + self.cmu * (ys.T * self.w) @ ys
        self.sigma *= math.exp((self.cs / self.damps) * (np.linalg.norm(self.ps) / self.chiN - 1))
        self.C = np.triu(self.C) + np.triu(self.C, 1).T
        d2, self.B = np.linalg.eigh(self.C)
        self.D = np.sqrt(np.maximum(d2, 1e-20))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=4, help="seeds per net and side for each candidate")
    ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--out", default=os.path.join(ROOT, "logs", "tune"))
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2, help="parallel matches (fewer = cooler laptop)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    state_f, log_f, best_f = (os.path.join(a.out, f) for f in ("state.pkl", "log.jsonl", "best.json"))
    if a.show:
        print(open(best_f).read())
        return
    rng = np.random.default_rng(11)
    if os.path.exists(state_f):
        es, best, rng = pickle.load(open(state_f, "rb"))
        print("resumed at generation %d" % es.gen, flush=True)
    else:
        es, best = CMA(X0, a.sigma), None
    val_seeds = [880000 + k for k in range(VAL_SEEDS)]
    with mp.get_context("fork").Pool(a.workers, initializer=_nice) as pool:
        if best is None:
            t0 = time.time()
            f = fitness_many(pool, [decode(X0)], val_seeds)[0]
            best = {"gen": 0, "fitness": f[0], "pts": f[1], "gd": f[2], "params": decode(X0), "default": True}
            json.dump(best, open(best_f, "w"), indent=1)
            print("defaults on validation: fitness %.3f pts %.2f gd %.2f (%.0f s)" % (f[0], f[1], f[2], time.time() - t0), flush=True)
        while es.gen < a.gens:
            t0 = time.time()
            xs = es.ask(rng)
            seeds = [700000 + es.gen * 100 + k for k in range(a.seeds)]
            fits = fitness_many(pool, [decode(x) for x in xs], seeds)
            es.tell(xs, [f[0] for f in fits])
            rec = {"gen": es.gen, "sigma": es.sigma, "best": max(f[0] for f in fits), "median": float(np.median([f[0] for f in fits])),
                   "secs": round(time.time() - t0)}
            if es.gen % VALIDATE_EVERY == 0:
                f = fitness_many(pool, [decode(es.mean)], val_seeds)[0]
                rec.update({"val_fitness": f[0], "val_pts": f[1], "val_gd": f[2]})
                if f[0] > best["fitness"]:
                    best = {"gen": es.gen, "fitness": f[0], "pts": f[1], "gd": f[2], "params": decode(es.mean), "default": False}
                    json.dump(best, open(best_f, "w"), indent=1)
            with open(log_f, "a") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
            pickle.dump((es, best, rng), open(state_f, "wb"))
    print("best:", json.dumps(best, indent=1))


if __name__ == "__main__":
    main()
