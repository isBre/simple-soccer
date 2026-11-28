"""Playmaker: the one who passes. It drops off to receive (calls "open" in a free pocket behind the ball), looks first for a
teammate running in behind (a through ball into the space ahead of a "run"), then for the best open teammate, and rarely shoots.
Without the ball it screens in front of the defence, between the ball and our goal."""
from ...core.vec import clamp
from .. import kit
from ...core.act import Act
from .base import RuleAgent


class Playmaker(RuleAgent):
    NAME = "Playmaker"
    DESCRIPTION = "Drops deep to receive, finds runners with through balls, rarely shoots; screens the defence without the ball."
    SETTINGS = {"vision_bias": (0.7, "Looks for the through ball"), "patience": (0.5, "Keeps the ball instead of forcing it"),
                "shoot": (0.25, "Willing to shoot")}

    def wants_ball(self, s):
        return self.ball_is_mine(s, margin=2.0)

    def choose(self, s, bp):
        tgt, lane, dist = self.shot(s, bp)
        if dist < 200.0 * (1.0 + self.set["shoot"]) and lane > 40.0 - 20.0 * self.set["shoot"]:
            return "shoot", tgt
        ps = self.passes(s, bp, max_d=480.0, through=self.set["vision_bias"])
        runs = [p for p in ps if p[1].intent == "run"]
        if runs and runs[0][0] > ps[0][0] - 40.0 * self.set["vision_bias"]:
            self._target_mate = runs[0][1]
            return "pass", runs[0][2]
        pressure = self.pressure(s, bp)
        if ps and (pressure < 70.0 or ps[0][0] > 60.0 - 50.0 * self.set["patience"] or (ps[0][2].real - bp.real) * s.ax > 60.0):
            self._target_mate = ps[0][1]
            return "pass", ps[0][2]
        if s.danger and pressure < 60.0:
            return "clear", self.clear_aim(s, bp)
        # shield: carry it into the space with the most room, sideways if need be
        return "dribble", self.dribble_aim(s, bp, look=90.0, spread=0.55)

    def off_ball(self, s):
        me = s.me
        if s.have:
            # a pocket 90-150 px behind the ball, to the side with the most room: always available
            best, best_s = s.ball, -1e9
            for dx in (-0.25, -0.15):
                for dy in (-0.35, 0.0, 0.35):
                    p = kit.on_pitch(s.v, s.ball + complex(s.ax * dx * s.hw, dy * s.hh), 30.0)
                    sc = min(kit.nearest(s.opps, p)[0], 130.0) + kit.lane_clearance(s.opps, s.ball, p) * 0.5 - 0.12 * abs(p - me.pos)
                    sc -= 60.0 if kit.nearest(s.mates, p)[0] < 70.0 else 0.0
                    if sc > best_s:
                        best_s, best = sc, p
            return Act(kit.arrive(me, self.spot(s, best)), intent="open")
        # screen: in front of our deepest player, on the line ball - goal
        fx = clamp(min(s.x(s.ball) - 0.25, 0.1), -0.6, 0.2)
        line = self.cover_spot(s, 140.0)
        target = complex(s.ax * fx * s.hw, line.imag * 0.7)
        return Act(kit.arrive(me, self.spot(s, target)), intent="none")
