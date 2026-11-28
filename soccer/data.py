"""Game data: pitches (as soccer.core.pitch.Pitch), kickoff spots (formations.json), players (soccer/players.py) and teams
(soccer/teams.py), read from the JSON files under data/; the web game (game/api.py) shows the same data."""
import glob
import json
import os

from .core.pitch import Pitch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MY_LEAGUE = "mine"                 # the league of the teams built in the game (local/my_teams)


def res_path(path: str) -> str:
    """res://x -> <repository>/x; other paths unchanged. res:// (the repository root) is kept from the Godot days: older
    commands, specs and test scenarios still name models that way."""
    return os.path.join(ROOT, path[6:]) if path.startswith("res://") else path


def local_dir():
    """Everything that belongs to this machine only (git-ignored): local/, or $SOCCER_LOCAL (tests)."""
    return os.environ.get("SOCCER_LOCAL") or os.path.join(ROOT, "local")


def my_teams_dir():
    """Where the teams built in the game are kept: local/my_teams, or $SOCCER_MY_TEAMS (tests)."""
    return os.environ.get("SOCCER_MY_TEAMS") or os.path.join(local_dir(), "my_teams")


_FORMATIONS = None


def formations():
    global _FORMATIONS
    if _FORMATIONS is None:
        with open(os.path.join(DATA, "formations.json")) as f:
            _FORMATIONS = json.load(f)
    return _FORMATIONS


def formation_slots(name):
    return formations()["formations"].get(name, [])


def default_formation(size):
    return formations()["defaults"].get(str(size), "1-2-1-1")


def _load_dir(path, skip_broken=False):
    """Every JSON file of a folder. A file that does not parse raises with its name (data/ is the game's own data), or with
    skip_broken (the teams built in the game) is left out with a note."""
    out = []
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        with open(f) as fh:
            try:
                d = json.load(fh)
            except ValueError as e:
                if skip_broken:
                    print("data: %s skipped (not valid JSON: %s)" % (f, e))
                    continue
                raise ValueError("%s: not valid JSON (%s)" % (f, e)) from None
        out.append(d)
    return out


class Database:
    """Everything under data/: pitches, players and teams (line-ups of players). Loading checks that every team's line-up names
    known players and every rule-based player's archetype exists, so a broken file fails at once with its name."""

    def __init__(self, root=ROOT, my_teams=True):
        from .ai.players import ALGORITHMS
        from .players import PlayerDef
        from .teams import Team
        data = os.path.join(root, "data")
        self.pitches = {p.id: p for p in (Pitch(d) for d in _load_dir(os.path.join(data, "pitches")))}
        self.players = {}
        for d in _load_dir(os.path.join(data, "players")):
            p = PlayerDef(d, root)
            if p.kind == "rules" and p.algorithm not in ALGORITHMS:
                raise ValueError("player %s: unknown algorithm %r (one of %s)" % (p.id, p.algorithm, ", ".join(ALGORITHMS)))
            self.players[p.id] = p
        self.teams = {}
        mine = my_teams_dir() if my_teams else None
        for d in [os.path.join(data, "teams")] + ([mine] if mine else []):
            for t in (Team(x) for x in _load_dir(d, skip_broken=d == mine)):
                missing = [i for i in t.lineup_ids if i not in self.players]
                if missing or not t.lineup_ids:
                    if d == mine:                    # a built team whose player was removed: skipped, never fatal
                        print("data: %s skipped (%s)" % (t.id, "unknown players " + ", ".join(missing) if missing else "empty line-up"))
                        continue
                    raise ValueError("team %s: line-up %s" % (t.id, "names unknown players " + ", ".join(missing) if missing
                                                              else "is empty"))
                if d == mine:
                    t.custom, t.league, t.rl_eval = True, MY_LEAGUE, False
                t.players = [self.players[i] for i in t.lineup_ids]
                self.teams[t.id] = t


def _hex(c, default):
    return str(c or default).lstrip("#").lower()[:6]


def team_colors(team):
    """[primary, secondary] kit colours of a team as "rrggbb"."""
    c = team.raw.get("colors", {})
    return [_hex(c.get("primary"), "e56e56"), _hex(c.get("secondary"), "ffffff")]


def resolve_kits(team_a, team_b):
    """MatchConfig.resolve_kits: [[primary, secondary] of team A, of team B], "rrggbb". The second team switches to its secondary
    colour (then to white) when the two primaries look alike, so the teams never look the same."""
    def rgb(h):
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def dist(x, y):
        return sum((p - q) ** 2 for p, q in zip(rgb(x), rgb(y))) ** 0.5

    ka, kb = team_colors(team_a), team_colors(team_b)
    if dist(ka[0], kb[0]) < 0.35:
        kb = [kb[1], kb[0]]
        if dist(ka[0], kb[0]) < 0.35:
            kb = ["e8e8e8", kb[1]]
    return [ka, kb]


_DB = None


def database():
    global _DB
    if _DB is None:
        _DB = Database()
    return _DB


def reload():
    """Forget the loaded data (after a team was built or deleted in the game); the next database() reads the files again."""
    global _DB
    _DB = None
    return database()
