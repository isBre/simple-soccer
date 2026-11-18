"""Turns match events into a 1-10 grade (like newspaper player ratings): 6.0 plus an "impact" summed from many small
contributions, squeezed with a soft curve so 9+ needs a truly outstanding game and nobody drops below 3."""
import math

from .stats import snapped

BASE = 6.0
# Calibrated with bot-vs-bot batches so every role averages about 6.4.
ROLE_OFFSET = {"GK": 0.0, "DEF": -0.25, "MID": -1.3, "FWD": -1.5}


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


def grade(role, st, team_won, team_lost, goals_against) -> float:
    imp = ROLE_OFFSET.get(role, 0.0)
    # result of the team
    if team_won:
        imp += 0.4
    elif team_lost:
        imp -= 0.3
    # finishing and chance creation
    goal_w = {"MID": 1.1, "DEF": 1.3, "GK": 2.0}.get(role, 1.0)
    imp += st.goals * goal_w
    imp += st.xg * 0.45                                   # credit for getting into scoring positions
    imp -= (st.big_chances - st.big_scored) * 0.2         # missed sitters hurt
    imp -= (st.shots - st.shots_on_target) * 0.05
    imp += st.assists * 0.8 + st.key_passes * 0.12 + st.xa * 0.6
    imp -= st.own_goals * 1.2
    # passing: every pass counts for what it was worth, plus overall reliability
    imp += st.pass_value
    if st.passes() >= 8:
        imp += (st.pass_accuracy() - 0.72) * 0.8
    # carrying the ball and duels
    imp += st.dribbles * 0.22 + min(st.carry_dist * 0.0006, 0.35)
    imp -= st.dispossessed * (0.05 if role == "FWD" else 0.08)
    # defending (diminishing returns so spamming tackles cannot carry a grade alone)
    tw, iw, rw, cw = {"DEF": (0.18, 0.16, 0.04, 0.07), "FWD": (0.10, 0.09, 0.03, 0.0),
                      "GK": (0.15, 0.15, 0.04, 0.06)}.get(role, (0.12, 0.10, 0.03, 0.05))
    d = st.tackles * tw + st.interceptions * iw + st.recoveries * rw + st.blocks * 0.25 + st.clearances * cw
    imp += 1.8 * (1.0 - math.exp(-d / 1.8))
    # goalkeeping: harder saves are worth more, goals from good chances hurt less than sitters
    if role == "GK":
        imp += st.saves * 0.12 + st.save_xg * 1.0
        imp -= st.conceded_xg * 0.5
    # what happened to the team's goal while on the pitch
    concede_w, cs_bonus = {"GK": (0.25, 0.7), "DEF": (0.2, 0.45), "MID": (0.1, 0.15)}.get(role, (0.02, 0.0))
    imp -= st.conceded * concede_w
    if goals_against == 0:
        imp += cs_bonus
    if imp >= 0.0:
        g = BASE + 4.0 * (1.0 - math.exp(-imp / 2.6))
    else:
        g = BASE - 3.0 * (1.0 - math.exp(imp / 2.6))
    return snapped(clamp(g, 3.0, 10.0), 0.1)
