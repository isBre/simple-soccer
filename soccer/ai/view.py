"""The public view: everything a player of the match may know, the same for every kind of player (rule-based bots, nets, any
future agent). docs/public_view.md is the specification; this module is its implementation.

A player may use what a spectator in the stadium could know, and anything it computes from that (inferring, predicting,
simulating forward, searching). It never sees the match engine or another agent's inside.

  in the view      the ball and every player as an anonymous body (team, line-up slot, kickoff spot and its line, position,
                   velocity, size), the last HIST frames of all of them, the match clock (tick, 60 per second), score, time
                   left, overtime, state (playing / goal celebration), the kickoff (on, whose, who takes it), the last touch
                   (who and when), the pitch, and the physics as public constants (soccer.match: KICK_STRENGTH, KICK_RANGE,
                   damping, AI_PERIOD)
  not in the view  who a player is (name, kind, skill: only your own, in your own bot), the match object, every other
                   agent's inside: its brain and plan, its memory, its random numbers, the buttons it is about to press, the
                   moment the other team's kickoff taker will kick

Each team gets its own View with its own Body objects (MatchAI builds them; nobody shares a Body across teams). On a team's own
bodies the brain that commands the player (`brain`), the human flag and the buttons (`input_dir`, `input_kick`, `kick_intent`)
are set: a team talks to itself. On the opponents' bodies they stay empty. Bodies are the same objects for the whole match
(updated in place every tick), so a brain may remember them from tick to tick.

`reaction_delay` and `defend_q` on a Body are the GENERIC assumption about an unknown player (skill 70): an agent judges
others, teammates included, by how they move, never by who they are. A player's own skill is in its own bot (soccer/ai/skill.py).
"""
from ..match import GOAL, HIST
from .skill import quality

GENERIC_SKILL = 70.0                                   # what an agent assumes about any player but itself
_GQ = quality(GENERIC_SKILL)
GENERIC_DELAY = int(14.0 - 14.0 * _GQ + 0.5)           # ticks of ball-perception delay (skill.attach_skill with the generic skill)
GENERIC_Q = _GQ                                        # marking / interception quality


class Body:
    """A player as anyone can see it. Public: uid, team, slot, radius, line, home, spawn, pos, vel. Own team only: brain,
    is_human, input_dir / input_kick / kick_intent (the team's own buttons)."""
    __slots__ = ("uid", "team", "slot", "radius", "line", "home", "spawn", "pos", "vel", "brain", "is_human",
                 "input_dir", "input_kick", "kick_intent")
    reaction_delay = GENERIC_DELAY
    defend_q = GENERIC_Q

    def __init__(self, p):
        self.uid, self.team, self.slot, self.radius = p.uid, p.team, p.slot, p.radius
        self.line, self.home, self.spawn = p.line, p.home, p.spawn
        self.pos, self.vel = p.pos, p.vel
        self.brain, self.is_human = None, False
        self.input_dir, self.input_kick, self.kick_intent = 0j, False, ""


class Ball:
    __slots__ = ("pos", "vel", "radius")

    def __init__(self, b):
        self.pos, self.vel, self.radius = b.pos, b.vel, b.radius


class View:
    """The public view for team `team` (see the module docstring). refresh(m) copies the public state of the match in; the
    view keeps no reference to the match."""

    def __init__(self, m, team):
        self.team = team
        self.pitch = m.pitch
        self.duration = m.cfg.duration
        self.bodies = {p.uid: Body(p) for p in m.players}
        self.team_lists = [[self.bodies[p.uid] for p in m.team_lists[t]] for t in (0, 1)]
        self.players = [self.bodies[p.uid] for p in m.players]
        self.by_uid = self.bodies
        self.ball = Ball(m.ball)
        self.ball_r = m.ball.radius
        self.refresh(m)

    def refresh(self, m):
        t = self.team
        for p in m.players:
            b = self.bodies[p.uid]
            b.pos, b.vel = p.pos, p.vel
            if p.team == t:                            # a team knows its own: who commands whom, its human, its buttons
                b.brain, b.is_human = p.brain, p.is_human
                b.input_dir, b.input_kick, b.kick_intent = p.input_dir, p.input_kick, p.kick_intent
        self.ball.pos, self.ball.vel = m.ball.pos, m.ball.vel
        self.tick = m.tick
        self.state = m.state
        self.scores = list(m.scores)
        self.time_left = m.time_left
        self.overtime = m.overtime
        self.kickoff_active = m.kickoff_active
        self.kickoff_team = m.kickoff_team
        self.kickoff_taker = self.bodies[m.kickoff_taker.uid] if m.kickoff_taker is not None else None
        self.kickoff_go = m.kickoff_go if m.kickoff_team == t else None     # only the taker's own team knows when it kicks
        self.last_touch = self.bodies[m.last_touch.uid] if m.last_touch is not None else None
        self.last_touch_tick = m.last_touch_tick
        h = m.controlled
        self.controlled = self.bodies[h.uid] if h is not None and h.team == t else None
        self._ball_hist, self._pos_hist, self._hist_idx = m.ball_hist, m.pos_hist, m.hist_idx   # the public history (recorded by the match)
        return self

    # ---------- what the AI reads (the names the match had, so the bots read a view exactly like they read the match) ----------
    @property
    def ball_pos(self):
        return self.ball.pos

    @property
    def ball_vel(self):
        return self.ball.vel

    @staticmethod
    def attack_dir(team):
        return 1.0 if team == 0 else -1.0

    def ball_at(self, delay):
        """The ball's position `delay` ticks ago (0 = this tick), from the last HIST frames."""
        return self._ball_hist[(self._hist_idx - 1 - delay + HIST * 2) % HIST]

    def pos_at(self, uid, delay):
        """A player's position `delay` ticks ago (0 = this tick)."""
        return self._pos_hist[(self._hist_idx - 1 - delay + HIST * 2) % HIST].get(uid, self.bodies[uid].pos)

    def celebrating(self):
        return self.state == GOAL

    def deepest(self, team):
        """The player of `team` nearest its own goal line (who seems to guard the goal), None for a team of one."""
        lst = self.team_lists[team]
        if len(lst) < 2:
            return None
        ax = self.attack_dir(team)
        return min(lst, key=lambda b: (b.pos.real * ax, b.uid))
