"""The evaluation reports (rl/evaluate.py) against stored ones (tests/golden/evaluate_*.json). lab/tracker.py reads these lines,
so their format matters as much as their numbers.

  league     the LEAGUE table and SUMMARY lines from a fixed set of made-up results (every team, both sides)
  h2h        the MATCH and H2H lines from made-up head-to-head results
  behaviour  4 behaviour matches of RL Team 5 against the rule bots: every printed line (behaviour, HEAT, scores, SCOUT)
  teams      rl/teams_info.json still matches the teams in data/teams
  record     the JSON record rl/eval_checkpoint.py builds from the RESULT lines equals what lab/tracker.py parse_eval reads from
             the text of the same evaluation (the text and the JSON can never drift apart)

  python3 tests/test_evaluate.py [--update]"""
import json
import os
import sys
import tempfile

from lab import tracker
from rl import eval_checkpoint as ec
from rl import evaluate as ev
import golden

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL = "res://data/models/rl_5v5_arena_v5.json"


def made_up(k):
    """A made-up score (gf, ga) for match k."""
    h = (k * 7 + 3) % 11
    return h % 4, (h * 5 + k) % 3


def league(seed0=1000):
    """(MATCH lines, table + SUMMARY lines, RESULT dict) of a league with made-up results."""
    ids, info = ev.league_teams()
    matches = [(tid, side, seed0 + 2 * i + side) + made_up(2 * i + side + seed0 - 1000) for i, tid in enumerate(ids) for side in (0, 1)]
    summary = {}
    lines, table = ev.league_report(MODEL, ids, info, matches, 0.0, summary)
    return lines, table, {"part": "league", "summary": summary, "matches": [list(m) for m in matches]}


def h2h(name="RL Team 4"):
    matches = [(k % 2, 500 + k) + made_up(k + len(name) - len("RL Team 4")) for k in range(10)]
    summary = {}
    lines = ev.h2h_report(name, matches, summary)
    return lines, {"part": "h2h", "name": name, "summary": summary, "matches": [list(m) for m in matches]}


def behaviour():
    results = [ev._behaviour_match((i, {"model": ev.res_abs(MODEL)}, False)) for i in range(4)]
    summary = {}
    lines = ev.behaviour_report(results, summary)
    return lines, {"part": "behaviour", **summary}


def record_ok(beh_lines, beh_res):
    """An evaluation text put together like rl/eval_checkpoint.py does, parsed by lab/tracker.py, against record()."""
    lg, tab, lres = league()
    glg, gtab, gres = league(3000)
    h4, h4res = h2h()
    h5, h5res = h2h("RL Team 5")
    text = (["EVAL models/x.json | mode full | league games/side 1 | duration 90s | h2h games/side 5", "# league"] + lg + tab +
            ["# behaviour"] + beh_lines + ["# greedy (best move instead of sampling)"] + ["greedy " + l for l in glg + gtab] +
            ["# head to head"] + h4 + h5 + ["DONE 12"])
    parts = [("league", lres), ("behaviour", beh_res), ("greedy", gres), ("h2h", h4res), ("h2h", h5res)]
    rec = ec.record("models/x.json", "full", 1, 90.0, 5, parts, 12.4)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(text) + "\n")
    try:
        parsed = tracker.parse_eval(f.name)
    finally:
        os.remove(f.name)
    bad = golden.diff(json.loads(json.dumps(rec)), parsed, rel=0)
    print("%-24s %s" % ("record", "OK" if not bad else "FAIL  JSON record and parsed text differ" +
                        "".join("\n      %s: json %r, text %r" % d for d in bad[:6])))
    return not bad


def teams_info_ok():
    ids, info = ev.league_teams()
    ok = open(os.path.join(ROOT, "rl", "teams_info.json")).read() == ev._godot_json([info[i] for i in ids])
    print("%-24s %s" % ("teams_info.json", "OK" if ok else "FAIL  differs from data/teams (rl/evaluate.py writes it)"))
    return ok


def main():
    update = "--update" in sys.argv
    _, table, lres = league()
    h_lines, hres = h2h()
    b_lines, bres = behaviour()
    ok = golden.check("evaluate_league", table, update, "league")
    ok &= golden.check("evaluate_h2h", h_lines, update, "h2h")
    ok &= golden.check("evaluate_behaviour", b_lines, update, "behaviour")
    ok &= teams_info_ok()
    ok &= record_ok(b_lines, bres)
    print("TOTAL ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
