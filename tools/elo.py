"""One Elo ranking for every team: the Rule Based League, the RL League and the trained nets in models/ (5v5 arena).

A full round robin, every pair on both sides with fixed seeds, then one Bradley-Terry fit with draws (Davidson) over ALL results,
shown on the Elo scale (400 points = 10x the odds) with the average team at 1500 and a 95% interval per team (bootstrap over
the matches). The order of the matches does not matter. Results are appended to a JSONL file, so an interrupted run resumes and
a later run with more teams or seeds only plays the missing matches.

  python3 tools/elo.py [--seeds 2] [--duration 180] [--out logs/elo/results.jsonl] [--fit-only] [--md table.md]
"""
import argparse
import glob
import json
import math
import multiprocessing as mp
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from soccer.data import database                         # noqa: E402
from soccer.match import ENDED, Match, make_config       # noqa: E402

ELO = 400.0 / math.log(10.0)


def players():
    """{name: (team id, net spec or None, group)}: rule teams, RL League teams, every net in models/."""
    db = database()
    out = {}
    for t in sorted(db.teams.values(), key=lambda t: t.id):
        out[t.name] = (t.id, None, "rule" if t.league == "rules" else "rl")
    for f in sorted(glob.glob(os.path.join(ROOT, "models", "*.json"))):
        out["net " + os.path.basename(f)[:-5]] = ("rl_team_5", {"model": f}, "net")
    return out


def play(job):
    a, b, seed, duration, P = job
    (ta, na, _), (tb, nb, _) = P[a], P[b]
    c = make_config(ta, tb, "arena", 5, duration, seed)
    c.nets = [na, nb]
    m = Match(c)
    m.run_to_end()
    return {"a": a, "b": b, "seed": seed, "ga": m.scores[0], "gb": m.scores[1], "warn": m.ai.warnings}


