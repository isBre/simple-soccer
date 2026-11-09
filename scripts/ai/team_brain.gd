class_name TeamBrain
extends RefCounted
## Team-level coordination shared by the bots of one team: who chases the
## ball, who is the carrier, who marks whom, pass targets.

var team := 0
var style: StyleDef
var has_possession := false
var opp_possession := false
var danger := false                    # ball in our defensive third
var lost_tick := -999                   # when we last lost possession (counter-press window)
var _had_possession := false
var interceptor: SimPlayer = null       # off-ball player sent to cut out an opponent's pass / shot
var intercept_pt := Vector2.ZERO
var urgency := 0.0                     # game management: >0 chase the game (behind late), <0 protect a lead
var chasers: Array[SimPlayer] = []
var carrier: SimPlayer = null
var pass_target: SimPlayer = null
var pass_tick := -999
var marks: Dictionary = {}             # slot -> SimPlayer (opponent to mark)
var keeper: SimPlayer = null           # whoever is guarding the goal right now (any player can)


## Ball physics is fixed (a kick adds exactly KICK_STRENGTH, damping 0.99 per tick), so its path is predictable.
## Ball position after t ticks (walls ignored, clamped to the pitch).
static func ball_at_t(sim: MatchSim, bpos: Vector2, bvel: Vector2, t: float) -> Vector2:
    var q := (1.0 - pow(0.99, t)) / 0.01
    var pd := sim.pitch
    return Vector2(clampf(bpos.x + bvel.x * q, -pd.half_w + 12.0, pd.half_w - 12.0),
        clampf(bpos.y + bvel.y * q, -pd.half_h + 12.0, pd.half_h - 12.0))


## Distance a player covers in t ticks (accel 0.1, damping 0.96: top speed 2.4 px/tick, 24-tick time constant).
static func reach_dist(p: SimPlayer, along: float, t: float) -> float:
    var te := maxf(t - float(p.reaction_delay) - 2.0, 0.0)
    return 2.4 * te + (along - 2.4) * 24.0 * (1.0 - exp(-te / 24.0))


## Earliest point on the ball's path the player can get to: Vector3(x, y, ticks); ticks = INF if none within 160.
static func intercept(sim: MatchSim, p: SimPlayer, bpos: Vector2, bvel: Vector2) -> Vector3:
    var touch := p.radius + sim.ball.radius
    var t := 1.0
    while t <= 160.0:
        var bp := ball_at_t(sim, bpos, bvel, t)
        var dv := bp - p.pos
        var dl := dv.length()
        var along := p.vel.dot(dv / maxf(dl, 1.0))
        if reach_dist(p, along, t) >= dl - touch * 0.6:
            return Vector3(bp.x, bp.y, t)
        t += 2.0
    var e := ball_at_t(sim, bpos, bvel, 160.0)
    return Vector3(e.x, e.y, INF)


func reset() -> void:
    interceptor = null
    _had_possession = false
    lost_tick = -999
    chasers = []
    carrier = null
    pass_target = null
    marks.clear()
    keeper = null
    has_possession = false
    opp_possession = false


## The keeper is the rearmost non-chasing player. The nominal GK slot gets a head start that
## shrinks with style.fluidity (0 = fixed goalkeeper, 1 = anyone can keep goal); the current keeper
## keeps the job unless someone else is clearly deeper (no flicker).
func _pick_keeper(sim: MatchSim, mates: Array, ax: float) -> void:
    if mates.size() <= 1:
        keeper = null
        return
    if keeper != null and keeper.is_human:
        keeper = null          # the human decides for himself where to stand
    if keeper == null:
        for m in mates:
            if (m as SimPlayer).role == "GK" and not (m as SimPlayer).is_human:
                keeper = m
        if keeper == null:
            for m in mates:
                if not (m as SimPlayer).is_human:
                    keeper = m
                    break
    var own_x := -ax * sim.pitch.half_w
    var best: SimPlayer = null
    var best_s := INF
    for m in mates:
        var sp: SimPlayer = m
        if sp.is_human or (chasers.has(sp) and sp != keeper):
            continue
        var depth := (sp.pos.x - own_x) * ax
        var s := depth
        if sp.role == "GK":
            s -= 260.0 * (1.0 - style.fluidity)
        elif sp.role == "FWD":
            s += 40.0
        if sp == keeper:
            s -= 50.0
        if s < best_s:
            best_s = s
            best = sp
    if best != null:
        keeper = best


