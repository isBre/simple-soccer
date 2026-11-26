"""What the browser game needs from the match core: the catalog (leagues, players, teams, pitches, formations), match setup
from the page's choices, and whole matches simulated in parallel (tournament rounds).

A "setup" is the page's description of one match: {"home", "away", "pitch", "size", "duration", "seed", "control"
("none" | "single" | "team"), "human_team", "player" (single control: the line-up slot 0..size-1 to play, "" = auto),
"formations": [home, away], "allow_draw" (False: golden-goal overtime), "record" (save the human's play, game/recorder.py)}."""
import json
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

LEAGUES = [{"id": "rules", "name": "Rule Based League"}, {"id": "rl", "name": "Reinforcement Learning League"},
           {"id": "mixed", "name": "Mixed League"}]
CONTROL = {"none": sm.NONE, "single": sm.SINGLE, "team": sm.TEAM}
STYLE_PARAMS = ("line_height", "press", "marking", "directness", "pass_bias", "width")
KIND_LABEL = {"rules": "Rule-based", "opus": "Opus planner", "net": "Neural net (RL)"}
NET_DESCRIPTION = "Every player is the same neural net, trained with reinforcement learning. It finds its own shape (5v5 only)."


def league_index(league_id):
    return next((i for i, lg in enumerate(LEAGUES) if lg["id"] == league_id), len(LEAGUES))


ALL_LEAGUES = "all"           # a tournament with the teams of every league


def league_name(league_id):
    if league_id == ALL_LEAGUES:
        return "All leagues"
    i = league_index(league_id)
    return LEAGUES[i]["name"] if i < len(LEAGUES) else league_id.capitalize()


def stars(strength):
    """0..5 stars in half steps from the team rating (50 -> 0 stars, 89+ -> 5 stars), as TeamDef.stars."""
    return math.floor(min(1.0, max(0.0, (strength - 50.0) / 39.0)) * 10.0 + 0.5) / 2.0


# ---------- the teams of the game: every team of data/teams (line-ups of data/players) ----------
def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def teams():
    """{id: Team}: the teams of data/teams."""
    return database().teams


def players():
    """{id: PlayerDef}: the players of data/players."""
    return database().players


def ladder_id(t):
    """The team's id in the Elo ranking (lab/ladder.py)."""
    return ("team:" if t.ml_model else "rules:") + t.id


def team_sha(t):
    """The files a team's play depends on (team file, net), as a short hash."""
    path = os.path.join(ROOT, "data", "teams", t.id + ".json")
    sha = _sha(path) if os.path.exists(path) else ""
    if t.ml_model:
        model = os.path.join(ROOT, t.ml_model)
        if os.path.exists(model):
            sha += _sha(model)
    return sha


_cache = {}


