"""Game data for the match core: pitches, styles, players, teams, formations and line-ups. Read from the same JSON files
the Godot UI reads (data/pitches, data/styles, data/teams, data/formations.json), or from dicts sent by the UI (teams
saved under user://teams only exist on the Godot side)."""
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


def roundi(x: float) -> int:
    """Godot's roundi: halves away from zero."""
    import math
    return int(math.floor(x + 0.5)) if x >= 0.0 else -int(math.floor(-x + 0.5))


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
        for k in STYLE_KEYS:
            setattr(self, k, float(d.get(k, STYLE_DEFAULTS[k])))

    def to_dict(self):
        d = {"id": self.id, "name": self.name, "description": self.description}
        d.update({k: getattr(self, k) for k in STYLE_KEYS})
        return d


class PlayerDef:
    def __init__(self, d):
        self.id = str(d.get("id", ""))
        self.name = str(d.get("name", "Player"))
        self.number = int(d.get("number", 1))
        self.pos = str(d.get("pos", "MID"))
        a = d.get("attrs", {})
        self.finishing = int(a.get("finishing", 60))
        self.passing = int(a.get("passing", 60))
        self.defending = int(a.get("defending", 60))
        self.positioning = int(a.get("positioning", 60))
        self.reaction = int(a.get("reaction", 60))

    def overall(self) -> int:
        if self.pos == "GK":
            v = self.positioning * 0.35 + self.reaction * 0.4 + self.defending * 0.25
        elif self.pos == "DEF":
            v = self.defending * 0.4 + self.positioning * 0.25 + self.passing * 0.2 + self.reaction * 0.15
        elif self.pos == "MID":
            v = self.passing * 0.35 + self.positioning * 0.2 + self.defending * 0.15 + self.reaction * 0.15 + self.finishing * 0.15
        else:
            v = self.finishing * 0.4 + self.reaction * 0.2 + self.passing * 0.2 + self.positioning * 0.2
        return roundi(v)


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


class Team:
    """A team (TeamDef): identity, style, formations per size, optional net (ml_model) and its squad."""

    def __init__(self, d):
        self.raw = d
        self.id = str(d.get("id", ""))
        self.name = str(d.get("name", self.id))
        self.style_id = str(d.get("style", "balanced"))
        self.formations = d.get("formations", {})
        self.ml_model = str(d.get("ml_model", ""))
        self.league = str(d.get("league", "rl" if self.ml_model else "rules"))
        self.players = [PlayerDef(p) for p in d.get("players", [])]

    def strength(self):
        """Team rating: average overall of the best 5 players (TeamDef.strength)."""
        best = sorted((p.overall() for p in self.players), reverse=True)[:5]
        return sum(best) / len(best) if best else 0.0

    def formation_for(self, size):
        f = str(self.formations.get(str(size), ""))
        if f and len(formation_slots(f)) == size:
            return f
        return default_formation(size)

    def lineup(self, size, formation=""):
        """[(PlayerDef, role, fx, fy)] for this team size: the best player for each slot of the formation
        (TeamDef.lineup: by overall, the first one whose position fits, else the best remaining outfielder)."""
        fname = formation
        if not fname or len(formation_slots(fname)) != size:
            fname = self.formation_for(size)
        pool = sorted(self.players, key=lambda p: -p.overall())     # stable, like Godot's sort for distinct values
        out = []
        for role, fx, fy in formation_slots(fname):
            pick = next((p for p in pool if p.pos == role), None)
            if pick is None:
                pick = next((p for p in pool if p.pos != "GK" or role == "GK"), None)
            if pick is None and pool:
                pick = pool[0]
            if pick is not None:
                pool.remove(pick)
                out.append((pick, role, float(fx), float(fy)))
        return out


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
    """Everything under data/ (the Godot Database autoload, without the UI parts)."""

    def __init__(self, root=ROOT, extra_team_dirs=()):
        data = os.path.join(root, "data")
        self.pitches = {p.id: p for p in (Pitch(d) for d in _load_dir(os.path.join(data, "pitches")))}
        self.styles = {s.id: s for s in (Style(d) for d in _load_dir(os.path.join(data, "styles")))}
        self.teams = {}
        for d in [os.path.join(data, "teams")] + list(extra_team_dirs):
            for t in (Team(x) for x in _load_dir(d)):
                self.teams[t.id] = t

    def style_of(self, team):
        return self.styles.get(team.style_id, self.styles.get("balanced", Style({})))


_DB = None


def database():
    global _DB
    if _DB is None:
        _DB = Database()
    return _DB
