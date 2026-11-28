"""The ratings (elo/) on made-up results drawn from known strengths (no match is simulated; a few seconds):

  players     the fit recovers the players' strengths on the pinned scale (the average rule-based player = 1500)
  bonus       a team's bonus over the average of its players is recovered when it is real, and stays near 0 when it is not
  intervals   intervals shrink with more games and do not carry the uncertainty of where the whole scale sits
  pinned      adding a new entry with its games does not move the scale (the rule-based average stays 1500, the others barely move)
  stale       results whose files changed (another sha) stop counting
  goals       the goals model recovers attack / defence strengths; adjusted goals do not depend on who an entry happened to meet
  estimate    rating_vs_fixed / strength_vs_fixed (the estimated Elo during training) recover a rating and goals
  database    two processes writing at once lose nothing; the rating history is thinned as it ages
  schedule    an entry without games is paired first (placement)

  python3 tests/test_elo.py"""
import math
import multiprocessing as mp
import os
import random
import sys
import tempfile

from elo import BASE, K, PLACEMENT, db, model, schedule

FAILS = []


def check(name, ok, detail=""):
    print("%s %s %s" % ("ok  " if ok else "FAIL", name, detail))
    if not ok:
        FAILS.append(name)


class FakeEntry:
    def __init__(self, eid, sub, comp=None, bonus=False, sha="x"):
        self.id, self.sub, self.sha = eid, sub, sha
        self.unit = comp is None
        self.bonus = bonus
        self.kind = "team" if bonus else "player"
        self._comp = comp

    def compose(self, size):
        return {self.id: 1.0} if self.unit else dict(self._comp)

    def sizes(self):
        return [3]


class FakeRoster:
    def __init__(self, entries):
        self.entries = {e.id: e for e in entries}

    def at(self, size):
        return dict(self.entries)


def made_up(strength, bonus, entries, pairs, seed=1, draws=0.15):
    """Summed pairings drawn from true strengths (Elo) and team bonuses: [{a, b, a_sha, b_sha, n, score, w, d, ga, gb}]."""
    rng = random.Random(seed)
    true = {}
    for e in entries:
        true[e.id] = sum(w * strength[u] for u, w in e.compose(3).items()) + bonus.get(e.id, 0.0)
    ids = [e.id for e in entries]
    agg = {}
    for _ in range(pairs):
        a, b = rng.sample(ids, 2)
        p = 1.0 / (1.0 + 10 ** ((true[b] - true[a]) / 400.0))
        r = rng.random()
        s = 0.5 if r < draws else (1.0 if rng.random() < (p - draws / 2) / (1 - draws) else 0.0)
        g = agg.setdefault((a, b), {"a": a, "b": b, "a_sha": "x", "b_sha": "x", "n": 0, "score": 0.0, "w": 0, "d": 0, "ga": 0, "gb": 0})
        g["n"] += 1
        g["score"] += s
        g["w"] += s == 1.0
        g["d"] += s == 0.5
        g["ga"] += 1 if s == 1.0 else 0
        g["gb"] += 1 if s == 0.0 else 0
    return list(agg.values()), true


def world(extra_bonus=80.0):
    strength = {"p%d" % i: 1300.0 + 50.0 * i for i in range(10)}           # rule-based players, mean 1525
    units = [FakeEntry(u, "rules") for u in strength]
    teams = [FakeEntry("t_plus", "mixed", {"p2": 0.4, "p5": 0.3, "p8": 0.3}, bonus=True),
             FakeEntry("t_zero", "mixed", {"p1": 0.5, "p6": 0.5}, bonus=True)]
    return strength, {"t_plus": extra_bonus}, units + teams


