"""What every rule-based player shares: its senses and precision (its own skill, soccer/ai/skill.py), how it reads the situation
from the public view (Sit), the kickoff, the decision whether the ball is its to play (with the teammates' calls), and the ball
play machinery (pick a kind of kick and an aim, then strike it). Each archetype (one file in this folder) decides the rest with
its own algorithm: what to do on the ball (`choose`), where to be without it (`off_ball`), how eager it is for the ball
(`wants_ball`) and what it calls.

An agent is alone: it reads its team's view and its own memory, never another agent (soccer/core/act.py)."""
from ...core.public import BALL_DAMPING
from ...core.vec import INF, clamp, lerp
from .. import kit
from ...core.act import Act
from ..skill import attach_skill


class Sit:
    """The situation one player reads from the view at one decision (all from the public view and its own senses).

      ax, own_goal, opp_goal, hw, hh   direction of attack, the two goals, the half sizes of the pitch
      ball, bvel                       where it sees the ball (its own perception delay) and how fast it moves
      mates, opps                      the other bodies of its team, the opponents
      have, lost                       our team touched the ball last / theirs did
      my_pt, my_t                      roughly where and when it can meet the ball (12 points of the ball's path; on_ball
                                       works it out exactly)
      mate_t, opp_t                    {mate: ticks} the teammates' estimated times to the ball, the fastest opponent's
      calls                            {intent: [mates calling it]} what the teammates call
      danger                           the ball is in our third"""

    def __init__(self, agent, v, me):
        self.v, self.me = v, me
        self.ax = v.attack_dir(me.team)
        pd = v.pitch
        self.hw, self.hh = pd.half_w, pd.half_h
        self.own_goal = complex(-self.ax * pd.half_w, 0.0)
        self.opp_goal = complex(self.ax * pd.half_w, 0.0)
        d = agent.reaction_delay
        self.ball = v.ball_at(d)
        self.bvel = (self.ball - v.ball_at(d + 4)) / 4.0
        self.mates = [b for b in v.in_play[me.team] if b is not me]     # the players on the pitch (not training's ghosts)
        self.opps = v.in_play[1 - me.team]
        lt = v.last_touch
        self.have = lt is not None and lt.team == me.team
        self.lost = lt is not None and lt.team != me.team
        path = kit.quick_path(v, self.ball, self.bvel)
        self.my_t, self.my_pt = kit.reach_times(v, [me], path, d)[me]
        self.mate_t = {b: t for b, (t, _) in kit.reach_times(v, self.mates, path).items()}
        self._path = path
        self.calls = {}
        for b in self.mates:
            self.calls.setdefault("human" if b.is_human else b.intent, []).append(b)
        self.danger = self.ball.real * -self.ax > self.hw * 0.4

    @property
    def opp_t(self) -> float:
        """The fastest opponent's estimated time to the ball (worked out when asked)."""
        return min((t for t, _ in kit.reach_times(self.v, self.opps, self._path).values()), default=INF)

    def x(self, p: complex) -> float:
        """How far up the pitch a point is for us: -1 our goal line, +1 theirs."""
        return p.real * self.ax / self.hw

    def deepest_mate_x(self) -> float:
        return min((self.x(b.pos) for b in self.mates), default=INF)


