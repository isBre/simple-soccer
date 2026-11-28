"""A pitch: its size, goals and walls, everything the match builds the stadium from (the game reads them from data/pitches)."""


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