def fit(names, res, iters=4000, prior=3.0, init=None):
    """Davidson model: P(i beats j) = p_i / D, P(draw) = nu sqrt(p_i p_j) / D, D = p_i + p_j + nu sqrt(p_i p_j), p = e^theta.
    Maximum a posteriori with a weak N(0, prior^2) prior on theta (keeps an unbeaten team finite). Returns (theta, nu)."""
    idx = {n: k for k, n in enumerate(names)}
    n = len(names)
    I = np.array([idx[r["a"]] for r in res])
    J = np.array([idx[r["b"]] for r in res])
    wa = np.array([1.0 if r["ga"] > r["gb"] else 0.0 for r in res])
    wb = np.array([1.0 if r["gb"] > r["ga"] else 0.0 for r in res])
    dr = 1.0 - wa - wb
    th = np.zeros(n) if init is None else init[0].copy()
    lnu = 0.0 if init is None else math.log(init[1])
    m1, v1, m2, v2 = np.zeros(n), np.zeros(n), 0.0, 0.0
    lr, b1, b2 = 0.05, 0.9, 0.999
    for it in range(1, iters + 1):
        ti, tj = th[I], th[J]
        nu = math.exp(lnu)
        ea, eb, ed = np.exp(ti), np.exp(tj), nu * np.exp(0.5 * (ti + tj))
        D = ea + eb + ed
        # d logL / d theta_i and theta_j for each match
        gi = wa + 0.5 * dr - (ea + 0.5 * ed) / D
        gj = wb + 0.5 * dr - (eb + 0.5 * ed) / D
        g = np.bincount(I, gi, n) + np.bincount(J, gj, n) - th / prior ** 2
        gn = float(np.sum(dr - ed / D))
        m1 = b1 * m1 + (1 - b1) * g
        v1 = b2 * v1 + (1 - b2) * g * g
        th += lr * (m1 / (1 - b1 ** it)) / (np.sqrt(v1 / (1 - b2 ** it)) + 1e-8)
        m2 = b1 * m2 + (1 - b1) * gn
        v2 = b2 * v2 + (1 - b2) * gn * gn
        lnu += lr * (m2 / (1 - b1 ** it)) / (math.sqrt(v2 / (1 - b2 ** it)) + 1e-8)
        if it > iters // 2:
            lr = 0.01
    return th - th.mean(), math.exp(lnu)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2, help="matches per pair and side")
    ap.add_argument("--duration", type=float, default=180.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "logs", "elo", "results.jsonl"))
    ap.add_argument("--fit-only", action="store_true")
    ap.add_argument("--boot", type=int, default=200)
    ap.add_argument("--md", default="", help="also write the table as Markdown here")
    a = ap.parse_args()
    P = players()
    names = sorted(P)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    done = {}
    if os.path.exists(a.out):
        for line in open(a.out):
            r = json.loads(line)
            done[(r["a"], r["b"], r["seed"])] = r
    jobs = []
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            for s in range(a.seeds):
                seed = 90000 + x * 1000 + y * 10 + s
                for home, away in ((names[x], names[y]), (names[y], names[x])):
                    if (home, away, seed) not in done:
                        jobs.append((home, away, seed, a.duration, P))
    if jobs and not a.fit_only:
        print("playing %d matches (%d already stored)" % (len(jobs), len(done)), flush=True)
        t0 = time.time()
        with mp.get_context("fork").Pool(os.cpu_count() or 2) as pool, open(a.out, "a") as f:
            for k, r in enumerate(pool.imap_unordered(play, jobs, chunksize=4)):
                f.write(json.dumps(r) + "\n")
                done[(r["a"], r["b"], r["seed"])] = r
                if (k + 1) % 200 == 0:
                    f.flush()
                    print("  %d/%d  %.0f s" % (k + 1, len(jobs), time.time() - t0), flush=True)
    res = [r for r in done.values() if r["a"] in P and r["b"] in P]
    warn = sorted({w for r in res for w in r["warn"]})
    th, nu = fit(names, res)
    rng = np.random.default_rng(7)
    boots = []
    for _ in range(a.boot):
        sample = [res[i] for i in rng.integers(0, len(res), len(res))]
        boots.append(fit(names, sample, iters=1500, init=(th, nu))[0])
    boots = np.array(boots)
    lo, hi = np.percentile(boots, 2.5, axis=0), np.percentile(boots, 97.5, axis=0)
    rec = {n: [0, 0, 0, 0, 0] for n in names}             # W D L GF GA
    for r in res:
        for me, gf, ga in ((r["a"], r["ga"], r["gb"]), (r["b"], r["gb"], r["ga"])):
            s = rec[me]
            s[0 if gf > ga else (1 if gf == ga else 2)] += 1
            s[3] += gf
            s[4] += ga
    order = np.argsort(-th)
    rows = []
    for rank, k in enumerate(order, 1):
        n = names[k]
        w, d, l, gf, ga = rec[n]
        g = w + d + l
        rows.append((rank, n, P[n][2], 1500 + ELO * th[k], 1500 + ELO * lo[k], 1500 + ELO * hi[k], w, d, l, gf / g, ga / g))
    head = "%-4s %-34s %-5s %6s  %-13s %5s %5s %5s  %s" % ("#", "team", "kind", "Elo", "95% interval", "W", "D", "L", "GF/GA per match")
    print("\n%d teams, %d matches, draw factor nu %.2f" % (len(names), len(res), nu))
    print(head)
    for r in rows:
        print("%-4d %-34s %-5s %6.0f  %5.0f - %-5.0f %5d %5d %5d  %.2f/%.2f" % r)
    if warn:
        print("warnings:", warn)
    if a.md:
        with open(a.md, "w") as f:
            f.write("| # | Team | Kind | Elo | 95% interval | W | D | L | GF/match | GA/match |\n|---|---|---|---|---|---|---|---|---|---|\n")
            for r in rows:
                f.write("| %d | %s | %s | %.0f | %.0f-%.0f | %d | %d | %d | %.2f | %.2f |\n" % r)


if __name__ == "__main__":
    main()
