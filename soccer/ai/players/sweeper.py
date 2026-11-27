"""Sweeper: the last man. It stays deepest, calls "cover" and guards our goal (reads shots and runs onto their path, comes out
to narrow the angle), sweeps up balls played in behind the defence, and clears long, preferably to a teammate calling "run"."""
from ...vec import clamp
from .. import kit
from ..agent import Act
from .base import RuleAgent


class Sweeper(RuleAgent):
    NAME = "Sweeper"
    DESCRIPTION = "The last man: guards the goal, sweeps up balls behind the defence and clears long."
    SETTINGS = {"sweep": (0.4, "Comes out of goal"), "step_up": (0.3, "Steps up when we have the ball")}

    def wants_ball(self, s):
        # only a ball in our third that it reaches clearly first (it is the last man: no gambles)
        if s.x(s.my_pt) > -0.35 + 0.3 * self.set["step_up"]:
            return False
        return self.ball_is_mine(s, margin=-4.0) and s.my_t < s.opp_t - 6.0

    def should_guard(self, s):
        if not s.mates:
            return False
        # another sweeper (someone calling cover deeper than it) keeps the goal; otherwise it is the guard
        for b in s.calls.get("cover", []):
            if s.x(b.pos) < s.x(s.me.pos) - 0.1:
                return False
        return not (s.have and s.x(s.ball) > 0.2)

    def choose(self, s, bp):
        runs = [p for p in self.passes(s, bp, max_d=520.0, through=0.6) if p[1].intent in ("run", "open")]
        if runs and runs[0][0] > 20.0:
            self._target_mate = runs[0][1]
            return "pass", runs[0][2]
        return "clear", self.clear_aim(s, bp)

    def off_ball(self, s):
        # we have the ball high up: step up behind the play, still the last man
        fx = clamp(s.x(s.ball) - 0.55 + 0.25 * self.set["step_up"], -0.85, -0.1)
        target = complex(s.ax * fx * s.hw, s.ball.imag * 0.3)
        return Act(kit.arrive(s.me, self.spot(s, target)), intent="cover")