func update(sim: MatchSim) -> void:
    var ball := sim.ball
    var ax := sim.attack_dir(team)
    var mates: Array = sim.team_lists[team]
    var opps: Array = sim.team_lists[1 - team]
    var lt := sim.last_touch
    has_possession = lt != null and lt.team == team
    opp_possession = lt != null and lt.team != team
    danger = ball.pos.x * -ax > sim.pitch.half_w * 0.4
    if _had_possession and not has_possession:
        lost_tick = sim.tick
    _had_possession = has_possession
    # game management: in the last ~45% of the match a team that is behind pushes up and shoots earlier,
    # a team that is ahead drops deeper and keeps the ball
    var behind: int = sim.scores[1 - team] - sim.scores[team]
    var elapsed_frac := 1.0 - sim.time_left / maxf(sim.cfg.duration, 1.0)
    urgency = clampf(float(behind) * 0.5, -1.0, 1.0) * clampf((elapsed_frac - 0.55) / 0.35, 0.0, 1.0)

    if pass_target != null and (sim.tick - pass_tick > 90 or lt == pass_target or not has_possession):
        pass_target = null

    if keeper == null and mates.size() > 1:
        _pick_keeper(sim, mates, ax)
    var prev := chasers
    chasers = []
    var human_has_ball := false
    # a human-controlled player is not ours to command: when he is the one at the ball the bots
    # leave it to him (no second chaser running into him) and just support
    var human: SimPlayer = null
    for m in mates:
        if (m as SimPlayer).is_human:
            human = m
    if pass_target != null and not pass_target.is_human:
        chasers.append(pass_target)
    else:
        var scale := sim.pitch.half_w / 370.0
        var n_max := 1
        if not has_possession:
            if style.press >= 0.25:
                n_max += 1
            if style.press >= 0.8:
                n_max += 1
        # attacking third: a second player follows the carrier for rebounds and tap-ins
        if has_possession and mates.size() >= 4 and ball.pos.x * ax > sim.pitch.half_w * 0.3:
            n_max = maxi(n_max, 2)
        if not has_possession and mates.size() >= 4:
            # the ball is in our half: more defenders close in on the carrier (cover instead of a single lunge)
            var depth := ball.pos.x * -ax / sim.pitch.half_w
            if depth > 0.45:
                n_max = maxi(n_max, 2)
            if depth > 0.7:
                n_max = maxi(n_max, 3)
        if not has_possession and style.counter_press > 0.05 and mates.size() >= 3 \
                and sim.tick - lost_tick < int(150.0 * style.counter_press):
            n_max += 1       # gegenpress: win the ball back straight after losing it
        if urgency > 0.5 and not has_possession and mates.size() >= 4:
            n_max += 1       # chasing the game: press with one more player
        n_max = mini(n_max, maxi(1, mates.size() - 1))
        if human != null:
            var hd := human.pos.distance_to(ball.pos)
            var bot_best := INF
            for m in mates:
                if not (m as SimPlayer).is_human and m != keeper:
                    bot_best = minf(bot_best, (m as SimPlayer).pos.distance_to(ball.pos))
            if hd < bot_best + 70.0 or hd < 90.0:
                human_has_ball = true
                n_max = 0 if has_possession else maxi(0, n_max - 1)
        var press_radius := (70.0 + style.press * 230.0) * scale
        var cand: Array = []
        for m in mates:
            var sp: SimPlayer = m
            if sp.is_human:
                continue
            var d := sp.pos.distance_to(ball.pos)
            if sp == keeper and mates.size() > 1:
                var reach := (110.0 + style.keeper_sweep * 130.0) * scale
                if not (danger and absf(ball.pos.y) < sim.pitch.goal_half * 2.4 and d < reach):
                    continue
                if (ball.pos.x - sp.pos.x) * ax < 8.0:
                    continue      # ball is behind / level with the keeper: stay on the line
                # only charge when he wins the race to the ball; against a dribbler who is closer he
                # stays between ball and goal and narrows the angle instead
                var opp_d := INF
                for o in opps:
                    opp_d = minf(opp_d, (o as SimPlayer).pos.distance_to(ball.pos))
                if d > opp_d - 12.0:
                    continue
            if prev.has(sp):
                d -= 25.0
            cand.append([d, sp])
        cand.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0])
        for i in mini(n_max, cand.size()):
            if i > 0 and cand[i][0] > press_radius:
                break
            chasers.append(cand[i][1])
    carrier = chasers[0] if (has_possession and not chasers.is_empty()) else null
    if has_possession and human_has_ball:
        carrier = human
    _pick_keeper(sim, mates, ax)
    _assign_marks(sim, mates, opps, ax)
    _pick_interceptor(sim, mates, ball)


## After an opponent's kick, the off-ball player who can reach the ball's path first (and clearly before the
## chasers can) runs onto it. Eagerness comes from the style, ability from the player's defending.
func _pick_interceptor(sim: MatchSim, mates: Array, ball: Disc) -> void:
    interceptor = null
    if style.intercept <= 0.05 or not opp_possession or ball.vel.length() < 1.2:
        return
    var chaser_t := INF
    for c in chasers:
        chaser_t = minf(chaser_t, intercept(sim, c, ball.pos, ball.vel).z)
    var best_t := INF
    for m in mates:
        var sp: SimPlayer = m
        if sp.is_human or sp == keeper or chasers.has(sp):
            continue
        var r := intercept(sim, sp, ball.pos, ball.vel)
        var limit := (25.0 + 70.0 * style.intercept) * lerpf(0.6, 1.0, sp.defend_q)
        if r.z <= limit and r.z < best_t and r.z < chaser_t - 6.0:
            best_t = r.z
            interceptor = sp
            intercept_pt = Vector2(r.x, r.y)


func _assign_marks(sim: MatchSim, mates: Array, opps: Array, ax: float) -> void:
    marks.clear()
    if has_possession:
        return
    var free: Array = []
    for m in mates:
        var sp: SimPlayer = m
        if sp == keeper or chasers.has(sp) or sp.is_human:
            continue
        if sp.role == "FWD" and style.forward_stay > 0.5:
            continue
        free.append(sp)
    if free.is_empty():
        return
    var own_goal := Vector2(-ax * sim.pitch.half_w, 0.0)
    var threats: Array = []
    for o in opps:
        var op: SimPlayer = o
        if op == sim.brains[1 - team].keeper and opps.size() > 1:
            continue
        threats.append([op.pos.distance_to(own_goal), op])
    threats.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0])
    for th in threats:
        if free.is_empty():
            break
        var opp: SimPlayer = th[1]
        var best: SimPlayer = null
        var bd := INF
        for f in free:
            var fp: SimPlayer = f
            var d := fp.pos.distance_to(opp.pos)
            if d < bd:
                bd = d
                best = fp
        marks[best.slot] = opp
        free.erase(best)
