"""Plays rated matches: both legs of a pair (sides swapped, same seed) per job, on a pool of niced worker processes, so a round
never starves a training run or a live match. A job is plain data (specs of the two entries, the size, a seed): the worker
rebuilds the teams from the game's files."""
import multiprocessing as mp
import os
import time

from . import DURATION, MAX_TICKS, PITCH, ROOT


def _nice():
    try:
        os.nice(10)
    except OSError:
        pass


def _team(spec, db, PlayerDef, Team):
    players = []
    for d in spec["lineup"]:
        if "model" in d:                              # a training checkpoint: a net player that is not in data/players
            players.append(PlayerDef({"id": d["id"], "name": spec["name"], "kind": "net", "model": d["model"]}, ROOT))
        else:
            players.append(db.players[d["id"]])
    t = Team({"id": spec["id"], "name": spec["name"], "lineup": [p.id for p in players]})
    t.players = players
    return t


def play_pair(job):
    """job = (spec_a, spec_b, size, seed): both legs, two result dicts (a is always the first entry)."""
    from soccer.data import database
    from soccer.core.public import ENDED
    from soccer.game import MatchConfig, new_match
    from soccer.players import PlayerDef
    from soccer.teams import Team
    sa, sb, size, seed = job
    db = database()
    teams = {sa["id"]: _team(sa, db, PlayerDef, Team), sb["id"]: _team(sb, db, PlayerDef, Team)}
    out = []
    for home, away in ((sa, sb), (sb, sa)):
        c = MatchConfig()
        c.pitch = db.pitches[PITCH]
        c.teams = [teams[home["id"]], teams[away["id"]]]
        c.team_size = size
        c.duration = DURATION
        c.match_seed = seed
        m = new_match(c)
        while m.state != ENDED and m.tick < MAX_TICKS:
            m.step()
        g = {home["id"]: m.scores[0], away["id"]: m.scores[1]}
        out.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "size": size, "a": sa["id"], "b": sb["id"], "a_sha": sa["sha"], "b_sha": sb["sha"],
                    "a_side": 0 if home is sa else 1, "ga": g[sa["id"]], "gb": g[sb["id"]], "seed": seed, "stalled": m.state != ENDED})
    return out


def play(jobs, workers=3):
    """The results of all jobs (two per job). With workers > 1 on niced worker processes; else in this process, which is never
    niced (it may be the web server or the training runner)."""
    if workers > 1 and len(jobs) > 1:
        with mp.get_context("spawn").Pool(min(workers, len(jobs)), initializer=_nice) as pool:
            return [r for pair in pool.map(play_pair, jobs) for r in pair]
    return [r for j in jobs for r in play_pair(j)]
