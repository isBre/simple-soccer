"""Target man: the reference point up front. It holds a high central spot and calls "open" (play it into me); on the ball it
shields it with its body and lays it off to a teammate running past ("run") or the nearest open one; with its back free it turns
and shoots. It does not chase deep."""
from ...vec import clamp
from .. import kit
from ..agent import Act
from .base import RuleAgent


class TargetMan(RuleAgent):
    NAME = "Target man"
    DESCRIPTION = "Holds the ball up front with its back to goal, lays it off to runners, turns and shoots when free."
    SETTINGS = {"height": (0.62, "How high it holds"), "turn": (0.4, "Turns instead of laying off")}
    GUARDS = False

    def wants_ball(self, s):
        if s.x(s.my_pt) < -0.1:
            return self.ball_is_mine(s, margin=-10.0)
        return self.ball_is_mine(s, margin=5.0)

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        pressure = self.pressure(s, bp)
        free = pressure > 70.0 or all(s.x(o.pos) < s.x(bp) - 0.02 for o in s.opps if abs(o.pos - bp) < 120.0)
        if dist < 300.0 * min(s.hw / 370.0, 1.2) and (lane > 24.0 or (free and self.rng.random() < 0.5 + 0.5 * self.set["turn"])):
            return "shoot", tgt
        ps = self.passes(s, bp, max_d=280.0, through=0.4)
        lay = [p for p in ps if p[1].intent == "run"] or ps
        if lay and pressure < 80.0 + 60.0 * (1.0 - self.set["turn"]):
            self._target_mate = lay[0][1]
            return "pass", lay[0][2]
        # shield: keep the ball, step away from the nearest opponent
        _, o = kit.nearest(s.opps, bp)
        away = (bp - o.pos) if o is not None else complex(s.ax, 0.0)
        return "dribble", bp + away / max(abs(away), 1.0) * 120.0 + complex(s.ax * 40.0, 0.0)

    def off_ball(self, s):
        h = self.set["height"]
        if s.have:
            fx = clamp(max(h, s.x(s.ball) + 0.15), -0.1, 0.8)
            intent = "open"
        else:
            fx = clamp(h - 0.25, -0.1, 0.7)
            intent = "none"
        target = complex(s.ax * fx * s.hw, clamp(s.ball.imag * 0.25, -s.hh * 0.3, s.hh * 0.3))
        return Act(kit.arrive(s.me, self.spot(s, target)), intent=intent)
