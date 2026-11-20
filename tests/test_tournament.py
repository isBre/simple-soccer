"""The game's tournaments (game/tournament.py) against the Godot game's Tournament (scripts/tournament/tournament.gd) in the
reference checkout ($SOCCER_REF, see tests/test_match.py): 8 tournaments of every format (league with an odd number of
teams, knockout of 4 / 8 / 16, groups + knockout) are played with the same made-up results on both sides
(tests/reference/record_tournament.gd); the shuffled teams, every fixture, every match seed, the results, standings and
player statistics must be identical. Knockout round names are the one intended difference (the Godot game called the final
"Round of 2"; see game/tournament.py _ko_name).

  python3 tests/test_tournament.py"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import tournament as tn                         # noqa: E402
from soccer.data import database                          # noqa: E402
from tests.godot_run import install_reference, run_scene  # noqa: E402

CASES = [[0, 5, 1], [0, 6, 12345], [0, 16, 777], [1, 4, 2], [1, 8, 99999], [1, 16, 31337], [2, 8, 4242], [2, 16, 5]]


def fake(t_seed, ri, idx, fix):
    """The made-up result of a match (the formula of record_tournament.gd)."""
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


def diff(a, b, path=""):
    """Differences between two JSON values (numbers compared as numbers: Godot writes every number as a float)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k), b.get(k), path + "." + str(k))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [(path, "length", len(a), len(b))]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, "%s[%d]" % (path, i))]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return [] if abs(a - b) <= 1e-9 * max(1.0, abs(a)) else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


def main():
    ref = os.environ.get("SOCCER_REF")
    if not ref:
        sys.exit("set SOCCER_REF to a checkout of the Godot implementation (see tests/test_match.py)")
    install_reference(ref)
    godot = json.loads(run_scene("res://tests/godot/record_tournament.tscn", "TOURNAMENTS ", project=ref, timeout=600))
    python = play_python()
    ok = True
    for (fmt, n, seed), g, p in zip(CASES, godot, python):
        for side in (g, p):                                    # knockout round names: the one intended difference
            for r in side["t"]["rounds"]:
                if r["stage"] == "ko":
                    r.pop("name", None)
        d = diff(p, g)
        rounds = len(p["t"]["rounds"])
        print("%-18s %2d teams seed %5d  %s  %d rounds, %d matches, champion %s%s" % (tn.FORMAT_NAMES[fmt], n, seed, "OK  " if not d else "FAIL",
              rounds, len(p["seeds"]), p["t"]["champion"], "" if not d else "\n   " + "\n   ".join(map(str, d[:8]))))
        ok = ok and not d
    names = [r["name"] for r in play_python_names()]
    good = names == ["Round of 16", "Quarter-finals", "Semi-finals", "Final"]
    print("knockout round names %s  %s" % ("OK  " if good else "FAIL", names))
    ok = ok and good
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
