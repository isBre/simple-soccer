"""The public view: everything a player of the match may know, the same for every kind of player (rule-based bots, nets, any
future agent). docs/public_view.md is the specification; this module is its implementation.

A player may use what a spectator in the stadium could know, and anything it computes from that (inferring, predicting,
simulating forward, searching). It never sees the match engine or another agent's inside.

  in the view      the ball and every player as an anonymous body (team, line-up slot, kickoff spot and its line, position,
                   velocity, size), the last HIST frames of all of them, the match clock (tick, 60 per second), score, time
                   left, overtime, state (playing / goal celebration), the kickoff (on, whose, who takes it), the last touch
                   (who and when), the pitch, and the physics as public constants (soccer.core.public: KICK_STRENGTH, KICK_RANGE,
                   damping, AI_PERIOD); on your own team's bodies: what each teammate calls (`intent`, public.INTENTS,
                   and since when, `intent_tick`) and whether a person controls it (`is_human`)
  not in the view  who a player is (name, kind, skill: only your own, in your own agent), the match object, every other
                   agent's inside, teammates included: its plan, its memory, its random numbers, the buttons it is about to
                   press; the opponents' calls; the moment the other team's kickoff taker will kick

Every player decides alone (its brain, soccer.core.match): players talk only through their calls. Each team gets its own View with its
own Body objects (the match builds them; nobody shares a Body across teams); on the opponents' bodies the calls stay "none" and
is_human False. Bodies are the same objects for the whole match (updated in place every tick), so an agent may remember them.

`reaction_delay` and `defend_q` on a Body are the GENERIC assumption about an unknown player (skill 70): an agent judges
others, teammates included, by how they move, never by who they are. A player's own skill is in its own brain (soccer/ai/skill.py).
"""
from .public import GOAL, HIST, quality

GENERIC_SKILL = 70.0                                   # what an agent assumes about any player but itself
_GQ = quality(GENERIC_SKILL)
GENERIC_DELAY = int(14.0 - 14.0 * _GQ + 0.5)           # ticks of ball-perception delay (skill.attach_skill with the generic skill)
GENERIC_Q = _GQ                                        # marking / interception quality


class Body:
    """A player as anyone can see it. Public: uid, team, slot, radius, line, home, spawn, pos, vel. Own team only: intent and
    intent_tick (what the player calls and since when), is_human."""
    __slots__ = ("uid", "team", "slot", "radius", "line", "home", "spawn", "pos", "vel", "intent", "intent_tick", "is_human")
    reaction_delay = GENERIC_DELAY
    defend_q = GENERIC_Q

    def __init__(self, p):
        self.uid, self.team, self.slot, self.radius = p.uid, p.team, p.slot, p.radius
        self.line, self.home, self.spawn = p.line, p.home, p.spawn
        self.pos, self.vel = p.pos, p.vel
        self.intent, self.intent_tick, self.is_human = "none", 0, False


class Ball:
    __slots__ = ("pos", "vel", "radius")

    def __init__(self, b):
        self.pos, self.vel, self.radius = b.pos, b.vel, b.radius


class View:
    """The public view for team `team` (see the module docstring). refresh(m) copies the public state of the match in; the
    view keeps no reference to the match.

    Training can take players off the pitch ("ghosts", rl/env.py: still in m.team_lists, no longer in m.players). The view
    keeps both: `team_lists` are the full line-ups (every Body, ghosts where the match parks them; the fixed-size net
    observations read these), `in_play` and `players` only the bodies on the pitch (what a player reasons about). In a match
    without ghosts they hold the same bodies in the same order."""

    def __init__(self, m, team):
        self.team = team
        self.pitch = m.pitch
        self.duration = m.duration
        self.bodies = {p.uid: Body(p) for t in (0, 1) for p in m.team_lists[t]}
        self.team_lists = [[self.bodies[p.uid] for p in m.team_lists[t]] for t in (0, 1)]
        self.players, self.in_play = [], self.team_lists
        self.by_uid = self.bodies
        self.ball = Ball(m.ball)
        self.ball_r = m.ball.radius
        self.refresh(m)

    def refresh(self, m):
        t = self.team
        for lst in m.team_lists:
            for p in lst:
                b = self.bodies[p.uid]
                b.pos, b.vel = p.pos, p.vel
                if p.team == t:                        # a team hears its own calls and knows which of its players a person controls
                    b.intent, b.intent_tick, b.is_human = p.intent, p.intent_tick, p.is_human
        if len(m.players) != len(self.players):        # players only ever leave the pitch (training), so the count says it all
            self.players = [self.bodies[p.uid] for p in m.players]
            on = {b.uid for b in self.players}
            self.in_play = [[b for b in lst if b.uid in on] for lst in self.team_lists] \
                if len(on) < len(self.bodies) else self.team_lists
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
        self.human_mates = [self.bodies[p.uid] for p in m.people_seats() if p.team == t]
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
        lst = self.in_play[team]
        if len(lst) < 2:
            return None
        ax = self.attack_dir(team)
        return min(lst, key=lambda b: (b.pos.real * ax, b.uid))
