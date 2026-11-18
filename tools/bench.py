"""Speed of the match core: rule-vs-rule matches (sim ticks/s) and the RL training environment (steps/s, rule opponents).
  python3 tools/bench.py"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rl"))
from soccer.match import Match, make_config     # noqa: E402
from env import RLEnv                           # noqa: E402

t0, ticks = time.time(), 0
ids = ["aurora", "cobalt", "granite", "tide"]
for i in range(4):
    m = Match(make_config(ids[i], ids[(i + 1) % 4], "arena", 5, 60.0, 100 + i))
    m.run_to_end()
    ticks += m.tick
dt = time.time() - t0
print("rules 5v5: %d ticks in %.2f s = %.0f ticks/s (%.0fx real time)" % (ticks, dt, ticks / dt, ticks / dt / 60))
e = RLEnv()
e.configure({"pitch": "arena", "size": 5, "n_active": 5, "with_keeper": True, "opp": "aurora,cobalt,granite", "match_mode": True,
             "duration": 90.0, "obs": "team", "seed": 3, "own_team": "owls"})
e.reset()
import random
rng = random.Random(5)
t0, n = time.time(), 2000
for s in range(n):
    r = e.step([x for _ in range(5) for x in (rng.randrange(9), int(rng.random() < 0.2))])
    e.observe()
    if r[1]:
        e.reset()
dt = time.time() - t0
print("training env: %d steps in %.2f s = %.0f steps/s (one process)" % (n, dt, n / dt))