def _cached_json(path, parse):
    """parse(file) for a file, re-read only when it changes; None when it is missing."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path) as f:
            val = parse(f)
    except (OSError, ValueError):
        val = None
    _cache[path] = (mt, val)
    return val


def elo_table():
    """{ladder id: Elo} from the latest snapshot of the ranking (exp/ladder_ratings.jsonl: 5v5, arena, 90 s)."""
    def last(f):
        line = ""
        for line in f:
            pass
        return json.loads(line).get("elo", {}) if line.strip() else {}
    return _cached_json(os.path.join(ROOT, "exp", "ladder_ratings.jsonl"), last) or {}


def profiles():
    return _cached_json(os.path.join(ROOT, "data", "team_profiles.json"), json.load) or {}


# ---------- how a team plays, in one sentence: with the ball; without it; how it scores ----------
# Every phrase comes from a measured scout statistic (game/profiles.py). A beat says what sets the team apart from its own league (rule
# bots from rule bots, nets from nets): a difference from the league median of at least the NOTICE step (about what a player notices in
# a match); the largest difference of the beat wins. A beat with nothing distinctive says what stands out against every team of the game
# (top or bottom fifth), so the best nets, typical of their league, still get a sentence. A phrase is only used when it is also true in
# absolute terms (its guard: hi_min for the "higher" text, lo_max for the "lower" text).
# (statistic, notice step, said when higher, said when lower, hi_min, lo_max)
BEATS = (
    (("possession_pct", 4.0, "keeps the ball for long spells", "lets you have the ball", 51.0, 48.0),
     ("passes_match", "rel:0.25", "plays it around with lots of passes", "hardly passes, it runs the ball forward", None, None),
     ("ball_own_half_pct", 4.0, "spends most of the game in its own half", "camps in your half", 50.0, 40.0)),
    (("ppda", 0.1, "drops off and lets you build", "presses the moment it loses the ball", 0.6, 0.55),
     ("line_out_px", 80.0, "pushes its defence up high", "keeps its last defender deep", None, None),
     ("goal_empty_pct", 10.0, "often leaves its goal empty", "", 10.0, None)),
    (("shots_match", 1.2, "shoots at every chance", "creates little up front", 3.0, 6.0),
     ("xg_shot", 0.04, "waits for the clear chance", "tries its luck from distance", None, None),
     ("ball_corner_ours_pct", 1.5, "works the ball into the corners", "", None, None)),
)
EXTREME = 0.2                    # the fallback: top or bottom fifth of all the teams


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return 0.0 if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _text(cand, v, higher):
    _, _, hi, lo, hi_min, lo_max = cand
    if higher:
        return hi if hi and (hi_min is None or v >= hi_min) else ""
    return lo if lo and (lo_max is None or v <= lo_max) else ""


def describe(tid):
    """'Camps in your half; presses the moment it loses the ball; shoots at every chance.' ('' without a profile)."""
    prof = profiles()
    me = prof.get(tid)
    known = teams()
    if not me or tid not in known:
        return ""
    every = [p for k, p in prof.items() if k in known]
    league = [p for k, p in prof.items() if k in known and known[k].league == known[tid].league]
    said = []
    for beat in BEATS:
        best, best_score = "", 0.0
        for cand in beat:                                         # what sets it apart in its league
            key, step = cand[0], cand[1]
            v, med = me.get(key, 0.0), _median([p.get(key, 0.0) for p in league])
            step = abs(med) * float(step[4:]) if isinstance(step, str) else step
            score = (v - med) / max(step, 1e-9)
            text = _text(cand, v, score > 0)
            if text and abs(score) >= 1.0 and abs(score) > best_score:
                best, best_score = text, abs(score)
        if not best:                                              # else what stands out against every team
            for cand in beat:
                v = me.get(cand[0], 0.0)
                vals = [p.get(cand[0], 0.0) for p in every]
                pct = (sum(1 for x in vals if x < v) + 0.5 * sum(1 for x in vals if x == v)) / max(len(vals), 1)
                text = _text(cand, v, pct > 0.5)
                if text and abs(pct - 0.5) >= 0.5 - EXTREME and abs(pct - 0.5) > best_score:
                    best, best_score = text, abs(pct - 0.5)
        if best:
            said.append(best)
    if not said:
        return "A bit of everything: no part of its game stands out."
    s = "; ".join(said) + "."
    return s[0].upper() + s[1:]


def formation_options(size):
    return [k for k in formations()["formations"] if len(formation_slots(k)) == size]


def player_info(p):
    """A player for the page: who it is, what drives it, how it was made, the sizes it can play."""
    db = database()
    style = db.styles.get(p.style_id) if p.kind != "net" else None
    return {"id": p.id, "name": p.name, "kind": p.kind, "kind_label": KIND_LABEL.get(p.kind, p.kind), "skill": p.skill if p.kind != "net" else None,
            "style": style.id if style else "", "style_label": style.name if style else "", "description": p.description,
            "origin": p.origin, "sizes": p.sizes(),
            "teams": sorted(t.id for t in teams().values() if p.id in t.lineup_ids)}


def team_info(t, elo=None):
    db = database()
    style = db.style_of(t)
    net = bool(t.ml_model)
    s = t.strength()
    elo = elo_table() if elo is None else elo
    e = elo.get(ladder_id(t))
    return {"id": t.id, "name": t.name, "short": t.short, "league": t.league,
            "league_name": league_name(t.league), "colors": team_colors(t), "kit": str(t.raw.get("kit", "solid")),
            "logo": t.raw.get("logo", {}), "net": net, "style": style.id, "kinds": t.kinds(),
            "style_label": "Neural net (RL)" if net else style.name,
            "style_description": NET_DESCRIPTION if net else style.description,
            "plays": describe(t.id), "elo": None if e is None else round(e),
            "style_params": {} if net else {k: getattr(style, k) for k in STYLE_PARAMS},
            "strength": s, "stars": stars(s), "formation_for": {str(n): t.formation_for(n) for n in range(1, 6)},
            "sizes": [n for n in range(1, 6) if t.can_play(n)],
            "lineup": [p.id for p in t.players],
            "lineup_for": {str(n): [p.id for p, _, _, _ in t.lineup(n)] for n in range(1, 6) if t.can_play(n)}}


def team_list():
    """Every team, grouped by league (LEAGUES order), strongest first inside a league (Elo; unranked teams last, by name)."""
    elo = elo_table()
    return sorted(teams().values(), key=lambda t: (league_index(t.league), -elo.get(ladder_id(t), -1e9), t.name))


def catalog():
    db = database()
    pitches = sorted(db.pitches.values(), key=lambda p: p.half_w)
    elo = elo_table()
    return {"leagues": [{**lg, "count": sum(1 for t in teams().values() if t.league == lg["id"])} for lg in LEAGUES],
            "teams": [team_info(t, elo) for t in team_list()],
            "players": [player_info(p) for p in sorted(players().values(), key=lambda p: (p.kind, p.name)) if not p.hidden],
            "pitches": [{"id": p.id, "name": p.name, "sizes": p.sizes, "recommended": int(p.sizes[-1]) if p.sizes else 3,
                         "half_w": p.half_w, "half_h": p.half_h, "goal_half": p.goal_half,
                         "colors": {k: str(p.raw.get("colors", {}).get(k, d)).lstrip("#")
                                    for k, d in (("pitch", "718c5a"), ("outer", "5b7347"), ("line", "c7e6bd"))}} for p in pitches],
            "formations": {str(n): formation_options(n) for n in range(1, 6)}}


def config(setup):
    """A MatchConfig from a setup (see the module docstring); unknown teams or pitches raise KeyError, a team that cannot play
    the size (only 5v5 nets in its line-up) raises ValueError."""
    all_teams = teams()
    size = int(setup.get("size", 3))
    for k in ("home", "away"):
        if setup[k] not in all_teams:
            raise KeyError("unknown team %r" % setup[k])
        if not all_teams[setup[k]].can_play(size):
            raise ValueError("%s cannot play %dv%d" % (all_teams[setup[k]].name, size, size))
    c = sm.make_config(setup["home"], setup["away"], setup.get("pitch", "arena"), size,
                       float(setup.get("duration", 180.0)), int(setup.get("seed", random.getrandbits(31))))
    c.control = CONTROL.get(str(setup.get("control", "none")), sm.NONE)
    c.human_team = 1 if int(setup.get("human_team", 0)) == 1 else 0
    slot = str(setup.get("player", "")).strip()
    c.human_slot = int(slot) if slot.isdigit() and int(slot) < size else -1
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
