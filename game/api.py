"""What the browser game needs from the match core: the catalog (leagues, teams, pitches, formations), match setup from the
page's choices, and whole matches simulated in parallel (tournament rounds).

A "setup" is the page's description of one match: {"home", "away", "pitch", "size", "duration", "seed", "control"
("none" | "single" | "team"), "human_team", "player" (single control: "GK" | "DEF" | "MID" | "FWD" | "" = auto), "formations":
[home, away], "allow_draw", "record" (save the human's play, game/recorder.py)}."""
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
from soccer.data import Team, database, formation_slots, formations, resolve_kits, team_colors   # noqa: E402
from soccer.match import res_path                                     # noqa: E402

LEAGUES = [{"id": "rules", "name": "Rule Based League"}, {"id": "rl", "name": "Reinforcement Learning League"}]
CONTROL = {"none": sm.NONE, "single": sm.SINGLE, "team": sm.TEAM}
STYLE_PARAMS = ("line_height", "press", "marking", "directness", "pass_bias", "width")
NET_DESCRIPTION = ("All players, goalkeeper included, are controlled by a neural net trained with reinforcement learning. It chooses its own "
                   "formation and roles (5v5; other sizes fall back to the rule-based style).")


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


# ---------- the teams of the game: every team of data/teams, plus every ranked net (lab/ladder.py roster) as an RL team ----------
NET_PREFIX = "net_"
_NET_COLORS = ("e74c3c", "e67e22", "f1c40f", "2ecc71", "1abc9c", "3498db", "9b59b6", "e84393", "00cec9", "fd79a8", "a3cb38",
               "6c5ce7", "fab1a0", "74b9ff", "ff7675", "55efc4", "ffeaa7", "b2bec3", "d35400", "16a085")
_LOGO = {"shape": ("shield", "circle", "hex", "diamond"), "pattern": ("solid", "stripes", "halves", "chevron", "band", "quarters"),
         "symbol": ("star", "bolt", "crown", "ring", "cross", "none")}
_teams = None


def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def _net_name(stem):
    """x_kickstart_persist_best -> Kickstart Persist; t48_u100 -> T48 U100."""
    core = stem[2:-5] if stem.startswith("x_") and stem.endswith("_best") else stem[:-5] if stem.endswith("_best") else stem
    return " ".join(w[:1].upper() + w[1:] for w in core.split("_"))


def _net_team(entry, squad):
    """An RL team for one ranked net: RL Team 5's squad (as the ladder plays it), its own name, colours and crest."""
    import hashlib
    stem = entry["id"][4:]
    h = hashlib.sha1(stem.encode()).digest()
    c1 = _NET_COLORS[h[0] % len(_NET_COLORS)]
    c2 = "1d1d1f" if int(c1[2:4], 16) > 120 else "f2f2f2"
    name = _net_name(stem)
    raw = {**squad.raw, "id": NET_PREFIX + stem, "name": name, "short": "".join(w[0] for w in name.split())[:3].upper() or "NET",
           "colors": {"primary": c1, "secondary": c2}, "kit": _LOGO["pattern"][h[1] % 6],
           "logo": {"shape": _LOGO["shape"][h[2] % 4], "pattern": _LOGO["pattern"][h[3] % 6], "symbol": _LOGO["symbol"][h[4] % 5],
                    "c1": c1, "c2": c2, "c3": "ffffff"},
           "ml_model": "res://" + entry["model"], "league": "rl", "_ladder": entry["id"], "_sha": entry["sha"]}
    raw["players"] = [{**p, "id": "%s_%d" % (raw["id"], i)} for i, p in enumerate(squad.raw.get("players", []))]
    return Team(raw)


def teams():
    """{id: Team}: the teams of data/teams and one RL team per ranked net (built once per process)."""
    global _teams
    if _teams is None:
        out = dict(database().teams)
        try:
            lab = os.path.join(ROOT, "lab")
            if lab not in sys.path:
                sys.path.insert(0, lab)
            import ladder
            squad = out.get(ladder.NET_SQUAD)
            if squad is not None:
                for e in ladder.roster():
                    if e["kind"] == "net":
                        t = _net_team(e, squad)
                        out[t.id] = t
        except Exception as e:                  # never lose the handmade teams because of a broken net file
            print("game: the ranked nets could not be added (%s: %s)" % (type(e).__name__, e), flush=True)
        _teams = out
    return _teams


def ladder_id(t):
    """The team's id in the Elo ranking (lab/ladder.py)."""
    return t.raw.get("_ladder") or (("team:" if t.ml_model else "rules:") + t.id)


def team_sha(t):
    """The files a team's play depends on (team file, net), as a short hash."""
    if t.raw.get("_sha"):
        return t.raw["_sha"]
    path = os.path.join(ROOT, "data", "teams", t.id + ".json")
    sha = _sha(path) if os.path.exists(path) else ""
    if t.ml_model:
        model = res_path(t.ml_model)
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


def team_info(t, elo=None):
    db = database()
    style = db.style_of(t)
    net = bool(t.ml_model)
    s = t.strength()
    elo = elo_table() if elo is None else elo
    e = elo.get(ladder_id(t))
    return {"id": t.id, "name": t.name, "short": str(t.raw.get("short", t.name[:3].upper())), "league": t.league,
            "league_name": league_name(t.league), "colors": team_colors(t), "kit": str(t.raw.get("kit", "solid")),
            "logo": t.raw.get("logo", {}), "net": net, "style": style.id,
            "style_label": "Neural net (RL)" if net else style.name,
            "style_description": NET_DESCRIPTION if net else style.description,
            "plays": describe(t.id), "elo": None if e is None else round(e),
            "style_params": {} if net else {k: getattr(style, k) for k in STYLE_PARAMS},
            "strength": s, "stars": stars(s), "formation_for": {str(n): t.formation_for(n) for n in range(1, 6)},
            "players": [{"id": p.id, "number": p.number, "name": p.name, "pos": p.pos, "overall": p.overall(), "finishing": p.finishing,
                         "passing": p.passing, "defending": p.defending, "positioning": p.positioning, "reaction": p.reaction}
                        for p in t.players]}


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
            "pitches": [{"id": p.id, "name": p.name, "sizes": p.sizes, "recommended": int(p.sizes[-1]) if p.sizes else 3,
                         "half_w": p.half_w, "half_h": p.half_h, "goal_half": p.goal_half,
                         "colors": {k: str(p.raw.get("colors", {}).get(k, d)).lstrip("#")
                                    for k, d in (("pitch", "718c5a"), ("outer", "5b7347"), ("line", "c7e6bd"))}} for p in pitches],
            "formations": {str(n): formation_options(n) for n in range(1, 6)}}


def config(setup):
    """A MatchConfig from a setup (see the module docstring); unknown teams or pitches raise KeyError."""
    db = database()
    all_teams = teams()
    for k in ("home", "away"):
        if setup[k] not in all_teams:
            raise KeyError("unknown team %r" % setup[k])

    class _Db:                                          # make_config's lookups, with the ranked nets as teams
        pitches = db.pitches
    _Db.teams = all_teams
    c = sm.make_config(setup["home"], setup["away"], setup.get("pitch", "arena"), int(setup.get("size", 3)),
                       float(setup.get("duration", 180.0)), int(setup.get("seed", random.getrandbits(31))), db=_Db)
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
