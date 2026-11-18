"""Python's training environment (rl/env.py) against Godot's (rl/rl_env.gd), step by step.

Godot runs the environments of tests/env_scenarios.json with random actions and records every step
(tests/reference/record_env.gd). For every step this test loads Godot's match state and the environment's bookkeeping into
Python, plays the same actions with the same AI inputs, and compares: the reward, every individual reward term, done,
outcome, the bookkeeping after the step, the whole match state after it, the observations. Every reset (episode start,
random layouts, ghosts, kickoffs) is compared too: Python resets from Godot's random generator state and must build the
same match.

  python3 tests/test_env.py [--record] [names...]       ($SOCCER_REF, $SOCCER_REC as for tests/test_match.py)"""
import json
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rl"))
from env import RLEnv                                          # noqa: E402
from tests import state_codec as sc                            # noqa: E402
from tests.godot_run import install_reference, run_scene       # noqa: E402
from tests.test_match import TOL_POS, TOL_STAT                 # noqa: E402

REC = os.environ.get("SOCCER_REC") or os.path.join(tempfile.gettempdir(), "soccer_recordings")
STAT_FIELDS = {"pass_value", "xg", "xa", "save_xg", "conceded_xg", "carry_dist", "distance", "rating", "pending_shot_xg", "last_shot_xg"}


class TapAI:
    """Gives the bots that are due the inputs Godot's AI gave them, tick by tick (from the recorded taps)."""

    def __init__(self):
        self.taps = []

    def decide(self, m, update):
        tap = self.taps.pop(0)
        assert tap["tick"] == m.tick, ("AI tick", tap["tick"], m.tick)
        k = 0
        for t in (0, 1):
            for p in m.team_lists[t]:
                if p.bot and not p.is_human and (m.tick + p.slot) % 2 == 0:
                    d = tap["inputs"][k]
                    p.input_dir, p.input_kick, p.kick_intent = complex(d[0], d[1]), bool(d[2]), str(d[3])
                k += 1
        m.keeper_uid = [int(x) for x in tap["keepers"]]


def load_env(e, d):
    e.steps, e.ep_return, e.prev_pot = int(d["steps"]), float(d["ep_return"]), float(d["prev_pot"])
    e.prev_scores, e.prev_playing = [int(x) for x in d["prev_scores"]], bool(d["prev_playing"])
    e.prev_pass = [int(x) for x in d["prev_pass"][:4]] + [float(d["prev_pass"][4])]
    e.coop_used, e.xg_used, e.def_used, e.prev_opp_xg = (float(d[k]) for k in ("coop_used", "xg_used", "def_used", "prev_opp_xg"))
    e.rng.state = (int(d["rng"][1]) << 32) | int(d["rng"][0])
    e.prev_ps = {int(k): [int(v[0]), int(v[1]), int(v[2]), int(v[3]), float(v[4]), int(v[5])] for k, v in d["prev_ps"].items()}
    e.prev_def = {int(k): [int(v[0]), float(v[1])] for k, v in d["prev_def"].items()}
    e.prev_dir = {int(k): complex(v[0], v[1]) for k, v in d["prev_dir"].items()}
    e.wall_streak = {int(k): int(v) for k, v in d["wall_streak"].items()}
    e.term_sums = {k: float(v) for k, v in d["term_sums"].items()}
    e.term_steps = int(d["term_steps"])


def env_state(e):
    return {"steps": e.steps, "ep_return": e.ep_return, "prev_pot": e.prev_pot, "prev_scores": e.prev_scores,
            "prev_playing": e.prev_playing, "prev_pass": e.prev_pass, "coop_used": e.coop_used, "xg_used": e.xg_used,
            "def_used": e.def_used, "prev_opp_xg": e.prev_opp_xg, "rng": [e.rng.state & 0xffffffff, e.rng.state >> 32],
            "prev_ps": {str(k): v for k, v in e.prev_ps.items()}, "prev_def": {str(k): v for k, v in e.prev_def.items()},
            "prev_dir": {str(k): [v.real, v.imag] for k, v in e.prev_dir.items()},
            "wall_streak": {str(k): v for k, v in e.wall_streak.items()}, "term_sums": e.term_sums, "term_steps": e.term_steps,
            "agents": [p.uid for p in e.agents], "opp_agents": [p.uid for p in e.opp_agents], "used_selfplay": e.used_selfplay,
            "movers": len(e.sim.movers), "players": [p.uid for p in e.sim.players]}


def diff(a, b, path="", tol=1e-4):
    """Differences between two JSON-like values (numbers within tol, relative for large ones)."""
    out = []
    if isinstance(b, dict):
        a = a if isinstance(a, dict) else {}
        for k in set(a) | set(b):
            if k not in a or k not in b:
                if not (isinstance(b.get(k), (int, float)) and abs(float(b.get(k, 0.0) or 0.0)) < 1e-12) and not (
                        isinstance(a.get(k), (int, float)) and abs(float(a.get(k, 0.0) or 0.0)) < 1e-12):
                    out.append((path + "." + k, a.get(k), b.get(k)))
                continue
            out += diff(a[k], b[k], path + "." + k, tol)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            return [(path, "len %s" % (len(a) if isinstance(a, list) else a), "len %d" % len(b))]
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, "%s[%d]" % (path, i), tol)
    elif isinstance(b, bool) or isinstance(a, bool):
        if bool(a) != bool(b):
            out.append((path, a, b))
    elif isinstance(b, (int, float)):
        if abs(float(a) - float(b)) > tol * max(1.0, abs(float(b))):
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def boundary_contacts(m, eps=1e-5):
    """Pairs of discs exactly at touching distance (|distance - sum of radii| < eps): a contact decided at the limit of
    float precision, which Godot (32-bit positions) and Python (64-bit) may decide differently."""
    out = []
    discs = m.movers
    for i, a in enumerate(discs):
        for b in discs[i + 1:] + m.statics:
            if abs(abs(a.pos - b.pos) - (a.radius + b.radius)) < eps:
                out.append((getattr(a, "uid", "ball"), getattr(b, "uid", "post")))
    return out


