"""Game data for the match core: pitches, styles, formations, players (soccer/players.py) and teams (soccer/teams.py), read
from the JSON files under data/ (pitches, styles, players, teams, formations.json); the web game (game/api.py) shows the same data."""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

STYLE_KEYS = ("line_height", "compactness", "width", "press", "marking", "directness", "shoot_range", "pass_bias", "risk",
              "keeper_sweep", "forward_stay", "support_dist", "fluidity", "attack_commit", "intercept", "counter_press",
              "long_shot", "switch_play")
STYLE_DEFAULTS = dict(line_height=0.5, compactness=0.5, width=1.0, press=0.5, marking=0.4, directness=0.5, shoot_range=0.55,
                      pass_bias=0.6, risk=0.4, keeper_sweep=0.3, forward_stay=0.3, support_dist=150.0, fluidity=0.6,
                      attack_commit=0.4, intercept=0.5, counter_press=0.0, long_shot=0.0, switch_play=0.0)


class Pitch:
    """A pitch (PitchDef): goal line x = half_w, touch line y = half_h, posts, outer walls for players, obstacles, extra walls."""
    NUM = ("half_w", "half_h", "goal_half", "net_depth", "out_x", "out_y", "center_r", "post_r", "box_depth", "box_half")
    DEFAULTS = dict(half_w=370.0, half_h=170.0, goal_half=64.0, net_depth=40.0, out_x=420.0, out_y=200.0, center_r=75.0,
                    post_r=8.0, box_depth=0.0, box_half=0.0)

    def __init__(self, d):
        self.raw = d
        self.id = str(d.get("id", "pitch"))
        self.name = str(d.get("name", self.id))
        self.sizes = list(d.get("sizes", [3]))
        for k in self.NUM:
            setattr(self, k, float(d.get(k, self.DEFAULTS[k])))
        self.obstacles = [[float(v) for v in o] for o in d.get("obstacles", [])]
        self.walls = [{"a": complex(w["a"][0], w["a"][1]), "b": complex(w["b"][0], w["b"][1]),
                       "ball": bool(w.get("ball", True)), "player": bool(w.get("player", False)), "bc": float(w.get("bc", 1.0))}
                      for w in d.get("walls", [])]


class Style:
    """Team tactics (StyleDef). All 0..1 unless noted."""

    def __init__(self, d):
        self.id = str(d.get("id", "balanced"))
        self.name = str(d.get("name", self.id))
        self.description = str(d.get("description", ""))
        self.brain = str(d.get("brain", "rules"))       # "rules" (TeamBrain + StyleBot) or "opus" (soccer/ai/opus.py)
        for k in STYLE_KEYS:
            setattr(self, k, float(d.get(k, STYLE_DEFAULTS[k])))

    def to_dict(self):
        d = {"id": self.id, "name": self.name, "description": self.description}
        d.update({k: getattr(self, k) for k in STYLE_KEYS})
        return d


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


def _load_dir(path):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        with open(f) as fh:
            try:
                d = json.load(fh)
            except ValueError:
                continue
        out.append(d)
    return out


class Database:
    """Everything under data/: pitches, styles, players and teams (line-ups of players). Loading checks that every team's
    line-up names known players and every player's style exists, so a broken file fails at once with its name."""

    def __init__(self, root=ROOT, extra_team_dirs=()):
        from .players import PlayerDef
        from .teams import Team
        data = os.path.join(root, "data")
        self.pitches = {p.id: p for p in (Pitch(d) for d in _load_dir(os.path.join(data, "pitches")))}
        self.styles = {s.id: s for s in (Style(d) for d in _load_dir(os.path.join(data, "styles")))}
        self.players = {}
        for d in _load_dir(os.path.join(data, "players")):
            p = PlayerDef(d, root)
            if p.kind != "net" and p.style_id not in self.styles:
                raise ValueError("player %s: unknown style %r" % (p.id, p.style_id))
            self.players[p.id] = p
        self.teams = {}
        for d in [os.path.join(data, "teams")] + list(extra_team_dirs):
            for t in (Team(x) for x in _load_dir(d)):
                missing = [i for i in t.lineup_ids if i not in self.players]
                if missing or not t.lineup_ids:
                    raise ValueError("team %s: line-up %s" % (t.id, "names unknown players " + ", ".join(missing) if missing
                                                              else "is empty"))
                t.players = [self.players[i] for i in t.lineup_ids]
                self.teams[t.id] = t

    def style_of(self, team):
        return self.styles.get(team.style_id, self.styles.get("balanced", Style({})))

    def style_of_player(self, player):
        return self.styles.get(player.style_id, self.styles.get("balanced", Style({})))


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
