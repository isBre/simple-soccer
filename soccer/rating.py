"""Values of single actions: expected goals of a shot and the impact of a pass (the pass value feeds the RL rewards and the
stats). There are no player grades: a player's strength is measured by its Elo (lab/ladder.py)."""
import math

from .stats import snapped


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def shot_xg(frm: complex, goal_x: float, goal_half: float) -> float:
    """Expected goals of a shot: grows with the angle the goal mouth subtends from the shooting spot
    (~0.7 from the six-yard box, ~0.2 from 300 px, ~0.08 from the halfway line)."""
    dx = max(abs(goal_x - frm.real), 1.0)
    ang = abs(math.atan2(goal_half - frm.imag, dx) - math.atan2(-goal_half - frm.imag, dx))
    return clamp(math.pow(ang / 1.8, 1.6) * 0.75, 0.01, 0.8)


def pass_value(ok: bool, gain: float, fwd_intent: bool, pressed: bool, from_norm: float, prog_thr: float) -> float:
    """Impact of one pass. gain = px gained towards the opponent goal (completed passes), fwd_intent = played forwards
    (failed ones), pressed = an opponent was close, from_norm = where it started (-1 own goal line .. +1 opponent's)."""
    if ok:
        v = 0.012
        if gain >= prog_thr:
            v += 0.05 + min((gain - prog_thr) / (prog_thr * 4.0), 0.04)
        if pressed:
            v += 0.03
        return v
    cost = 0.05
    if from_norm < -0.33:
        cost *= 1.8        # losing it in front of your own goal is dangerous
    elif from_norm > 0.33:
        cost *= 0.45       # a failed through-ball up front is cheap
    if fwd_intent:
        cost *= 0.65       # at least it was ambitious
    if pressed:
        cost *= 0.6
    return -cost
