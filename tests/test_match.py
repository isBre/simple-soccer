"""The match core (soccer/) against stored matches (tests/golden/match_<name>.json).

Plays every match of tests/scenarios.json (all sizes, every pitch plus one with extra walls, net teams, mixed line-ups of
rule, Opus and net players, a net that does not fit the size, a scripted human in single and team control, golden-goal
overtime, score limit) with the real AI and compares: the score, ball position and ball speed every second (so a FAIL says
when the match started to differ) and the complete result (events, team and player statistics).

  python3 tests/test_match.py [--update] [scenario names...]"""
import cmath
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from soccer.data import Pitch                                   # noqa: E402
from soccer.match import ENDED, Match, make_config             # noqa: E402
from tests import golden                                       # noqa: E402

MAX_TICKS = 60 * 60 * 10


def build(sc_def, pitches):
    pid = sc_def["pitch"]
    cfg = make_config(sc_def["home"], sc_def["away"], pid if pid not in pitches else "arena", int(sc_def["size"]),
                      float(sc_def["duration"]), int(sc_def["seed"]))
    if pid in pitches:
        cfg.pitch = Pitch(pitches[pid])
    cfg.control = int(sc_def.get("control", 0))
    cfg.human_team = int(sc_def.get("human_team", 0))
    cfg.auto_switch = bool(sc_def.get("auto_switch", False))
    cfg.allow_draw = bool(sc_def.get("allow_draw", True))
    cfg.score_limit = int(sc_def.get("score_limit", 0))
    cfg.net_temperature = float(sc_def.get("temperature", 1.0))
    if sc_def.get("net"):                                        # one net for the home team instead of its line-up
        cfg.nets[0] = {"model": os.path.join(ROOT, sc_def["net"])}
    return Match(cfg)


def scripted_human(m):
    """The human's keys, a fixed function of the tick: a new direction every 40 ticks, a short kick every 37."""
    m.set_human_input(cmath.exp(1j * ((m.tick // 40) * 2.399963)), m.tick % 37 < 3)
    if m.cfg.control == 2 and not m.cfg.auto_switch and m.tick % 240 == 0:
        m.switch_controlled()


def play(sc_def, pitches):
    m = build(sc_def, pitches)
    trace = []
    while m.state != ENDED and m.tick < MAX_TICKS:
        if m.cfg.control:
            scripted_human(m)
        m.step()
        if m.tick % 60 == 0:
            trace.append([m.tick, list(m.scores), m.ball.pos, abs(m.ball.vel)])
    if m.state != ENDED:
        m._end_match()
    return {"ticks": m.tick, "trace": trace, "result": json.loads(json.dumps(m.make_result()))}


def first_divergence(name, got):
    """The first second at which the trace differs from the stored one (for the FAIL message)."""
    try:
        ref = json.load(open(os.path.join(golden.GOLDEN, "match_" + name + ".json")))["data"]["trace"]
    except (OSError, ValueError, KeyError):
        return None
    got = golden.rounded(got["trace"])
    for a, b in zip(got, ref):
        if golden.diff(a, b):
            return a[0]
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update" in sys.argv
    spec = json.load(open(os.path.join(ROOT, "tests", "scenarios.json")))
    todo = [s for s in spec["scenarios"] if not args or s["name"] in args]
    ok_all = True
    for s in todo:
        got = play(s, spec["pitches"])
        ok = golden.check("match_" + s["name"], got, update, s["name"], show=3)
        if not ok:
            t = first_divergence(s["name"], got)
            if t is not None:
                print("      first difference in the trace at tick %d" % t)
        ok_all &= ok
    print("TOTAL %d matches -> %s" % (len(todo), "PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
