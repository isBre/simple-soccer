"""The Elo ladder's statistics (lab/ladder.py) on made-up matches drawn from known strengths (no simulation, a few seconds):

  goals      goal_model() recovers the attack / defence strengths the goals were drawn from, and adjusted_goals() does not
             depend on who a team happened to play (a strong team meeting only strong opponents scores fewer raw goals)
  intervals  fit()'s 95% intervals are relative to the average rating: they shrink with more games (they no longer carry the
             ±125 uncertainty of the level of the whole scale)
  estimate   _rating_vs_fixed() / _strength_vs_fixed() (the estimated Elo during training) recover a team's rating and goals
             against opponents held fixed

  python3 tests/test_ladder.py"""
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lab import ladder                    # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print("%s %s %s" % ("ok  " if ok else "FAIL", name, detail))
    if not ok:
        FAILS.append(name)


def poisson(rng, lam):
    k, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def made_up(n_teams=12, pairs=4000, seed=1, biased=False):
    """Matches between teams with known (elo, att, def). biased: the pairs prefer close ratings, as choose_pairs() does."""
    rng = random.Random(seed)
    teams = []
    for i in range(n_teams):
        att = -0.8 + 1.6 * i / (n_teams - 1)
        dfn = -0.6 + 1.2 * i / (n_teams - 1)
        teams.append({"id": "t%d" % i, "sha": "x", "att": att, "def": dfn})
    mu = 0.0
    res = []
    for _ in range(pairs):
        a, b = rng.sample(range(n_teams), 2)
        if biased and abs(a - b) > 2 and rng.random() < 0.9:
            continue
        ta, tb = teams[a], teams[b]
        ga = poisson(rng, math.exp(mu + ta["att"] - tb["def"]))
        gb = poisson(rng, math.exp(mu + tb["att"] - ta["def"]))
        res.append({"protocol": ladder.PROTOCOL, "a": ta["id"], "b": tb["id"], "a_sha": "x", "b_sha": "x", "ga": ga, "gb": gb})
    return teams, res


def test_goals():
    teams, res = made_up(biased=True)
    gm = ladder.goal_model(teams, res)
    centre_a = sum(t["att"] for t in teams) / len(teams)
    centre_d = sum(t["def"] for t in teams) / len(teams)
    err = max(abs((gm["att"][t["id"]][0] - sum(gm["att"][u["id"]][0] for u in teams) / len(teams)) - (t["att"] - centre_a)) for t in teams)
    check("goals: attack strengths recovered", err < 0.2, "max error %.3f" % err)
    err = max(abs((gm["def"][t["id"]][0] - sum(gm["def"][u["id"]][0] for u in teams) / len(teams)) - (t["def"] - centre_d)) for t in teams)
    check("goals: defence strengths recovered", err < 0.2, "max error %.3f" % err)
    tab = ladder.goal_table(teams, res)
    raw = {}
    for r in res:
        for me, gf in ((r["a"], r["ga"]), (r["b"], r["gb"])):
            raw.setdefault(me, []).append(gf)
    best, worse = "t11", "t8"
    raw_best, raw_worse = sum(raw[best]) / len(raw[best]), sum(raw[worse]) / len(raw[worse])
    check("goals: adjusted ordering follows the true attack", tab[best]["gf"] > tab[worse]["gf"],
          "adjusted %.2f > %.2f (raw %.2f vs %.2f)" % (tab[best]["gf"], tab[worse]["gf"], raw_best, raw_worse))
    se_ok = all(0 < tab[t["id"]]["gf_se"] < 0.2 * tab[t["id"]]["gf"] + 0.05 for t in teams)
    check("goals: standard errors are finite and small with many games", se_ok)


def test_intervals():
    teams, res = made_up(pairs=600)
    few = ladder.fit(teams, res)
    teams, res = made_up(pairs=6000)
    many = ladder.fit(teams, res)
    a, b = 1.96 * few["t5"]["se"], 1.96 * many["t5"]["se"]
    check("intervals: shrink with more games", b < 0.5 * a, "±%.0f (600 pairs) -> ±%.0f (6000 pairs)" % (a, b))
    check("intervals: no longer the ±125 of the scale's level", b < 60, "±%.0f" % b)


def test_estimate():
    rng = random.Random(3)
    true_elo = 1700.0
    opp = [1300 + 50 * k for k in range(12)]
    scores = []
    for _ in range(400):
        for o in opp:
            p = 1.0 / (1.0 + 10 ** ((o - true_elo) / 400.0))
            scores.append((o, 1.0 if rng.random() < p else 0.0))
    elo, se = ladder._rating_vs_fixed([o for o, _ in scores], [s for _, s in scores])
    check("estimate: rating against fixed opponents", abs(elo - true_elo) < 30 and se < 15, "%.0f ± %.0f (true %.0f)" % (elo, 1.96 * se, true_elo))
    base = [0.1 * k - 0.5 for k in range(12)] * 200
    y = [poisson(rng, math.exp(b + 0.4)) for b in base]
    x, xse = ladder._strength_vs_fixed(base, y, +1)
    check("estimate: attack against fixed defences", abs(x - 0.4) < 0.05, "%.3f ± %.3f (true 0.4)" % (x, 1.96 * xse))
    y = [poisson(rng, math.exp(b - 0.3)) for b in base]
    x, xse = ladder._strength_vs_fixed(base, y, -1)
    check("estimate: defence against fixed attacks", abs(x - 0.3) < 0.05, "%.3f ± %.3f (true 0.3)" % (x, 1.96 * xse))


if __name__ == "__main__":
    test_goals()
    test_intervals()
    test_estimate()
    print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
    sys.exit(1 if FAILS else 0)
