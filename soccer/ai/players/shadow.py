"""Shadow: a man-marker. It picks the most dangerous opponent (close to our goal, running at it, not their deepest player) and
stays goal-side of that player; a pass towards that player it reads early and steps in front to cut it out. On the ball it keeps things simple:
the safest pass, else a clearance."""
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class Shadow(RuleAgent):
    NAME = "Shadow"
    DESCRIPTION = "Marks the most dangerous opponent goal-side, reads passes meant for that player and cuts them out."
    SETTINGS = {"tight": (0.7, "How tight it marks"), "read": (0.6, "Steps in to intercept")}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mark = None                 # the body it marks (it switches only to a clearly bigger threat)

    def wants_ball(self, s):
        return self.ball_is_mine(s, margin=1.0)

    def threat(self, s, o):
        d = abs(o.pos - s.own_goal)
        towards = -(o.vel.real * s.ax)
        return -d + 40.0 * max(towards, 0.0) - (300.0 if o is s.v.deepest(1 - s.me.team) and len(s.opps) > 1 else 0.0)

    def choose(self, s, bp):
        ps = self.passes(s, bp, max_d=320.0)
        safe = [p for p in ps if p[1].intent != "cover"]
        if safe and self.pressure(s, bp) < 90.0:
            self._target_mate = safe[0][1]
            return "pass", safe[0][2]
        if s.x(bp) < 0.1:
            return "clear", self.clear_aim(s, bp)
        return "dribble", self.dribble_aim(s, bp, look=80.0)

    def off_ball(self, s):
        if not s.opps:
            return super().off_ball(s)
        best = max(s.opps, key=lambda o: self.threat(s, o))
        if self._mark is None or self.threat(s, best) > self.threat(s, self._mark) + 60.0:
            self._mark = best
        o = self._mark
        if s.have:                                        # ours: stay near that player anyway, a little off (ready if we lose it)
            return Act(kit.arrive(s.me, self.spot(s, kit.goal_side(s.v, s.me.team, o.pos, s.ball, 0.2))), intent="none")
        # a ball travelling that way: step into its path in front of the mark
        if abs(s.bvel) > 1.5 and self.set["read"] > 0.05:
            pt, t = kit.intercept(s.v, s.me, s.ball, s.bvel, self.reaction_delay)
            if t < (20.0 + 60.0 * self.set["read"]) * (0.6 + 0.4 * self.defend_q) and abs(pt - o.pos) < 120.0:
                return Act(kit.chase(s.me, pt) if abs(pt - s.me.pos) > 14.0 else kit.arrive(s.me, pt), intent="ball")
        target = kit.goal_side(s.v, s.me.team, o.pos + o.vel * 8.0, s.ball, self.set["tight"] * (0.6 + 0.4 * self.defend_q))
        return Act(kit.rush(s.me, target, 12.0), intent="none")

