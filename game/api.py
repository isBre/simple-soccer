"""What the browser game needs from the match core: the catalog (leagues, teams, pitches, formations), match setup from the
page's choices, and whole matches simulated in parallel (tournament rounds).

A "setup" is the page's description of one match: {"home", "away", "pitch", "size", "duration", "seed", "control"
("none" | "single" | "team"), "human_team", "player" (single control: "GK" | "DEF" | "MID" | "FWD" | "" = auto), "formations":
[home, away], "allow_draw", "record" (save the human's play, game/recorder.py)}."""
import math
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from soccer import match as sm                                       # noqa: E402
from soccer.data import database, formation_slots, formations, resolve_kits, team_colors   # noqa: E402

LEAGUES = [{"id": "rules", "name": "Rule Based League"}, {"id": "rl", "name": "Reinforcement Learning League"}]
CONTROL = {"none": sm.NONE, "single": sm.SINGLE, "team": sm.TEAM}
STYLE_PARAMS = ("line_height", "press", "marking", "directness", "pass_bias", "width")
NET_DESCRIPTION = ("All players, goalkeeper included, are controlled by a neural net trained with reinforcement learning. It chooses its own "
                   "formation and roles (5v5; other sizes fall back to the rule-based style).")


def league_index(league_id):
    return next((i for i, lg in enumerate(LEAGUES) if lg["id"] == league_id), len(LEAGUES))


def league_name(league_id):
    i = league_index(league_id)
    return LEAGUES[i]["name"] if i < len(LEAGUES) else league_id.capitalize()


def stars(strength):
    """0..5 stars in half steps from the team rating (50 -> 0 stars, 89+ -> 5 stars), as TeamDef.stars."""
    return math.floor(min(1.0, max(0.0, (strength - 50.0) / 39.0)) * 10.0 + 0.5) / 2.0


def formation_options(size):
    return [k for k in formations()["formations"] if len(formation_slots(k)) == size]


def team_info(t):
    db = database()
    style = db.style_of(t)
    net = bool(t.ml_model)
    s = t.strength()
    return {"id": t.id, "name": t.name, "short": str(t.raw.get("short", t.name[:3].upper())), "league": t.league,
            "league_name": league_name(t.league), "colors": team_colors(t), "kit": str(t.raw.get("kit", "solid")),
            "logo": t.raw.get("logo", {}), "net": net, "style": style.id,
            "style_label": "Neural net (RL)" if net else style.name,
            "style_description": NET_DESCRIPTION if net else style.description,
            "style_params": {} if net else {k: getattr(style, k) for k in STYLE_PARAMS},
            "strength": s, "stars": stars(s), "formation_for": {str(n): t.formation_for(n) for n in range(1, 6)},
            "players": [{"id": p.id, "number": p.number, "name": p.name, "pos": p.pos, "overall": p.overall(), "finishing": p.finishing,
                         "passing": p.passing, "defending": p.defending, "positioning": p.positioning, "reaction": p.reaction}
                        for p in t.players]}


def team_list():
    """Every team, grouped by league (LEAGUES order), by name inside a league (Database.team_list)."""
    return sorted(database().teams.values(), key=lambda t: (league_index(t.league), t.name))


def catalog():
    db = database()
    pitches = sorted(db.pitches.values(), key=lambda p: p.half_w)
    return {"leagues": [{**lg, "count": sum(1 for t in db.teams.values() if t.league == lg["id"])} for lg in LEAGUES],
            "teams": [team_info(t) for t in team_list()],
            "pitches": [{"id": p.id, "name": p.name, "sizes": p.sizes, "recommended": int(p.sizes[-1]) if p.sizes else 3,
                         "half_w": p.half_w, "half_h": p.half_h, "goal_half": p.goal_half} for p in pitches],
            "formations": {str(n): formation_options(n) for n in range(1, 6)}}


def config(setup):
    """A MatchConfig from a setup (see the module docstring); unknown teams or pitches raise KeyError."""
    db = database()
    for k in ("home", "away"):
        if setup[k] not in db.teams:
            raise KeyError("unknown team %r" % setup[k])
    c = sm.make_config(setup["home"], setup["away"], setup.get("pitch", "arena"), int(setup.get("size", 3)),
                       float(setup.get("duration", 180.0)), int(setup.get("seed", random.getrandbits(31))))
    c.control = CONTROL.get(str(setup.get("control", "none")), sm.NONE)
    c.human_team = 1 if int(setup.get("human_team", 0)) == 1 else 0
    role = str(setup.get("player", "")).upper()
    c.human_role = role if role in ("GK", "DEF", "MID", "FWD") else ""
    c.allow_draw = bool(setup.get("allow_draw", True))
    fs = list(setup.get("formations") or ["", ""])[:2]
    c.formations = [str(f) if f and len(formation_slots(str(f))) == c.team_size else "" for f in fs] + [""] * (2 - len(fs))
    return c


def play(setup):
    """Plays one whole match (no human) and returns its result. Runs in a worker process."""
    m = sm.Match(config(setup))
    m.run_to_end()
    return m.make_result()


_pool = None


def _worker_init():
    try:
        os.nice(10)                     # tournament rounds must not starve a training run on the Pi
    except OSError:
        pass


def simulate(setups):
    """Results of several whole matches, played in parallel on all cores (a tournament round)."""
    global _pool
    if not setups:
        return []
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=max(1, os.cpu_count() or 1), mp_context=mp.get_context("spawn"),
                                    initializer=_worker_init)
    return list(_pool.map(play, setups))