def test_players_and_bonus():
    strength, bonus, entries = world()
    groups, true = made_up(strength, bonus, entries, 20000)
    rat = model.fit(FakeRoster(entries), 3, groups)
    centre = sum(strength.values()) / len(strength)
    err = max(abs(rat[u]["elo"] - (strength[u] - centre + BASE)) for u in strength)
    check("players: strengths recovered on the pinned scale", err < 40, "max error %.0f Elo" % err)
    mean = sum(rat[u]["elo"] for u in strength) / len(strength)
    check("players: the rule-based average is pinned at 1500", abs(mean - BASE) < 1e-6, "%.3f" % mean)
    check("bonus: a real team bonus is recovered", 40 < rat["t_plus"]["bonus"] < 120, "%.0f (true 80)" % rat["t_plus"]["bonus"])
    check("bonus: no bonus stays near 0", abs(rat["t_zero"]["bonus"]) < 30, "%.0f (true 0)" % rat["t_zero"]["bonus"])


def test_intervals():
    strength, bonus, entries = world()
    few = model.fit(FakeRoster(entries), 3, made_up(strength, bonus, entries, 600)[0])
    many = model.fit(FakeRoster(entries), 3, made_up(strength, bonus, entries, 6000)[0])
    a, b = 1.96 * few["p5"]["se"], 1.96 * many["p5"]["se"]
    check("intervals: shrink with more games", b < 0.5 * a, "±%.0f (600 games) -> ±%.0f (6000 games)" % (a, b))
    check("intervals: no level-of-the-scale uncertainty in them", b < 60, "±%.0f" % b)


def test_pinned():
    strength, bonus, entries = world()
    groups, _ = made_up(strength, bonus, entries, 8000, seed=2)
    before = model.fit(FakeRoster(entries), 3, groups)
    strength2 = dict(strength, newnet=1900.0)
    entries2 = entries + [FakeEntry("newnet", "net")]
    extra, _ = made_up(strength2, bonus, entries2, 3000, seed=3)
    extra = [g for g in extra if "newnet" in (g["a"], g["b"])]
    after = model.fit(FakeRoster(entries2), 3, groups + extra)
    moved = max(abs(after[u]["elo"] - before[u]["elo"]) for u in strength)
    mean = sum(after[u]["elo"] for u in strength) / len(strength)
    check("pinned: a strong new entry does not move the scale", abs(mean - BASE) < 1e-6 and moved < 15,
          "rule-based average %.1f, the others moved at most %.1f Elo" % (mean, moved))


def test_stale():
    strength, bonus, entries = world()
    groups, _ = made_up(strength, bonus, entries, 500)
    groups[0] = dict(groups[0], a_sha="old")
    ros = FakeRoster(entries)
    ok = model.valid_groups(ros, 3, groups)
    check("stale: results of a changed file stop counting", len(ok) == len(groups) - 1, "%d of %d count" % (len(ok), len(groups)))


def poisson(rng, lam):
    k, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def test_goals():
    rng = random.Random(1)
    n = 12
    ents = [FakeEntry("t%d" % i, "rules") for i in range(n)]
    att = {"t%d" % i: -0.8 + 1.6 * i / (n - 1) for i in range(n)}
    dfn = {"t%d" % i: -0.6 + 1.2 * i / (n - 1) for i in range(n)}
    agg = {}
    for _ in range(4000):
        a, b = rng.sample(range(n), 2)
        if abs(a - b) > 2 and rng.random() < 0.9:                    # strong teams mostly meet strong teams
            continue
        ia, ib = "t%d" % a, "t%d" % b
        ga, gb = poisson(rng, math.exp(att[ia] - dfn[ib])), poisson(rng, math.exp(att[ib] - dfn[ia]))
        g = agg.setdefault((ia, ib), {"a": ia, "b": ib, "a_sha": "x", "b_sha": "x", "n": 0, "score": 0.0, "w": 0, "d": 0, "ga": 0, "gb": 0})
        g["n"] += 1
        g["ga"] += ga
        g["gb"] += gb
        g["score"] += 1.0 if ga > gb else 0.5 if ga == gb else 0.0
    groups = list(agg.values())
    gm = model.goal_model(FakeRoster(ents), 3, groups)
    ca, cd = sum(att.values()) / n, sum(dfn.values()) / n
    ma = sum(gm["att"][i][0] for i in att) / n
    md = sum(gm["def"][i][0] for i in dfn) / n
    err = max(max(abs(gm["att"][i][0] - ma - (att[i] - ca)), abs(gm["def"][i][0] - md - (dfn[i] - cd))) for i in att)
    check("goals: attack and defence strengths recovered", err < 0.2, "max error %.3f" % err)
    tab = model.goal_table(gm)
    check("goals: adjusted goals follow the true attack", tab["t11"]["gf"] > tab["t8"]["gf"], "%.2f > %.2f" % (tab["t11"]["gf"], tab["t8"]["gf"]))


