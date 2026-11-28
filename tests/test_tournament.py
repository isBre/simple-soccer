"""The tournaments (game/tournament.py) against stored ones (tests/golden/tournament.json): 8 tournaments of every format
(league with an odd number of teams, knockout of 4 / 8 / 16, groups + knockout) played with made-up results; the shuffled
teams, every fixture, every match seed, the results, standings and player statistics must be identical. Also checks the
knockout round names.

  python3 tests/test_tournament.py [--update]"""
import sys

from game import tournament as tn
from soccer.data import database
import golden

CASES = [[0, 5, 1], [0, 6, 12345], [0, 16, 777], [1, 4, 2], [1, 8, 99999], [1, 16, 31337], [2, 8, 4242], [2, 16, 5]]


def fake(t_seed, ri, idx, fix):
    """The made-up result of a match."""
    h = (t_seed * 31 + ri * 7 + idx * 13) % 11
    hg, ag = h % 3, (h * 5 + idx) % 3
    winner = 0 if hg > ag else 1 if ag > hg else -1
    shoot = []
    if fix["stage"] == "ko" and winner == -1:
        shoot, winner = ([3, 2], 0) if h % 2 == 0 else ([2, 3], 1)
    ev = [{"clock": 30.0 * (k + 1), "team": 0, "scorer_name": "H%d" % k, "own": False} for k in range(hg)]
    ev += [{"clock": 31.0 * (k + 1), "team": 1, "scorer_name": "A%d" % k, "own": k == 1} for k in range(ag)]
    rh, ra = 6.0 + 0.5 * hg, 6.25 + 0.5 * ag
    pl = [{"uid": 0, "id": fix["home"] + "_1", "name": "Home " + fix["home"], "team": 0, "role": "MID", "goals": hg, "assists": 0,
           "saves": 1, "shots": hg + 2, "rating": rh},
          {"uid": 1, "id": fix["away"] + "_1", "name": "Away " + fix["away"], "team": 1, "role": "FWD", "goals": ag,
           "assists": 1 if ag > 0 else 0, "saves": 0, "shots": ag + 1, "rating": ra}]
    return {"teams": [fix["home"], fix["away"]], "scores": [hg, ag], "shootout": shoot, "winner": winner, "events": ev, "players": pl,
            "mom": 0 if rh >= ra else 1}


def play_python():
    ids = sorted(t.id for t in database().teams.values() if t.rl_eval)
    out = []
    for fmt, n, seed in CASES:
        t = tn.create(fmt, ids[:n], ids[0], "arena", 3, 60.0, seed)
        seeds, guard = [], 0
        while not t["finished"] and guard < 200:
            guard += 1
            ri = t["round_index"]
            fixtures = list(tn.current_round(t)["fixtures"])
            for idx, f in enumerate(fixtures):
                if f["played"]:
                    continue
                s = tn.setup_for(t, idx)
                seeds.append([s["seed"], s["allow_draw"]])
                tn.record(t, idx, fake(t["t_seed"], ri, idx, f))
        st = [tn.standings(t)] if fmt == tn.LEAGUE else [tn.standings(t, 0), tn.standings(t, 1)] if fmt == tn.GROUPS else []
        out.append({"t": t, "seeds": seeds, "standings": st})
    return out


def play_python_names():
    """The rounds of a 16-team knockout (Python), for the names."""
    ids = sorted(t.id for t in database().teams.values() if t.rl_eval)
    t = tn.create(tn.KNOCKOUT, ids[:16], ids[0], "arena", 3, 60.0, 3)
    while not t["finished"]:
        ri = t["round_index"]
        for idx, f in enumerate(list(tn.current_round(t)["fixtures"])):
            tn.record(t, idx, fake(3, ri, idx, f))
    return t["rounds"]


def main():
    python = play_python()
    labels = ["%s %d teams seed %d" % (tn.FORMAT_NAMES[fmt], n, seed) for fmt, n, seed in CASES]
    ok = golden.check("tournament", {"cases": labels, "tournaments": python}, "--update" in sys.argv,
                      "tournaments (%d)" % len(CASES))
    names = [r["name"] for r in play_python_names()]
    good = names == ["Round of 16", "Quarter-finals", "Semi-finals", "Final"]
    print("%-24s %s  %s" % ("knockout round names", "OK  " if good else "FAIL", names))
    ok = ok and good
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
