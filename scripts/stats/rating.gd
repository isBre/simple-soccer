class_name Rating
extends RefCounted
## Turns match events into a 1-10 grade (like newspaper player ratings).
##
## The grade is 6.0 plus an "impact" that is summed from many small contributions, so a match-winning
## striker, a ball-winning defender, a creative midfielder and a keeper are all judged on what they
## actually did. Impact is then squeezed with a soft curve so that 9+ needs a truly outstanding game and
## nobody drops below 3. Weights live here only; the simulation just feeds in events.

const BASE := 6.0
## Calibrated with bot-vs-bot batches (experiments/) so every role averages about 6.4.
const ROLE_OFFSET := {"GK": 0.0, "DEF": -0.25, "MID": -1.3, "FWD": -1.5}


## Expected-goals of a shot: grows with the angle the goal mouth subtends from the shooting spot.
## (~0.7 from the six-yard box, ~0.2 from 300 px, ~0.08 from the halfway line)
static func shot_xg(from: Vector2, goal_x: float, goal_half: float) -> float:
    var dx := maxf(absf(goal_x - from.x), 1.0)
    var ang := absf(atan2(goal_half - from.y, dx) - atan2(-goal_half - from.y, dx))
    return clampf(pow(ang / 1.8, 1.6) * 0.75, 0.01, 0.8)


## Impact of one pass. `gain` = px gained towards the opponent goal (completed passes),
## `fwd_intent` = it was played forwards (failed ones), `pressed` = an opponent was close when it was
## played, `from_norm` = where it started, -1 own goal line .. +1 opponent goal line.
static func pass_value(ok: bool, gain: float, fwd_intent: bool, pressed: bool, from_norm: float,
        prog_thr: float) -> float:
    if ok:
        var v := 0.012
        if gain >= prog_thr:
            v += 0.05 + minf((gain - prog_thr) / (prog_thr * 4.0), 0.04)
        if pressed:
            v += 0.03
        return v
    var cost := 0.05
    if from_norm < -0.33:
        cost *= 1.8        # losing it in front of your own goal is dangerous
    elif from_norm > 0.33:
        cost *= 0.45       # a failed through-ball up front is cheap
    if fwd_intent:
        cost *= 0.65       # at least it was ambitious
    if pressed:
        cost *= 0.6
    return -cost


static func grade(role: String, st: PlayerMatchStats, team_won: bool, team_lost: bool,
        goals_against: int) -> float:
    var imp: float = ROLE_OFFSET.get(role, 0.0)

    # --- result of the team
    if team_won:
        imp += 0.4
    elif team_lost:
        imp -= 0.3

    # --- finishing and chance creation
    var goal_w := 1.0
    match role:
        "MID": goal_w = 1.1
        "DEF": goal_w = 1.3
        "GK": goal_w = 2.0
    imp += st.goals * goal_w
    imp += st.xg * 0.45                                   # credit for getting into scoring positions
    imp -= (st.big_chances - st.big_scored) * 0.2         # missed sitters hurt
    imp -= (st.shots - st.shots_on_target) * 0.05
    imp += st.assists * 0.8 + st.key_passes * 0.12 + st.xa * 0.6
    imp -= st.own_goals * 1.2

    # --- passing: every pass counts for what it was worth, plus overall reliability
    imp += st.pass_value
    if st.passes() >= 8:
        imp += (st.pass_accuracy() - 0.72) * 0.8

    # --- carrying the ball and duels
    imp += st.dribbles * 0.22 + minf(st.carry_dist * 0.0006, 0.35)
    imp -= st.dispossessed * (0.05 if role == "FWD" else 0.08)

    # --- defending (diminishing returns so spamming tackles cannot carry a grade alone)
    var tw := 0.12
    var iw := 0.10
    var rw := 0.03
    var cw := 0.05
    match role:
        "DEF":
            tw = 0.18
            iw = 0.16
            rw = 0.04
            cw = 0.07
        "FWD":
            tw = 0.10
            iw = 0.09
            rw = 0.03
            cw = 0.0
        "GK":
            tw = 0.15
            iw = 0.15
            rw = 0.04
            cw = 0.06
    var d := st.tackles * tw + st.interceptions * iw + st.recoveries * rw + st.blocks * 0.25 \
        + st.clearances * cw
    imp += 1.8 * (1.0 - exp(-d / 1.8))

    # --- goalkeeping: harder saves are worth more, goals from good chances hurt less than sitters
    if role == "GK":
        imp += st.saves * 0.12 + st.save_xg * 1.0
        imp -= st.conceded_xg * 0.5

    # --- what happened to the team's goal while on the pitch
    var concede_w := 0.02
    var cs_bonus := 0.0
    match role:
        "GK":
            concede_w = 0.25
            cs_bonus = 0.7
        "DEF":
            concede_w = 0.2
            cs_bonus = 0.45
        "MID":
            concede_w = 0.1
            cs_bonus = 0.15
    imp -= st.conceded * concede_w
    if goals_against == 0:
        imp += cs_bonus

    var g: float
    if imp >= 0.0:
        g = BASE + 4.0 * (1.0 - exp(-imp / 2.6))
    else:
        g = BASE - 3.0 * (1.0 - exp(imp / 2.6))
    return snappedf(clampf(g, 3.0, 10.0), 0.1)
