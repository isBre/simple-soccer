"""Python's match core (soccer.match) against Godot's MatchSim, tick by tick.

Godot records every tick of the matches in tests/scenarios.json (tests/reference/record_match.gd). For every tick t this test
loads Godot's complete state at t into a Python match, gives the bots the inputs Godot's AI gave them at that tick, steps
once and compares the whole state with Godot's at t+1: positions, velocities, inputs, the ball's history, every counter of
every player, possession, timers, kickoffs, goals, the random generator. Discrete values must be equal; continuous ones
may differ by float32 rounding only (Godot keeps positions in 32-bit floats, Python in 64-bit).

  python3 tests/test_match.py [--record] [scenario names...]
--record runs Godot first. The reference is a checkout of the Godot implementation ($SOCCER_REF, a project directory that
still has scripts/core/match_sim.gd; the recorders are copied in); recordings go to $SOCCER_REC or the system temp dir."""
import json
import math
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from soccer.data import Pitch                                   # noqa: E402
from soccer.match import ENDED, Match, make_config             # noqa: E402
from tests import state_codec as sc                            # noqa: E402
from tests.godot_run import install_reference, run_scene       # noqa: E402

REC = os.environ.get("SOCCER_REC") or os.path.join(tempfile.gettempdir(), "soccer_recordings")
TOL_POS = 2e-3          # px and px/tick: float32 rounding of one tick (values up to ~600)
TOL_STAT = 1e-4         # accumulated stats (xg, distance, pass value...)


class ReplayAI:
    """Gives the bots that are due exactly the inputs Godot's AI gave them (read from Godot's next state)."""

    def __init__(self):
        self.next_inputs = None
        self.next_keepers = None

    def decide(self, m, update):
        k = 0
        for t in (0, 1):
            for p in m.team_lists[t]:
                if p.bot and not p.is_human and (m.tick + p.slot) % 2 == 0:
                    p.input_dir, p.input_kick, p.kick_intent = self.next_inputs[k]
                k += 1
        m.keeper_uid = list(self.next_keepers)


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
    cfg.overtime = float(sc_def.get("overtime", 60.0))
    cfg.score_limit = int(sc_def.get("score_limit", 0))
    cfg.net_temperature = float(sc_def.get("temperature", 1.0))
    return Match(cfg, ai=False)


def read_vectors(path, n_values):
    raw = open(path, "rb").read()
    n = len(raw) // (8 * n_values)
    assert n * 8 * n_values == len(raw), "vector size mismatch: %s" % path
    return [struct.unpack_from("<%dd" % n_values, raw, k * 8 * n_values) for k in range(n)]


def close(a, b, tol):
    return abs(a - b) <= tol * max(1.0, abs(b) * 1e-3) if tol else a == b


def compare_event(ev_py, ev_go):
    bad = []
    for k, v in ev_go.items():
        pv = ev_py.get(k)
        if isinstance(v, float) or isinstance(pv, float):
            if abs(float(pv) - float(v)) > 1e-3:
                bad.append((k, pv, v))
        elif pv != v and not (isinstance(v, (int, float)) and float(pv) == float(v)):
            bad.append((k, pv, v))
    return bad