def compare_state(m, vec, names, where, bad):
    for fname, a, b in zip(names, sc.export_state(m), vec):
        if sc.is_float(fname):
            tol = TOL_STAT if fname.split(".")[-1] in STAT_FIELDS else TOL_POS
            if abs(a - b) > tol * max(1.0, abs(b) * 1e-3):
                bad.append((where, fname, a, b))
        elif a != b:
            bad.append((where, fname, a, b))


def replay(sc_def):
    name = sc_def["name"]
    recs = [json.loads(l) for l in open(os.path.join(REC, "env_" + name + ".jsonl"))]
    raw = open(os.path.join(REC, "env_" + name + ".bin"), "rb").read()
    e = RLEnv()
    c = dict(sc_def["cfg"], seed=4242)
    e.configure(c)
    if "selfplay_net" in sc_def:
        e.opp_net = {"model": os.path.join(ROOT, sc_def["selfplay_net"][6:])}
    st = {"steps": 0, "resets": 0, "bad": [], "max_r": 0.0, "flips": []}
    pos = [0]
    names_box = [None]

    def next_vec():
        n = len(names_box[0])
        v = struct.unpack_from("<%dd" % n, raw, pos[0])
        pos[0] += 8 * n
        return v

    def do_reset(pre_rng, want_env, want_obs, where):
        e.rng.state = (int(pre_rng[1]) << 32) | int(pre_rng[0])
        e.reset()
        e.sim.ai = TapAI()
        names_box[0] = sc.names(len(e.sim.team_lists[0]) + len(e.sim.team_lists[1]))
        compare_state(e.sim, next_vec(), names_box[0], where, st["bad"])
        st["bad"] += [(where, "env") + d for d in diff(env_state(e), want_env)]
        st["resets"] += 1

    first = recs[0]
    do_reset(first["pre_rng"], first["env"], first["obs"], "reset0")
    st["bad"] += [("reset0", "obs") + d for d in diff(e.observe(), first["obs"])]
    for i, r in enumerate(recs[1:]):
        before = next_vec()
        sc.import_state(e.sim, before)
        load_env(e, r["env"])
        e.sim.ai.taps = list(r["taps"])
        n_bad = len(st["bad"])
        rew, done, outcome, indiv = e.step(r["actions"])
        contacts = boundary_contacts(e.sim)
        st["steps"] += 1
        where = "step %d" % i
        if abs(rew - r["r"]) > 1e-5 * max(1.0, abs(r["r"])):
            st["bad"].append((where, "reward", rew, r["r"]))
        st["max_r"] = max(st["max_r"], abs(rew - r["r"]))
        if bool(done) != bool(r["done"]) or outcome != r["outcome"]:
            st["bad"].append((where, "done/outcome", (done, outcome), (r["done"], r["outcome"])))
        st["bad"] += [(where, "indiv") + d for d in diff(indiv, r["indiv"], tol=1e-5)]
        st["bad"] += [(where, "env after") + d for d in diff(env_state(e), r["after"])]
        compare_state(e.sim, next_vec(), names_box[0], where + " after", st["bad"])
        if r["done"]:
            do_reset(r["pre_rng"], r["reset_env"], r["obs"], where + " reset")
        st["bad"] += [(where, "obs") + d for d in diff(e.observe(), r["obs"])]
        if len(st["bad"]) > n_bad and contacts:          # a contact exactly at touching distance: a float precision flip
            st["flips"].append((where, contacts, len(st["bad"]) - n_bad))
            del st["bad"][n_bad:]
    assert pos[0] == len(raw), "recording not fully read"
    return st


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    spec = json.load(open(os.path.join(ROOT, "tests", "env_scenarios.json")))
    todo = [s for s in spec["scenarios"] if not args or s["name"] in args]
    if "--record" in sys.argv:
        ref = os.environ["SOCCER_REF"]
        install_reference(ref)
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "reference", "ref_tap.py"), ref], check=True)
        tmp = os.path.join(REC, "_env")
        os.makedirs(tmp, exist_ok=True)
        run_scene("res://tests/godot/record_env.tscn", "RECORDED", [tmp] + [s["name"] for s in todo], timeout=7200, project=ref)
        for s in todo:
            for ext in ("bin", "jsonl"):
                os.replace(os.path.join(tmp, "%s.%s" % (s["name"], ext)), os.path.join(REC, "env_%s.%s" % (s["name"], ext)))
    ok_all = True
    tot_steps = tot_resets = 0
    for s in todo:
        st = replay(s)
        ok = not st["bad"]
        ok_all &= ok
        tot_steps += st["steps"]
        tot_resets += st["resets"]
        print("%-18s %s  steps %5d  resets %3d  max reward diff %.1e  mismatches %d  precision flips %d" % (
              s["name"], "OK  " if ok else "FAIL", st["steps"], st["resets"], st["max_r"], len(st["bad"]), len(st["flips"])))
        for b in st["bad"][:8]:
            print("      ", b)
        for f in st["flips"]:
            print("       precision flip at %s: discs %s exactly at touching distance (%d values differ after it)" % f)
    print("TOTAL %d steps, %d resets -> %s" % (tot_steps, tot_resets, "PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
