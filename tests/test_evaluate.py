"""The evaluation reports (rl/evaluate.py) against stored ones (tests/golden/evaluate.json). lab/tracker.py reads these lines,
so their format matters as much as their numbers.

  league     the LEAGUE table and SUMMARY lines from a fixed set of made-up results (every team, both sides)
  h2h        the MATCH and H2H lines from made-up head-to-head results
  behaviour  4 behaviour matches of RL Team 5 against the rule bots: every printed line (behaviour, HEAT, scores, SCOUT)
  teams      rl/teams_info.json still matches the teams in data/teams

  python3 tests/test_evaluate.py [--update]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rl"))
import evaluate as ev                     # noqa: E402
from tests import golden                  # noqa: E402

MODEL = "res://data/models/rl_5v5_arena_v5.json"


def made_up(k):
    """A made-up score (gf, ga) for match k."""
    h = (k * 7 + 3) % 11
    return h % 4, (h * 5 + k) % 3


def league():
    ids, info = ev.league_teams()
    matches = [(tid, side, 1000 + 2 * i + side) + made_up(2 * i + side) for i, tid in enumerate(ids) for side in (0, 1)]
    _, table = ev.league_report(MODEL, ids, info, matches, 0.0)
    return table


def h2h():
    return ev.h2h_report("RL Team 4", [(k % 2, 500 + k) + made_up(k) for k in range(10)])


def behaviour():
    results = [ev._behaviour_match((i, {"model": ev.res_abs(MODEL)}, False)) for i in range(4)]
    return ev.behaviour_report(results)


def teams_info_ok():
    ids, info = ev.league_teams()
    ok = open(os.path.join(ROOT, "rl", "teams_info.json")).read() == ev._godot_json([info[i] for i in ids])
    print("%-24s %s" % ("teams_info.json", "OK" if ok else "FAIL  differs from data/teams (rl/evaluate.py writes it)"))
    return ok


def main():
    update = "--update" in sys.argv
    ok = golden.check("evaluate_league", league(), update, "league")
    ok &= golden.check("evaluate_h2h", h2h(), update, "h2h")
    ok &= golden.check("evaluate_behaviour", behaviour(), update, "behaviour")
    ok &= teams_info_ok()
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
