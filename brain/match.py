"""The match as the AI sees it. Built once from Godot's setup message, then updated from a snapshot on every AI tick.
Positions are complex numbers (see vec.py), in the same pixel units and axes as Godot's MatchSim."""
import random

from .vec import clamp, lerpf, roundi

PLAYING, GOAL, ENDED = 0, 1, 2      # MatchSim.State
AI_PERIOD = 2                       # MatchSim.AI_PERIOD: a bot decides every 2nd tick
KICK_STRENGTH = 5.0                 # MatchSim.KICK_STRENGTH
KICK_RANGE = 4.0                    # MatchSim.KICK_RANGE
HIST = 20                           # ball positions Godot sends, newest first (reaction delay is at most 14 + 4 ticks)

STYLE_KEYS = ("line_height", "compactness", "width", "press", "marking", "directness", "shoot_range", "pass_bias", "risk",
              "keeper_sweep", "forward_stay", "support_dist", "fluidity", "attack_commit", "intercept", "counter_press",
              "long_shot", "switch_play")
STYLE_DEFAULTS = dict(line_height=0.5, compactness=0.5, width=1.0, press=0.5, marking=0.4, directness=0.5, shoot_range=0.55,
                      pass_bias=0.6, risk=0.4, keeper_sweep=0.3, forward_stay=0.3, support_dist=150.0, fluidity=0.6,
                      attack_commit=0.4, intercept=0.5, counter_press=0.0, long_shot=0.0, switch_play=0.0)


class Pitch:
    __slots__ = ("half_w", "half_h", "goal_half", "out_x", "out_y", "center_r")

    def __init__(self, d):
        for k in self.__slots__:
            setattr(self, k, float(d[k]))


class Style:
    """Team tactics (data/styles/*.json, StyleDef in Godot). All 0..1 unless noted."""

    def __init__(self, d):
        self.id = str(d.get("id", "balanced"))
        self.name = str(d.get("name", self.id))
        for k in STYLE_KEYS:
            setattr(self, k, float(d.get(k, STYLE_DEFAULTS[k])))


def quality(attr: float) -> float:
    """Maps an attribute (0-100) to a 0..1 quality: 40 -> 0, 95 -> 1."""
    return clamp((attr - 40.0) / 55.0, 0.0, 1.0)


class Player:
    """One player disc plus the AI-only effects of its attributes (they never change the physics)."""

    def __init__(self, d):
        self.uid = int(d["uid"])
        self.team = int(d["team"])
        self.slot = int(d["slot"])
        self.role = str(d["role"])                 # GK / DEF / MID / FWD
        self.home = complex(*d["home"])            # formation spot in the attack frame (-1 own goal line .. +1 opponent goal line)
        self.spawn = complex(*d["spawn"])          # kickoff position (world)
        self.radius = float(d.get("radius", 15.0))
        self.pos = self.spawn
        self.vel = 0j
        self.is_human = False
        a = d["attrs"]
        q_rea, q_fin, q_pas, q_pos = (quality(float(a[k])) for k in ("reaction", "finishing", "passing", "positioning"))
        self.defend_q = quality(float(a["defending"]))               # marking tightness, interceptions
        self.vision = (q_pas + q_pos + q_rea) / 3.0                  # how much of the play he reads
        self.reaction_delay = roundi(lerpf(14.0, 0.0, q_rea))        # ticks of delayed ball perception
        self.err_finish = lerpf(0.24, 0.005, q_fin)                  # radians (std dev) aim error when shooting
        self.err_pass = lerpf(0.20, 0.005, q_pas)                    # radians (std dev) aim error when passing
        self.pos_noise = lerpf(70.0, 2.0, q_pos)                     # px of positioning inaccuracy
        self.think_ticks = roundi(lerpf(18.0, 6.0, self.vision))     # ticks between two decisions of the ball carrier
        self.rng = random.Random(int(d["seed"]))
        self.bot = None                                               # rules.StyleBot or nets.NetBot, set by the session
        # the decision of the current tick
        self.out_dir = 0j
        self.out_kick = False
        self.out_intent = ""                                          # pass / shoot / clear / long (MatchSim uses it for stats)


class Match:
    def __init__(self, setup):
        self.pitch = Pitch(setup["pitch"])
        self.ball_r = float(setup.get("ball_radius", 10.0))
        self.duration = float(setup["duration"])
        self.styles = [Style(s) for s in setup["styles"]]
        self.players = [Player(p) for p in setup["players"]]     # team 0 first, slot order (MatchSim.team_lists order)
        self.by_uid = {p.uid: p for p in self.players}
        self.team_lists = [[p for p in self.players if p.team == t] for t in (0, 1)]
        self.tick = 0
        self.state = PLAYING
        self.kickoff_active = True
        self.kickoff_taker = None
        self.kickoff_go = 0
        self.scores = [0, 0]
        self.time_left = self.duration
        self.last_touch = None
        self.controlled = None
        self.ball_pos = 0j
        self.ball_vel = 0j
        self.hist = [0j] * HIST
        self.resets = 0
        self.brains = []                                          # rules.TeamBrain per team, set by the session

    @staticmethod
    def attack_dir(team: int) -> float:
        return 1.0 if team == 0 else -1.0

    def ball_at(self, delay: int) -> complex:
        """Where the ball was `delay` ticks ago (0 = last tick)."""
        return self.hist[min(delay, HIST - 1)]
