"""Poacher: lives on the shoulder of the last defender and finishes. It runs in behind (calls "run"), shoots at the first
chance, lays the ball off when it cannot, and leaves the defending to the others (it never guards the goal)."""
from ...vec import clamp
from .. import kit
from ..agent import Act
from .base import RuleAgent


class Poacher(RuleAgent):
    NAME = "Poacher"
    DESCRIPTION = "Lives on the last defender's shoulder, runs in behind and shoots at the first chance; barely defends."
    SETTINGS = {"greed": (0.7, "Shoots instead of passing"), "depth": (0.75, "How high it waits"), "drop": (0.2, "How far it drops without the ball")}
    GUARDS = False

    def wants_ball(self, s):
        # only balls in the attacking two thirds, or one that is clearly its
        if s.x(s.my_pt) < -0.3:
            return self.ball_is_mine(s, margin=-15.0)
        return self.ball_is_mine(s, margin=6.0)

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        reach = (330.0 + 80.0 * self.set["greed"]) * min(s.hw / 370.0, 1.2)
        if dist < reach * 0.55 or (dist < reach and lane > 22.0 - 14.0 * self.set["greed"]):
            return "shoot", tgt
        ps = self.passes(s, bp, max_d=260.0)
        if ps and (self.pressure(s, bp) < 50.0 or ps[0][1].intent in ("open", "run")):
            self._target_mate = ps[0][1]
            return "pass", ps[0][2]
        if dist < reach * 1.2:
            return "dribble", self.dribble_aim(s, bp, look=90.0, spread=0.3)
        return "dribble", self.dribble_aim(s, bp)

    def off_ball(self, s):
        # the line of the second-deepest opponent (the last defender in front of their goal guard)
        xs = sorted(s.x(o.pos) for o in s.opps)
        line = xs[-2] if len(xs) >= 2 else (xs[-1] if xs else 0.5)
        if s.have:
            fx = clamp(max(line - 0.02, s.x(s.ball) + 0.1), -0.2, 0.88) if line > s.x(s.ball) else clamp(s.x(s.ball) + 0.25, -0.2, 0.88)
            intent = "run" if fx > s.x(s.ball) + 0.15 else "open"
        else:
            fx = clamp(max(self.set["depth"] - 0.25 - 0.3 * self.set["drop"], s.x(s.ball) - 0.15 - 0.4 * self.set["drop"]), -0.3, 0.85)
            intent = "none"
        fy = clamp(s.ball.imag / s.hh * 0.35 + s.me.home.imag * 0.3, -0.45, 0.45)
        target = complex(s.ax * fx * s.hw, fy * s.hh)
        d = kit.chase(s.me, self.spot(s, target)) if intent == "run" and abs(target - s.me.pos) > 40.0 else kit.arrive(s.me, self.spot(s, target))
        return Act(d, intent=intent)
