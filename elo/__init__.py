"""Ratings: Elo for every player and team, per team size (1v1 ... 5v5), from matches played on this machine.

  db.py        the local SQLite database (local/elo.db, never pushed): every match result, rating snapshots
  roster.py    who is rated: players, mixed teams and training checkpoints, with the files their results depend on
  model.py     the fit: player strengths and a small team bonus per size, a pinned scale, a Poisson goals model
  schedule.py  which matches to play next (placement first, then the most informative)
  play.py      plays a batch of matches on a pool of niced workers
  api.py       cached ratings and the ranking tables the game and the Lab show
  __main__.py  python3 -m elo init | round | rank | status | roster | refine | archive

docs/ratings.md explains the model, the storage and how to read the numbers. Every machine has its own database and its own
ratings: results are not shared (they are not comparable across machines or after a behaviour change: see ENGINE)."""
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.environ.get("SOCCER_LOCAL") or os.path.join(ROOT, "local")     # everything that belongs to this machine only (git-ignored)

SIZES = (1, 2, 3, 4, 5)           # team sizes that are rated; the pitch is always the arena (5v5 large)
PITCH = "arena"
DURATION = 90.0                   # seconds of a rated match
MAX_TICKS = int(DURATION * 60 * 4)    # the clock stops until a kickoff is taken: a team that never touches the ball would hang
PLACEMENT = 6                     # games before an entry counts as placed

# Bump when the behaviour of the game changes on purpose (the same moment the golden tests in tests/golden/ are re-recorded):
# results played with another ENGINE no longer count (they stay in the database).
ENGINE = 2

BASE = 1500.0                     # the average rule-based player of a size is pinned here
PRIOR_SD = 400.0                  # Elo: prior of a player's strength (keeps a player with few games finite)
BONUS_SD = 50.0                   # Elo: prior of a team's bonus over the average of its players (synergy): close to 0 unless results show it
K = 400.0 / math.log(10.0)        # Elo points per unit of the logistic scale
GOAL_PRIOR_SD = 1.0               # attack / defence strengths ~ N(0, 1) on the log scale
PROTOCOL = "arena/d%d/engine%d" % (DURATION, ENGINE)