class RuleAgent:
    """A rule-based player. Subclasses set NAME, DESCRIPTION, SETTINGS ({key: (default, label)}: the archetype's own numbers,
    0..1 unless noted) and override choose / off_ball (and wants_ball, guards) with their own algorithm."""
    NAME = "player"
    DESCRIPTION = ""
    SETTINGS = {}
    GUARDS = True               # steps in to guard our goal when nobody calls cover and it is the deepest

    def __init__(self, settings=None, skill=70, seed=0):
        self.set = {k: float((settings or {}).get(k, d)) for k, (d, _) in self.SETTINGS.items()}
        attach_skill(self, skill, seed)
        self._kind, self._aim, self._decided, self._err, self._target_mate = "dribble", 0j, -999, 0.0, None
        self._noise, self._noise_tick = 0j, -999
        self._guarding = False
        self._mine = False

    # ------------------------------------------------------------ the decision
    def decide(self, v, me):
        if v.kickoff_active:
            return self.kickoff(v, me)
        s = Sit(self, v, me)
        if self.wants_ball(s):
            self._mine, self._guarding = True, False
            act = self.on_ball(s)
        else:
            self._mine = False
            act = self.guard(s) if self.should_guard(s) else None
            if act is None:
                self._guarding = False
                act = self.off_ball(s)
        act.dir = kit.avoid(v, me, act.dir)
        return act

    def kickoff(self, v, me):
        if me is v.kickoff_taker:                     # stand behind the ball, kick when our team's moment comes
            return Act(0j, v.kickoff_go is not None and v.tick >= v.kickoff_go, "none", "pass")
        return Act(kit.arrive(me, me.spawn))

    # ------------------------------------------------------------ whose ball
    def ball_is_mine(self, s, margin=0.0) -> bool:
        """The shared rule: it plays the ball when it gets there first (by `margin` ticks of leeway, more if it already had it),
        unless a teammate who is about as quick already calls "ball", or a person on our team is on it."""
        if s.my_t == INF:
            return False
        lead = margin + (12.0 if self._mine else 0.0)
        for b in s.calls.get("human", []):
            if s.mate_t[b] <= s.my_t + 20.0:
                return False
        for b in s.calls.get("ball", []):
            if s.mate_t[b] <= s.my_t + (4.0 if self._mine else 12.0):
                return False
        best = min(s.mate_t.values(), default=INF)
        return s.my_t <= best + lead

    def wants_ball(self, s) -> bool:
        return self.ball_is_mine(s)

    # ------------------------------------------------------------ guarding the goal
    def should_guard(self, s) -> bool:
        """Nobody calls cover, it is the deepest of the team (keeps the job while it has it), the ball is not ours to keep."""
        if not self.GUARDS or len(s.mates) == 0:
            return False
        if s.calls.get("cover") and not self._guarding:
            return False
        mx = s.x(s.me.pos) - (0.12 if self._guarding else 0.0)
        return mx <= s.deepest_mate_x() and not (s.have and s.x(s.ball) > 0.3)

    def guard(self, s):
        self._guarding = True
        d, k = kit.guard(s.v, s.me, s.ball, s.bvel, self.reaction_delay, self.set.get("sweep", 0.3))
        return Act(d, k, "cover", "clear" if k else "")

    # ------------------------------------------------------------ on the ball
    def on_ball(self, s):
        bp, t = kit.intercept(s.v, s.me, s.ball, s.bvel, self.reaction_delay)
        if s.v.tick - self._decided > self.think_ticks:
            self._target_mate = None
            self._kind, self._aim = self.choose(s, bp)
            self._err = self.rng.gauss(0.0, self.err_finish if self._kind == "shoot" else self.err_pass) if self._kind != "dribble" else 0.0
            self._decided = s.v.tick
        d = self._aim - bp
        if abs(d) < 1.0:
            d = complex(s.ax, 0.0)
        d = kit.aim_with_error(d, self._err)
        run, kick = kit.strike(s.v, s.me, bp, d, self._kind, s.bvel * (BALL_DAMPING ** min(t, 160.0)))
        return Act(run, kick, "ball", self._kind if kick else "")

    def choose(self, s, bp):
        """(kind, aim): shoot / pass / clear / long / dribble and where to. The archetypes decide."""
        return "dribble", self.dribble_aim(s, bp)

    # tools for choose
    def shot(self, s, bp):
        """(target, lane clearance, distance to goal) of the best shot from bp."""
        tgt, lane = kit.shot_target(s.v, s.opps, bp, s.opp_goal, s.ax, self.err_finish)
        if self.rng.random() > self.vision + 0.4:              # a poor eye sometimes picks a corner at random
            tgt = complex(tgt.real, self.rng.uniform(-(s.v.pitch.goal_half - 14.0), s.v.pitch.goal_half - 14.0))
            lane = kit.lane_clearance(s.opps, bp, tgt)
        return tgt, lane, abs(bp - s.opp_goal)

    def passes(self, s, bp, max_d=420.0, through=0.0):
        """Every playable pass from bp, best first: [(score, mate, aim)]. A mate calling "open" gets the ball to the feet, one
        calling "run" into the space ahead (`through` 0..1: how far ahead); the score likes progress, an open lane, a
        receiver with room and a call."""
        out = []
        scale = min(s.hw / 370.0, 1.2)
        for b in s.mates:
            dist = abs(b.pos - bp)
            if dist < 50.0 or dist > max_d * scale or b.is_human and dist > 300.0:
                continue
            lead = b.vel * min(kit.ball_time(dist), 40.0) * 0.8
            if b.intent == "run":
                lead += complex(s.ax, 0.0) * (40.0 + 90.0 * through)
            aim = kit.on_pitch(s.v, b.pos + lead, 15.0)
            lane = kit.lane_clearance(s.opps, bp, aim)
            if lane < lerp(16.0, 34.0, self.vision):
                continue
            margin = kit.pass_margin(s.opps, bp, aim)
            if margin < lerp(-45.0, -5.0, self.vision):
                continue
            room = min(kit.nearest(s.opps, b.pos)[0], 140.0)
            sc = (aim.real - bp.real) * s.ax * 0.4 + min(lane, 100.0) * 0.5 + room * 0.6 + clamp(margin, -40.0, 40.0) * 0.6
            sc += {"open": 45.0, "run": 35.0 + 50.0 * through, "cover": -60.0, "ball": -20.0}.get(b.intent, 0.0)
            out.append((sc, b, aim))
        out.sort(key=lambda x: -x[0])
        return out

    def pressure(self, s, bp) -> float:
        return kit.nearest(s.opps, bp)[0]

    def dribble_aim(self, s, bp, look=120.0, spread=0.38):
        return kit.open_heading(s.v, s.opps, bp, s.opp_goal, look * min(s.hw / 370.0, 1.3), spread, self.vision)

    def clear_aim(self, s, bp):
        """Away from our goal, to the nearer flank."""
        sy = 1.0 if bp.imag >= 0.0 else -1.0
        return complex(s.ax * s.hw * 0.4, sy * s.hh * 0.8)

    # ------------------------------------------------------------ off the ball
    def off_ball(self, s):
        return Act(kit.arrive(s.me, self.spot(s, self.home_spot(s))), intent="none")

    def home_spot(self, s, push=0.0, depth_shift=0.4):
        """A sensible place by default: its kickoff spot moved with the ball and with possession (`push` towards the goal)."""
        me = s.me
        fx = me.home.real + s.x(s.ball) * depth_shift + (0.15 if s.have else -0.05) + push
        fy = me.home.imag + (s.ball.imag / s.hh) * 0.25
        return complex(s.ax * clamp(fx, -0.9, 0.85) * s.hw, clamp(fy, -0.85, 0.85) * s.hh)

    def spot(self, s, target):
        """A target with this player's positioning inaccuracy (it drifts every 1.5 s), kept on the pitch."""
        if s.v.tick - self._noise_tick > 90:
            self._noise = complex(self.rng.gauss(0.0, 1.0), self.rng.gauss(0.0, 1.0)) * self.pos_noise * 0.5
            self._noise_tick = s.v.tick
        return kit.on_pitch(s.v, target + self._noise)

    def cover_spot(self, s, dist=110.0):
        """Between the ball and our goal, `dist` px from the ball."""
        back = min(dist * s.hw / 370.0, abs(s.ball - s.own_goal) - 45.0)
        return s.ball + (s.own_goal - s.ball) / max(abs(s.own_goal - s.ball), 1.0) * max(back, 0.0)

    def support_spot(self, s, ahead=80.0, side=90.0):
        """Free space near the ball to receive a pass: ahead of it and to one side, whichever is further from the opponents."""
        best, best_s = s.ball, -INF
        for dy in (-side, 0.0, side):
            p = kit.on_pitch(s.v, s.ball + complex(s.ax * ahead, dy) * min(s.hw / 370.0, 1.3), 25.0)
            sc = min(kit.nearest(s.opps, p)[0], 120.0) - 0.15 * abs(p - s.me.pos) - (40.0 if dy == 0.0 else 0.0)
            sc -= min(kit.nearest(s.mates, p)[0] < 60.0, 1) * 50.0
            if sc > best_s:
                best_s, best = sc, p
        return best

