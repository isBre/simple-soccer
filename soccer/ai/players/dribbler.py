"""Dribbler: wants the ball at its feet and takes people on. It carries the ball on curving paths around the defenders (it looks
further ahead and turns harder than anyone), shoots once it has beaten its man, and passes only when it is cornered. Without the
ball it drifts into the half-space near the ball and calls "open"."""
from ...core.vec import clamp
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class Dribbler(RuleAgent):
    NAME = "Dribbler"
    DESCRIPTION = "Carries the ball past defenders on curving runs, shoots after beating a man, passes only when cornered."
    SETTINGS = {"daring": (0.7, "Takes people on"), "shoot": (0.5, "Willing to shoot")}

    def wants_ball(self, s):
        return self.ball_is_mine(s, margin=8.0 * self.set["daring"])

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        beaten = all(s.x(o.pos) < s.x(bp) for o in s.opps if abs(o.pos - bp) > 1.0 and s.x(o.pos) < 0.95)
        reach = (300.0 + 60.0 * self.set["shoot"]) * min(s.hw / 370.0, 1.2)
        if dist < reach and (lane > 28.0 - 12.0 * self.set["shoot"] or beaten or dist < reach * 0.4):
            return "shoot", tgt
        pressure = self.pressure(s, bp)
        cornered = pressure < 30.0 + 20.0 * (1.0 - self.set["daring"]) and abs(bp.imag) > s.hh * 0.6
        if cornered or (pressure < 25.0 and s.danger):
            ps = self.passes(s, bp, max_d=260.0)
            if ps:
                self._target_mate = ps[0][1]
                return "pass", ps[0][2]
            return "clear", self.clear_aim(s, bp)
        return "dribble", self.dribble_aim(s, bp, look=150.0 + 50.0 * self.set["daring"], spread=0.45)

    def off_ball(self, s):
        side = 1.0 if (s.me.home.imag or 0.1) > 0 else -1.0
        if s.have:
            fx = clamp(s.x(s.ball) + 0.12, -0.3, 0.75)
            target = complex(s.ax * fx * s.hw, side * s.hh * 0.4)
            return Act(kit.arrive(s.me, self.spot(s, target)), intent="open")
        target = self.home_spot(s, push=0.05)
        return Act(kit.arrive(s.me, self.spot(s, target)), intent="none")
