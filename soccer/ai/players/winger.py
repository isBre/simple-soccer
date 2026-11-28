"""Winger: owns one touchline. With the ball ours it sprints up its flank ahead of the play (calls "run"); on the ball it runs
down the line until it reaches the box, then crosses low into it (to a teammate there, else across the goal mouth), and shoots
only from close. Without the ball it tracks back along its flank."""
from ...core.vec import clamp
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class Winger(RuleAgent):
    NAME = "Winger"
    DESCRIPTION = "Hugs a touchline, sprints forward, runs down the line and crosses low into the box."
    SETTINGS = {"width": (0.85, "How wide it stays"), "cut_in": (0.25, "Cuts inside to shoot"), "track": (0.4, "Tracks back")}
    GUARDS = False

    def side(self, s):
        return 1.0 if (s.me.home.imag if abs(s.me.home.imag) > 0.05 else (s.me.slot % 2) - 0.5) > 0 else -1.0

    def wants_ball(self, s):
        on_my_flank = s.my_pt.imag * self.side(s) > s.hh * 0.2
        return self.ball_is_mine(s, margin=5.0 if on_my_flank else 0.0)

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        if dist < 170.0 * (1.0 + self.set["cut_in"]) and lane > 18.0:
            return "shoot", tgt
        box_x = s.hw - max(s.v.pitch.box_depth, 90.0)
        if s.x(bp) * s.hw > box_x - 40.0:
            # the cross: a teammate in the box, else the far post area
            inbox = [b for b in s.mates if s.x(b.pos) * s.hw > box_x - 60.0 and abs(b.pos.imag) < s.v.pitch.goal_half * 2.2]
            if inbox:
                b = min(inbox, key=lambda b: abs(b.pos - s.opp_goal))
                self._target_mate = b
                return "pass", b.pos + b.vel * 12.0
            return "pass", complex(s.opp_goal.real - s.ax * 45.0, -self.side(s) * s.v.pitch.goal_half * 0.6)
        # down the line: aim along the flank, a little inside when somebody blocks it
        lane_y = self.side(s) * s.hh * (0.55 + 0.3 * self.set["width"])
        ahead = complex(bp.real + s.ax * 200.0, lane_y)
        blocked = kit.lane_clearance(s.opps, bp, ahead) < 26.0
        if blocked and self.pressure(s, bp) < 45.0:
            ps = self.passes(s, bp, max_d=300.0)
            if ps:
                self._target_mate = ps[0][1]
                return "pass", ps[0][2]
        if blocked and self.rng.random() < self.set["cut_in"]:
            return "dribble", self.dribble_aim(s, bp)
        return "dribble", ahead if not blocked else kit.open_heading(s.v, s.opps, bp, ahead, 110.0, 0.3, self.vision)

    def off_ball(self, s):
        y = self.side(s) * s.hh * (0.5 + 0.35 * self.set["width"])
        if s.have:
            fx = clamp(s.x(s.ball) + 0.3, -0.2, 0.82)
            target = complex(s.ax * fx * s.hw, y)
            far = abs(target - s.me.pos) > 50.0
            return Act(kit.chase(s.me, target) if far else kit.arrive(s.me, target), intent="run" if fx > s.x(s.ball) + 0.1 else "open")
        fx = clamp(s.x(s.ball) - 0.1 - 0.35 * self.set["track"], -0.6, 0.6)
        return Act(kit.arrive(s.me, self.spot(s, complex(s.ax * fx * s.hw, y * 0.85))), intent="none")
