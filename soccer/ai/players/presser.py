"""Presser: pressure everywhere. Without the ball it goes at the opponent on it when nobody else does ("ball"), otherwise at the
opponent most likely to receive next, standing in the passing lane between the carrier and that player. On the ball it plays forward
fast: a shot if there is one, else the first forward pass, else it drives on."""
from ...vec import lerp
from .. import kit
from ..agent import Act
from .base import RuleAgent


class Presser(RuleAgent):
    NAME = "Presser"
    DESCRIPTION = "Presses the carrier or cuts the passing lane to the next receiver; plays forward fast when it wins the ball."
    SETTINGS = {"intensity": (0.7, "How far it presses"), "cut": (0.6, "Cuts lanes instead of chasing")}

    def wants_ball(self, s):
        if self.ball_is_mine(s, margin=3.0):
            return True
        return s.lost and not s.calls.get("ball") and s.my_t < 60.0 + 80.0 * self.set["intensity"]

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        if dist < 280.0 * min(s.hw / 370.0, 1.2) and lane > 22.0:
            return "shoot", tgt
        fwd = [p for p in self.passes(s, bp, max_d=380.0, through=0.3) if (p[2].real - bp.real) * s.ax > 20.0]
        if fwd:
            self._target_mate = fwd[0][1]
            return "pass", fwd[0][2]
        return "dribble", self.dribble_aim(s, bp)

    def off_ball(self, s):
        if s.have:
            return Act(kit.arrive(s.me, self.spot(s, self.support_spot(s, ahead=110.0, side=110.0))), intent="open")
        # the next receiver: the opponent nearest the ball carrier who is not the carrier; stand in that lane
        _, carrier = kit.nearest(s.opps, s.ball)
        rest = [o for o in s.opps if o is not carrier]
        if carrier is None or not rest:
            return Act(kit.arrive(s.me, self.spot(s, self.cover_spot(s, 80.0))), intent="none")
        recv = min(rest, key=lambda o: abs(o.pos - carrier.pos) + 0.5 * abs(o.pos - s.me.pos))
        lane = lerp(carrier.pos, recv.pos, 0.45 + 0.25 * self.set["cut"])
        reach = (180.0 + 220.0 * self.set["intensity"]) * min(s.hw / 370.0, 1.2)
        target = lane if abs(lane - s.me.pos) < reach else self.cover_spot(s, 100.0)
        return Act(kit.rush(s.me, target, 14.0), intent="none")
