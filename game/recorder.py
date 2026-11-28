"""Records the user's play in the browser game as a dataset for imitation learning (docs/imitation_plan.md, Phase 1).

While a match with a human player is in play, every AI_PERIOD (2) ticks, the same rate as the bots and the RL nets decide, one row:
  obs        features_team of the player the human controls (46 numbers, soccer/ai/obs.py): exactly a net's input
  state      the raw match: all players (uid order: team 0 slots, then team 1 slots) and the ball, x, y, vx, vy each, in world
             coordinates (team 0 attacks right). Any other observation can be recomputed from it later (il/human_data.py)
  ctrl       uid of the controlled player (changes in team control)
  move       the human's direction as one of the 9 net moves (soccer.core.public.DIRS, 0 = stand), in the player's own frame
             (+x towards the opponent goal), so it is directly a net's action label
  kick       kick key held (0/1)
  dir        the raw direction the page sent (world frame, unit length or 0)
  tick, time_left, score (2), kickoff (0/1), speed (the page's 1/2/4/8 at that moment)
Rows are taken from the state BEFORE the tick in which the input is applied; the human's reaction lag is NOT corrected here
(the training code shifts the labels).

One file per match: data/human/<UTC time>_<home>-<away>.npz (numpy, compressed, no pickles: meta is a JSON string), written when
the match ends, or when the player quits / closes the page after at least MIN_ROWS rows (meta "complete": false). A puzzle round
(game/session.py) is kept from 30 rows (1 s): it is short by design, and ends at the first goal.
$SOCCER_HUMAN_DIR overrides the folder (tests)."""
import datetime as dt
import json
import os
import secrets

import numpy as np

from soccer.ai.obs import features_team
from soccer.core.view import View
from soccer.core.public import AI_PERIOD, DIRS, PLAYING

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 1
OBS = "team46"
MIN_ROWS = 300                    # 10 s of play: shorter aborted matches are not worth a file
_UNIT = [d / abs(d) if abs(d) > 0 else 0j for d in DIRS]


def data_dir():
    return os.environ.get("SOCCER_HUMAN_DIR") or os.path.join(ROOT, "data", "human")


def move_index(d: complex, attack: float) -> int:
    """The net move (0..8) closest to direction d (world frame) for a player attacking towards `attack` (+1 right, -1 left)."""
    if abs(d) < 1e-9:
        return 0
    own = complex(d.real * attack, d.imag)
    return max(range(1, 9), key=lambda k: own.real * _UNIT[k].real + own.imag * _UNIT[k].imag)


class Recorder:
    def __init__(self, g, setup, min_rows=MIN_ROWS):
        self.g, self.m = g, g.match          # g: soccer.game.Game
        m = self.m
        self.min_rows = min_rows
        self.setup = dict(setup)
        self.started = dt.datetime.now(dt.timezone.utc)
        self.rows = {k: [] for k in ("obs", "state", "ctrl", "move", "kick", "dir", "tick", "time_left", "score", "kickoff", "speed")}
        self.players = [q for t in (0, 1) for q in m.team_lists[t]]
        self.views = {}                     # team -> its public view: the observation is built from it, as a net's is
        self.saved = None

    def __len__(self):
        return len(self.rows["tick"])

    def due(self):
        """True when the coming step is a decision tick and the human plays (call before Match.step())."""
        m = self.m
        return (m.tick + 1) % AI_PERIOD == 0 and m.state == PLAYING and self.g.people.controlled is not None

    def sample(self, d: complex, kick: bool, speed: int):
        """One row: the state now and the input the human holds for the coming step."""
        m, p, r = self.m, self.g.people.controlled, self.rows
        st = []
        for q in self.players:
            st += (q.pos.real, q.pos.imag, q.vel.real, q.vel.imag)
        st += (m.ball.pos.real, m.ball.pos.imag, m.ball.vel.real, m.ball.vel.imag)
        if p.team not in self.views:
            self.views[p.team] = View(m, p.team)
        v = self.views[p.team].refresh(m)
        r["obs"].append(features_team(v, v.bodies[p.uid]))
        r["state"].append(st)
        r["ctrl"].append(p.uid)
        r["move"].append(move_index(d, m.attack_dir(p.team)))
        r["kick"].append(1 if kick else 0)
        r["dir"].append((d.real, d.imag))
        r["tick"].append(m.tick)
        r["time_left"].append(m.time_left)
        r["score"].append(tuple(m.scores))
        r["kickoff"].append(1 if m.kickoff_active else 0)
        r["speed"].append(speed)

    def save(self, result=None):
        """Writes the file (once). Returns its path, or None when there is too little to keep."""
        if self.saved or len(self) < self.min_rows:
            return self.saved
        m, cfg = self.m, self.g.cfg
        pd = m.pitch
        ctrl = self.rows["ctrl"]
        meta = {
            "version": VERSION, "obs": OBS, "decision_ticks": AI_PERIOD, "rows": len(self),
            "started": self.started.isoformat(timespec="seconds"),
            "saved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "complete": result is not None,
            "setup": self.setup,
            "teams": [{"id": cfg.teams[t].id, "name": cfg.teams[t].name, "league": cfg.teams[t].league} for t in (0, 1)],
            "human_team": cfg.human_team, "control": {1: "single", 2: "team"}.get(cfg.control, "none"),
            "players": [{"uid": q.uid, "team": q.team, "slot": q.slot, "line": q.line, "name": q.label.name, "player": q.label.id,
                         "rows": ctrl.count(q.uid)} for q in self.players],
            "pitch": {"id": pd.id, "half_w": pd.half_w, "half_h": pd.half_h, "goal_half": pd.goal_half, "out_x": pd.out_x,
                      "out_y": pd.out_y},
            "state_layout": "per player in uid order (team 0 slots, team 1 slots): x, y, vx, vy; then ball x, y, vx, vy",
            "result": None if result is None else {"scores": result["scores"], "overtime": result["overtime"], "winner": result["winner"],
                                                   "team_stats": result["team_stats"], "ticks": result["ticks"], "puzzle": result.get("puzzle")},
            "scores_at_save": list(m.scores),
        }
        r = self.rows
        arrays = {
            "obs": np.asarray(r["obs"], np.float32), "state": np.asarray(r["state"], np.float32),
            "ctrl": np.asarray(ctrl, np.int16), "move": np.asarray(r["move"], np.int8), "kick": np.asarray(r["kick"], np.int8),
            "dir": np.asarray(r["dir"], np.float32), "tick": np.asarray(r["tick"], np.int32),
            "time_left": np.asarray(r["time_left"], np.float32), "score": np.asarray(r["score"], np.int16),
            "kickoff": np.asarray(r["kickoff"], np.int8), "speed": np.asarray(r["speed"], np.int8),
            "meta": np.array(json.dumps(meta, default=str)),
        }
        folder = data_dir()
        os.makedirs(folder, exist_ok=True)
        name = "%s_%s-%s_%s.npz" % (self.started.strftime("%Y%m%dT%H%M%SZ"), cfg.teams[0].id, cfg.teams[1].id, secrets.token_hex(2))
        path = os.path.join(folder, name)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            np.savez_compressed(f, **arrays)
        os.replace(tmp, path)
        self.saved = path
        return path


def wanted(setup, g):
    """Record this match? Only when the page asked for it and one human plays (the datasets have one controlled player; local
    multiplayer matches are not recorded)."""
    return bool(setup.get("record")) and len(g.people.humans) == 1
