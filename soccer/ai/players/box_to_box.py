"""Box-to-box: follows the phase of play. When we have the ball it supports the carrier ("open") and, once the ball is in the
attacking third, makes a late run into the box ("run"); when we lose it, it sprints back to a cover spot between the ball and our
goal. On the ball it weighs shot, pass and carry evenly."""
from ...core.vec import clamp
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class BoxToBox(RuleAgent):
    NAME = "Box-to-box"
    DESCRIPTION = "Joins every attack with late runs into the box and sprints back the moment the ball is lost."
    SETTINGS = {"engine": (0.7, "Runs up and down"), "shoot": (0.5, "Willing to shoot")}

    def wants_ball(self, s):
        return self.ball_is_mine(s, margin=2.0)

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        reach = (250.0 + 100.0 * self.set["shoot"]) * min(s.hw / 370.0, 1.2)
        if dist < reach and (lane > 24.0 or dist < reach * 0.45):
            return "shoot", tgt
        ps = self.passes(s, bp, max_d=400.0, through=0.4)
        pressure = self.pressure(s, bp)
        if ps and (pressure < 60.0 or (ps[0][2].real - bp.real) * s.ax > 40.0) and self.rng.random() < 0.75:
            self._target_mate = ps[0][1]
            return "pass", ps[0][2]
        if s.danger and pressure < 55.0:
            return "clear", self.clear_aim(s, bp)
        return "dribble", self.dribble_aim(s, bp)

    def off_ball(self, s):
        e = self.set["engine"]
        if s.have:
            if s.x(s.ball) > 0.3:                             # the late run into the box
                y = clamp(-s.ball.imag * 0.4, -s.v.pitch.goal_half * 1.5, s.v.pitch.goal_half * 1.5)
                target = complex(s.ax * (s.hw - 70.0 - 60.0 * (1.0 - e)), y)
                return Act(kit.chase(s.me, target) if abs(target - s.me.pos) > 50.0 else kit.arrive(s.me, target), intent="run")
            return Act(kit.arrive(s.me, self.spot(s, self.support_spot(s, ahead=60.0 + 60.0 * e))), intent="open")
        target = self.cover_spot(s, 90.0 + 60.0 * (1.0 - e))
        return Act(kit.rush(s.me, self.spot(s, target), 20.0), intent="none")