def replay(name, spec):
    sc_def = next(s for s in spec["scenarios"] if s["name"] == name)
    meta = json.load(open(os.path.join(REC, name + ".json")))
    m = build(sc_def, spec["pitches"])
    names = sc.names(len(m.team_lists[0]) + len(m.team_lists[1]))
    vecs = read_vectors(os.path.join(REC, name + ".bin"), len(names))
    ai = ReplayAI()
    m.ai = ai
    stats = {"ticks": 0, "values": 0, "discrete_bad": [], "max_pos": 0.0, "max_stat": 0.0, "events": 0, "event_bad": []}
    n_players = len(m.team_lists[0]) + len(m.team_lists[1])
    for t in range(len(vecs) - 1):
        cur, nxt = vecs[t], vecs[t + 1]
        sc.import_state(m, cur, meta["events"], meta["kickoff_waits"])
        ai.next_inputs = sc.player_inputs(nxt, n_players)
        nd = dict(zip(names, nxt))
        ai.next_keepers = [int(nd["keeper0"]), int(nd["keeper1"])]
        n_ev = len(m.events)
        m.step()
        # between two ticks the recorder set the scripted human's next input and, in TEAM mode, sometimes switched player
        m.set_human_input(complex(nd["human_dir_x"], nd["human_dir_y"]), bool(nd["human_kick"]))
        nxt_ctrl = m.by_uid.get(int(nd["controlled"]))
        if nxt_ctrl is not m.controlled:
            m.set_controlled(nxt_ctrl)
        got = sc.export_state(m)
        stats["ticks"] += 1
        for fname, a, b in zip(names, got, nxt):
            stats["values"] += 1
            if sc.is_float(fname):
                tol = TOL_STAT if fname.split(".")[-1] in ("pass_value", "xg", "xa", "save_xg", "conceded_xg", "carry_dist",
                                                         "distance", "rating", "pending_shot_xg", "last_shot_xg") else TOL_POS
                diff = abs(a - b)
                key = "max_stat" if tol == TOL_STAT else "max_pos"
                stats[key] = max(stats[key], diff if not math.isnan(diff) else math.inf)
                if diff > tol * max(1.0, abs(b) * 1e-3):
                    stats["discrete_bad"].append((t, fname, a, b))
            elif a != b:
                stats["discrete_bad"].append((t, fname, a, b))
        if len(m.events) > n_ev:
            stats["events"] += 1
            bad = compare_event(m.events[-1], meta["events"][len(m.events) - 1])
            if bad:
                stats["event_bad"].append((t, bad))
        if len(m.kickoff_waits) and m.kickoff_waits[-1] != meta["kickoff_waits"][len(m.kickoff_waits) - 1]:
            stats["discrete_bad"].append((t, "kickoff_wait", m.kickoff_waits[-1], meta["kickoff_waits"][len(m.kickoff_waits) - 1]))
    # the result: load Godot's final state and build the result dictionary in Python
    sc.import_state(m, vecs[-1], meta["events"], meta["kickoff_waits"])
    res_py, res_go = json.loads(json.dumps(m.make_result())), meta["result"]
    stats["result_bad"] = diff_result(res_py, res_go)
    stats["ended"] = m.state == ENDED
    return stats


def diff_result(a, b, path=""):
    out = []
    if isinstance(b, dict):
        for k in b:
            out += diff_result(a.get(k) if isinstance(a, dict) else None, b[k], path + "." + k)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            return [(path, a, b)]
        for k, (x, y) in enumerate(zip(a, b)):
            out += diff_result(x, y, path + "[%d]" % k)
    elif isinstance(b, (int, float)) and isinstance(a, (int, float)) and not isinstance(b, bool):
        if abs(float(a) - float(b)) > 1e-3 * max(1.0, abs(float(b)) * 1e-3):
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    spec = json.load(open(os.path.join(ROOT, "tests", "scenarios.json")))
    names = args or [s["name"] for s in spec["scenarios"]]
    if "--record" in sys.argv:
        os.makedirs(REC, exist_ok=True)
        install_reference(os.environ["SOCCER_REF"])
        print(run_scene("res://tests/godot/record_match.tscn", "RECORDED ", [REC] + names, timeout=7200,
                        project=os.environ.get("SOCCER_REF")).strip(), "recorded")
    total = {"ticks": 0, "values": 0, "bad": 0}
    ok_all = True
    for name in names:
        s = replay(name, spec)
        total["ticks"] += s["ticks"]
        total["values"] += s["values"]
        total["bad"] += len(s["discrete_bad"])
        ok = not s["discrete_bad"] and not s["event_bad"] and not s["result_bad"]
        ok_all &= ok
        print("%-22s %s  ticks %5d  goals %d  max pos diff %.1e  max stat diff %.1e  mismatches %d  events bad %d  result bad %d"
              % (name, "OK  " if ok else "FAIL", s["ticks"], s["events"], s["max_pos"], s["max_stat"], len(s["discrete_bad"]),
                 len(s["event_bad"]), len(s["result_bad"])))
        for b in (s["discrete_bad"][:5] + s["event_bad"][:3] + s["result_bad"][:5]):
            print("      ", b)
    print("TOTAL %d ticks, %d values compared, %d mismatches -> %s" % (total["ticks"], total["values"], total["bad"],
                                                                      "PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