def test_estimate():
    rng = random.Random(3)
    true_elo = 1700.0
    opp = [1300 + 50 * k for k in range(12)]
    scores = []
    for _ in range(400):
        for o in opp:
            p = 1.0 / (1.0 + 10 ** ((o - true_elo) / 400.0))
            scores.append((o, 1.0 if rng.random() < p else 0.0))
    elo, se = model.rating_vs_fixed([o for o, _ in scores], [s for _, s in scores])
    check("estimate: rating against fixed opponents", abs(elo - true_elo) < 30 and se < 15, "%.0f ± %.0f (true %.0f)" % (elo, 1.96 * se, true_elo))
    base = [0.1 * k - 0.5 for k in range(12)] * 200
    y = [poisson(rng, math.exp(b + 0.4)) for b in base]
    x, xse = model.strength_vs_fixed(base, y, +1)
    check("estimate: attack against fixed defences", abs(x - 0.4) < 0.05, "%.3f (true 0.4)" % x)


def _writer(args):
    path, k = args
    conn = db.connect(path)
    for i in range(50):
        db.add_results(conn, [{"size": 3, "a": "w%d" % k, "b": "x", "a_sha": "s", "b_sha": "s", "a_side": 0, "ga": 1, "gb": 0, "seed": i}])
    conn.close()


def test_database():
    path = os.path.join(tempfile.mkdtemp(prefix="elo_test_"), "elo.db")
    db.connect(path).close()
    with mp.get_context("spawn").Pool(2) as pool:
        pool.map(_writer, [(path, 0), (path, 1)])
    conn = db.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    check("database: two writers at once lose nothing", n == 100, "%d of 100 rows" % n)
    for h in range(20):                                              # 20 snapshots, 10 hours old, one hour apart in pairs
        t = "2020-01-01T%02d:%02d:00" % (h // 2, 0 if h % 2 == 0 else 30)
        conn.execute("INSERT INTO history (t, size, matches, elo) VALUES (?, 3, 0, '{}')", (t,))
    db.thin_history(conn, 3)
    left = conn.execute("SELECT COUNT(*) FROM history WHERE size = 3").fetchone()[0]
    check("database: old history thinned to one snapshot per hour", left == 10, "%d snapshots left of 20" % left)


def test_schedule():
    strength, bonus, entries = world()
    groups, _ = made_up(strength, bonus, entries, 3000)
    rat = model.fit(FakeRoster(entries), 3, groups)
    rat["newcomer"] = {"elo": BASE, "se": 300.0, "games": 0}
    pairs = schedule.choose_pairs(list(rat), rat, schedule.pair_games(groups), 6, random.Random(1))
    check("schedule: a new entry is paired first", pairs and "newcomer" in pairs[0], "first pair %s" % (pairs[0],))
    check("schedule: nobody plays more than two pairs a round",
          all(sum(1 for p in pairs if i in p) <= 2 for i in rat), "%d pairs" % len(pairs))


if __name__ == "__main__":
    test_players_and_bonus()
    test_intervals()
    test_pinned()
    test_stale()
    test_goals()
    test_estimate()
    test_database()
    test_schedule()
    print("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
    sys.exit(1 if FAILS else 0)
