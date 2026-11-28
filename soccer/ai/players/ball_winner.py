"""Ball winner: hunts the opponent with the ball. It goes for any ball an opponent has within its hunting range (calls "ball"
even when a teammate is a little closer: two on the carrier), comes in from the goal side, and once it wins the ball gives it
away at once to whoever calls "open" (or clears). With the ball ours it holds midfield behind the play."""
from ...core.vec import clamp, lerp
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class BallWinner(RuleAgent):
    NAME = "Ball winner"
    DESCRIPTION = "Hunts the opponent on the ball, wins it and lays it off at once to whoever calls for it."
    SETTINGS = {"range": (0.6, "How far it hunts"), "bite": (0.7, "Goes in even when a teammate is closer")}

    def wants_ball(self, s):
        if self.ball_is_mine(s, margin=4.0):
            return True
        hunt = (140.0 + 220.0 * self.set["range"]) * min(s.hw / 370.0, 1.2)
        if s.lost and abs(s.ball - s.me.pos) < hunt:
            # a second man on the carrier: unless a teammate already doubles up
            callers = len(s.calls.get("ball", []))
            return callers < 2 and s.my_t < min(s.mate_t.values(), default=1e9) + 40.0 * self.set["bite"]
        return False

    def on_ball(self, s):
        # with an opponent on the ball, come in from the goal side of it instead of chasing its back
        carrier_d, carrier = kit.nearest(s.opps, s.ball)
        if s.lost and carrier is not None and carrier_d < 30.0 and abs(s.ball - s.me.pos) > 45.0:
            gs = lerp(s.ball, s.own_goal, 0.12)
            return Act(kit.chase(s.me, gs), intent="ball")
        return super().on_ball(s)

    def choose(self, s, bp):
        ps = self.passes(s, bp, max_d=300.0)
        if ps:
            self._target_mate = ps[0][1]
            return "pass", ps[0][2]
        tgt, lane, dist = self.shot(s, bp)
        if dist < 220.0 and lane > 25.0:
            return "shoot", tgt
        if s.x(bp) < 0.0:
            return "clear", self.clear_aim(s, bp)
        return "dribble", self.dribble_aim(s, bp, look=80.0)

    def off_ball(self, s):
        if s.have:
            fx = clamp(s.x(s.ball) - 0.25, -0.55, 0.3)
            target = complex(s.ax * fx * s.hw, s.ball.imag * 0.5)
            return Act(kit.arrive(s.me, self.spot(s, target)), intent="none")
        return Act(kit.arrive(s.me, self.spot(s, self.cover_spot(s, 90.0))), intent="none")

