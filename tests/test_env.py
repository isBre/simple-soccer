"""The training environment (rl/env.py) against stored runs (tests/golden/env_<name>.json).

Runs every environment of tests/env_scenarios.json (every reward term, random layouts, curricula, self-play with a net,
external opponents) for its number of steps with seeded random actions and compares: the reward of every step, every
episode's end (step, outcome, return), every reward term's total, and the observation after each reset.

  python3 tests/test_env.py [--update] [names...]"""
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rl"))
from env import RLEnv                     # noqa: E402
from soccer.match import res_path         # noqa: E402
from tests import golden                  # noqa: E402


def run(sc_def):
    e = RLEnv()
    e.configure(dict(sc_def["cfg"], seed=4242))
    if "selfplay_net" in sc_def:
        e.opp_net = {"model": res_path(sc_def["selfplay_net"])}
    rnd = random.Random(7)
    e.reset()
    out = {"rewards": [], "episodes": [], "reset_obs": [e.observe()[:24]]}
    for i in range(int(sc_def["steps"])):
        actions = [x for _ in range(e.n_agents()) for x in (rnd.randrange(9), int(rnd.random() < 0.15))]
        r, done, outcome, _ = e.step(actions)
        out["rewards"].append(r)
        if done:
            out["episodes"].append([i, outcome, e.ep_return])
            e.reset()
            out["reset_obs"].append(e.observe()[:24])
    out["terms"] = dict(sorted(e.term_sums.items()))
    out["obs_dim"] = e.obs_dim()
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update" in sys.argv
    spec = json.load(open(os.path.join(ROOT, "tests", "env_scenarios.json")))
    todo = [s for s in spec["scenarios"] if not args or s["name"] in args]
    ok_all = True
    for s in todo:
        ok_all &= golden.check("env_" + s["name"], run(s), update, s["name"], show=4)
    print("TOTAL %d environments -> %s" % (len(todo), "PASS" if ok_all else "FAIL"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
