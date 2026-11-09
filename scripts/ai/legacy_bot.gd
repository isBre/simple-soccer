extends BotController
## FROZEN COPY of the original StyleBot (before the AI rework). Only used as a benchmark opponent:
## MatchConfig.legacy_bot[team] = true makes a team play with this bot (experiments mode "versus").
## Do not improve this file; it exists so that progress can be measured head to head.
## Rule-based bot driven by a StyleDef (tactics) and the player's attributes.
## Roles: goalkeeper / chaser (plays the ball: shoot, pass, dribble, clear) /
## off-ball (formation shape, supporting runs, marking).

## keeper depth tuning (see _keeper); static so experiments can sweep them
static var KEEP_F := 0.3
static var KEEP_FS := 0.3
static var KEEP_CAP := 60.0
static var KEEP_CAPS := 160.0
static var KEEP_FAR := 600.0

var style: StyleDef
var rng: RandomNumberGenerator

var _kind := "dribble"
var _aim := Vector2.ZERO
var _kick := false
var _mate: SimPlayer = null
var _decided := -999
var _err := 0.0
var _noise := Vector2.ZERO
var _noise_tick := -999


func _init(s: StyleDef, r: RandomNumberGenerator) -> void:
    style = s
    rng = r


func decide(sim: MatchSim, p: SimPlayer) -> void:
    p.input_kick = false
    p.kick_intent = ""
    p.input_dir = Vector2.ZERO
    var brain: TeamBrain = sim.brains[p.team]
    var bpos: Vector2 = sim.ball_at(p.reaction_delay)
    var bold: Vector2 = sim.ball_at(p.reaction_delay + 4)
    var bvel: Vector2 = (bpos - bold) / 4.0
    var is_chaser: bool = brain.chasers.has(p)

    if sim.kickoff_active:
        if p == sim.kickoff_taker:
            # taker stands right behind the ball: wait a random few ticks, then kick
            p.input_dir = Vector2.ZERO
            if sim.tick >= sim.kickoff_go:
                p.input_kick = true
                p.kick_intent = "pass"
        else:
            _arrive(p, p.spawn)
        return
    if brain.keeper == p and not is_chaser and sim.team_lists[p.team].size() > 1:
        _keeper(sim, p, brain, bpos, bvel)
    elif is_chaser:
        _go_for_ball(sim, p, brain, bpos, bvel)
    else:
        _off_ball(sim, p, brain, bpos)
    _avoid_human(sim, p)


## Bots give their human-controlled teammate some room instead of bumping into him.
func _avoid_human(sim: MatchSim, p: SimPlayer) -> void:
    var h := sim.controlled
    if h == null or h == p or h.team != p.team or not h.is_human:
        return
    var off := p.pos - h.pos
    var d := off.length()
    if d >= 66.0:
        return
    var push := off / maxf(d, 1.0) * (1.0 - d / 66.0) * 1.8
    p.input_dir = (p.input_dir + push).limit_length(1.0)


# ---------------------------------------------------------------- ball play

func _go_for_ball(sim: MatchSim, p: SimPlayer, brain: TeamBrain, bpos: Vector2, bvel: Vector2) -> void:
    var pd := sim.pitch
    var t := clampf(p.pos.distance_to(bpos) / 3.0, 0.0, 30.0)
    var bp := bpos + bvel * ((1.0 - pow(0.99, t)) / 0.01)
    bp.x = clampf(bp.x, -pd.half_w + 12.0, pd.half_w - 12.0)
    bp.y = clampf(bp.y, -pd.half_h + 12.0, pd.half_h - 12.0)
    if sim.tick - _decided > 10:
        _decide_action(sim, p, brain, bp)
        _decided = sim.tick
    _play_ball(sim, p, brain, bp)


func _decide_action(sim: MatchSim, p: SimPlayer, brain: TeamBrain, bp: Vector2) -> void:
    var ax := sim.attack_dir(p.team)
    var pd := sim.pitch
    var opp_goal := Vector2(ax * pd.half_w, 0.0)
    var d_goal := bp.distance_to(opp_goal)
    var pressure := _nearest_opp_dist(sim, p.team, bp)
    var in_front := bp.x * ax > -pd.half_w * 0.1
    _mate = null
    _err = 0.0

    # the ball's reach is fixed by the physics, so shot / pass distances must not grow with the pitch
    if d_goal < minf(style.shoot_range * pd.half_w * 1.15, 330.0) and in_front:
        _kind = "shoot"
        _kick = true
        _aim = _shot_target(sim, p, opp_goal, ax)
        _err = rng.randfn(0.0, p.err_finish)
        return

    var pass_chance := style.pass_bias
    if pressure < 55.0:
        pass_chance = minf(1.0, pass_chance + 0.35)
    elif pressure > 130.0 * (pd.half_w / 370.0) * 0.6:
        pass_chance *= 0.55      # plenty of space: carry the ball forward instead of passing sideways
    var best := _best_pass(sim, p, brain, bp, ax)
    if best != null and rng.randf() < pass_chance:
        _kind = "pass"
        _kick = true
        _mate = best
        var dist := bp.distance_to(best.pos)
        _aim = best.pos + best.vel * (dist / 4.5)
        _aim.x = clampf(_aim.x, -pd.half_w + 15.0, pd.half_w - 15.0)
        _aim.y = clampf(_aim.y, -pd.half_h + 15.0, pd.half_h - 15.0)
        _err = rng.randfn(0.0, p.err_pass)
        return

    if brain.danger and pressure < 80.0:
        _kind = "clear"
        _kick = true
        var sy := 1.0 if bp.y >= 0.0 else -1.0
        _aim = Vector2(ax * pd.half_w * 0.4, sy * pd.half_h * 0.8)
        _err = rng.randfn(0.0, p.err_pass)
        return

    if style.directness > 0.8 and not in_front and rng.randf() < 0.4:
        _kind = "long"
        _kick = true
        _aim = Vector2(opp_goal.x * 0.7, bp.y * 0.5)
        _err = rng.randfn(0.0, p.err_pass)
        return

    _kind = "dribble"
    _kick = false
    _aim = opp_goal


func _shot_target(sim: MatchSim, p: SimPlayer, opp_goal: Vector2, ax: float) -> Vector2:
    var best := INF
    var def_y := 0.0
    for o in sim.team_lists[1 - p.team]:
        var op: SimPlayer = o
        var d := absf(op.pos.x - opp_goal.x)
        if d < best:
            best = d
            def_y = op.pos.y
    var side := 0.0
    if best < 220.0 * (sim.pitch.half_w / 370.0):
        side = -1.0 if def_y > 0.0 else 1.0
    return Vector2(opp_goal.x + ax * 10.0, side * sim.pitch.goal_half * 0.6)


func _best_pass(sim: MatchSim, p: SimPlayer, brain: TeamBrain, bp: Vector2, ax: float) -> SimPlayer:
    var scale := minf(sim.pitch.half_w / 370.0, 1.2)
    var pref := lerpf(110.0, 300.0, style.directness) * scale
    var max_d := minf(lerpf(240.0, 520.0, style.directness) * scale, 450.0)
    var best: SimPlayer = null
    var best_s := -INF
    for m in sim.team_lists[p.team]:
        var mp: SimPlayer = m
        if mp == p:
            continue
        if mp == brain.keeper or (mp.pos.x * ax) < -sim.pitch.half_w * 0.6:
            continue
        var to := mp.pos - bp
        var dist := to.length()
        if dist < 60.0 or dist > max_d:
            continue
        var tgt := mp.pos + mp.vel * (dist / 4.5)
        var open := _lane_clearance(sim, p.team, bp, tgt)
        if open < 32.0:
            continue
        var rp := minf(_nearest_opp_dist(sim, p.team, mp.pos), 140.0)
        var progress := to.x * ax
        var s := progress * (0.25 + style.risk * 0.6) + minf(open, 100.0) * 0.5 + rp * 0.6 \
            - absf(dist - pref) * 0.35
        if s > best_s:
            best_s = s
            best = mp
    return best


func _play_ball(sim: MatchSim, p: SimPlayer, brain: TeamBrain, bp: Vector2) -> void:
    var ax := sim.attack_dir(p.team)
    var pd := sim.pitch
    var d := _aim - bp
    if d.length() < 1.0:
        d = Vector2(ax, 0.0)
    d = d.normalized().rotated(_err)
    var rel := p.pos - bp
    var along := rel.dot(d)
    var lateral := rel.cross(d)
    var reach := p.radius + sim.ball.radius
    var target: Vector2
    var tol := reach * 0.9
    if _kind == "shoot" or _kind == "pass":
        tol = 7.0
    elif _kind == "clear" or _kind == "long":
        tol = 13.0
    if along < 0.0 and absf(lateral) < tol:
        target = bp + d * 22.0
    elif along < 0.0:
        target = bp - d * (reach + 16.0)
    else:
        var sgn := 1.0 if lateral >= 0.0 else -1.0
        var perp := Vector2(d.y, -d.x) * sgn
        target = bp + perp * (reach + 30.0) - d * (reach + 6.0)
    target.x = clampf(target.x, -pd.out_x + 12.0, pd.out_x - 12.0)
    target.y = clampf(target.y, -pd.out_y + 12.0, pd.out_y - 12.0)
    _chase(p, target)

    if _kick:
        var to_ball := sim.ball.pos - p.pos
        var dist := to_ball.length()
        var need := 0.95 if (_kind == "shoot" or _kind == "pass") else 0.8
        if dist - reach < MatchSim.KICK_RANGE and to_ball.normalized().dot(d) > need:
            p.input_kick = true
            p.kick_intent = _kind
            if _kind == "pass" and _mate != null:
                brain.pass_target = _mate
                brain.pass_tick = sim.tick


# ----------------------------------------------------------- off-ball logic

func _off_ball(sim: MatchSim, p: SimPlayer, brain: TeamBrain, bpos: Vector2) -> void:
    var ax := sim.attack_dir(p.team)
    var pd := sim.pitch
    var hw := pd.half_w
    var hh := pd.half_h
    var bx := bpos.x * ax / hw
    var role := p.role
    var fx := p.home.x
    if role == "GK":
        # the nominal goalkeeper plays as a defender while someone else keeps goal
        role = "DEF"
        fx = maxf(fx, -0.62)
    var shift := 0.3
    match role:
        "MID": shift = 0.45
        "FWD": shift = 0.5
    fx += bx * shift * (0.4 + style.compactness)
    if role == "FWD":
        fx += (style.line_height - 0.5) * 0.15
    else:
        fx += (style.line_height - 0.5) * 0.3
    if brain.has_possession:
        match role:
            "FWD": fx += 0.25
            "MID": fx += 0.15
            "DEF": fx += 0.05
        # attack commitment: with the ball in the attacking half more players join the attack
        if bx > -0.15:
            fx += style.attack_commit * (0.32 if role == "DEF" else (0.2 if role == "MID" else 0.08))
    else:
        if role == "FWD":
            fx = maxf(fx, p.home.x + (style.forward_stay - 0.3) * 0.6)
        elif role == "DEF":
            fx -= 0.04
    fx = clampf(fx, -0.9, 0.85)
    var fy := p.home.y * style.width + (bpos.y / hh) * 0.2 * (0.5 + style.compactness)
    fy = clampf(fy, -0.85, 0.85)
    var target := Vector2(ax * fx * hw, fy * hh)

    if brain.has_possession and (role != "DEF" or style.attack_commit > 0.6) and brain.carrier != null:
        var c := brain.carrier
        var sd := style.support_dist * minf(hw / 370.0, 1.3)
        var base_x := c.pos.x + ax * sd
        var off := 90.0 * (hh / 170.0)
        var cands: Array = [target, Vector2(base_x, target.y),
            Vector2(base_x, clampf(c.pos.y + off, -hh * 0.8, hh * 0.8)),
            Vector2(base_x, clampf(c.pos.y - off, -hh * 0.8, hh * 0.8))]
        var best := target
        var best_s := -INF
        for cd in cands:
            var cp: Vector2 = cd
            var s := minf(_nearest_opp_dist(sim, p.team, cp), 120.0) - 0.15 * cp.distance_to(p.pos)
            if (cp.x - c.pos.x) * ax < -40.0:
                s -= 60.0
            if p.home.y != 0.0 and signf(cp.y - c.pos.y) == signf(p.home.y):
                s += 25.0
            if s > best_s:
                best_s = s
                best = cp
        target = target.lerp(best, 0.7)
    elif not brain.has_possession and role != "FWD" and bx < 0.2:
        var own_goal2 := Vector2(-ax * hw, 0.0)
        var scale := hw / 370.0
        var cover_dist := lerpf(150.0, 80.0, style.line_height) * scale
        var back := minf(cover_dist, bpos.distance_to(own_goal2) - 45.0)
        var cover := bpos + (own_goal2 - bpos).normalized() * maxf(back, 0.0)
        cover.y += p.home.y * hh * 0.35
        target = target.lerp(cover, 0.6 if role == "DEF" else 0.35)
        if brain.marks.has(p.slot):
            var o2: SimPlayer = brain.marks[p.slot]
            target = target.lerp(o2.pos.lerp(own_goal2, 0.3), style.marking * 0.5)
    elif not brain.has_possession and brain.marks.has(p.slot):
        var o: SimPlayer = brain.marks[p.slot]
        var own_goal := Vector2(-ax * hw, 0.0)
        target = target.lerp(o.pos.lerp(own_goal, 0.3), style.marking)

    if sim.tick - _noise_tick > 90:
        _noise = Vector2(rng.randfn(0.0, 1.0), rng.randfn(0.0, 1.0)) * p.pos_noise * 0.5
        _noise_tick = sim.tick
    target += _noise
    target.x = clampf(target.x, -hw + 20.0, hw - 20.0)
    target.y = clampf(target.y, -hh + 20.0, hh - 20.0)
    _arrive(p, target)


func _keeper(sim: MatchSim, p: SimPlayer, _brain: TeamBrain, bpos: Vector2, bvel: Vector2) -> void:
    var ax := sim.attack_dir(p.team)
    var pd := sim.pitch
    var goal := Vector2(-ax * pd.half_w, 0.0)
    var lim := pd.goal_half - 10.0
    var to_ball := bpos - goal
    var dist := maxf(to_ball.length(), 1.0)
    var sweep := style.keeper_sweep

    # 1) a shot / fast ball heading for the goal: simulate its path and run to the EARLIEST point of that
    #    path he can still reach in time (he accelerates slowly: ~2.4 px/tick top speed, 24-tick time constant)
    if bvel.x * (-ax) > 0.8:
        var bp := bpos
        var v := bvel
        var path: Array[Vector2] = []
        var on_target := false
        for i in 100:
            bp += v
            v *= 0.99
            path.append(bp)
            if (bp.x - (goal.x + ax * 10.0)) * (-ax) >= 0.0:
                on_target = absf(bp.y) < pd.goal_half + 25.0
                break
            if v.length() < 0.3:
                break
        if on_target:
            var tgt: Vector2 = path[path.size() - 1]
            var touch := p.radius + sim.ball.radius + 3.0
            for i in path.size():
                var t := float(i + 1)
                var dv: Vector2 = path[i] - p.pos
                var dl := dv.length()
                var along := p.vel.dot(dv / maxf(dl, 1.0))
                var te := maxf(t - float(p.reaction_delay) - 2.0, 0.0)    # he sees the ball late and decides every 2nd tick
                var reach := 2.4 * te + (along - 2.4) * 24.0 * (1.0 - exp(-te / 24.0))
                if reach * 0.92 >= dl - touch:
                    # aim a little further down the path: sitting in the ball's way guarantees the touch
                    tgt = path[mini(i + 8, path.size() - 1)]
                    break
            tgt.y = clampf(tgt.y, -(lim + 25.0), lim + 25.0)
            if (tgt.x - goal.x) * ax < 12.0:
                tgt.x = goal.x + ax * 12.0
            var to_t := tgt - p.pos
            if to_t.length() > 14.0:
                p.input_dir = to_t.normalized()      # full speed, no braking: he only has to get a touch
            else:
                _arrive(p, tgt)
            _keeper_kick(sim, p, ax)
            return

    var target: Vector2
    # 2) otherwise stand on the line between the ball and the goal centre; the closer the ball,
    #    the further the keeper comes out to narrow the angle
    # narrowing the angle: the keeper cannot cover the whole mouth in time (he needs ~40 ticks to cross
    # 60 px), so he comes out until the shot cone at his depth is as wide as he can reach
    var depth := minf(dist * (KEEP_F + sweep * KEEP_FS), KEEP_CAP + sweep * KEEP_CAPS)
    depth *= clampf((KEEP_FAR - dist) / 220.0, 0.25, 1.0)    # ball far away: back to a safe depth
    depth = maxf(depth, 24.0)
    var dir := to_ball / dist
    target = goal + dir * depth
    target.y = clampf(target.y, -lim, lim)
    if (target.x - goal.x) * ax < 20.0:
        target.x = goal.x + ax * 20.0
    _chase_arrive(p, target, 18.0)
    _keeper_kick(sim, p, ax)


func _keeper_kick(sim: MatchSim, p: SimPlayer, ax: float) -> void:
    # only kick when the ball is clearly in front of the keeper, so the kick can never push it towards his own goal
    var to_ball := sim.ball.pos - p.pos
    var dl := to_ball.length()
    if dl - p.radius - sim.ball.radius < MatchSim.KICK_RANGE + 3.0 and to_ball.x * ax / maxf(dl, 1.0) > 0.3:
        p.input_kick = true
        p.kick_intent = "clear"


## Full speed towards the target, braking only when close (keeper needs speed, not precision).
func _chase_arrive(p: SimPlayer, target: Vector2, slow_radius: float) -> void:
    var v := target - p.pos
    if v.length() > slow_radius * 2.5:
        p.input_dir = v.normalized()
    else:
        _arrive(p, target)


# ------------------------------------------------------------------ helpers

func _chase(p: SimPlayer, target: Vector2) -> void:
    var v := target - p.pos
    p.input_dir = v.normalized() if v.length() > 1.0 else Vector2.ZERO


func _arrive(p: SimPlayer, target: Vector2) -> void:
    var cmd := ((target - p.pos) - p.vel * 20.0) / 30.0
    if cmd.length() > 1.0:
        cmd = cmd.normalized()
    p.input_dir = cmd


func _nearest_opp_dist(sim: MatchSim, team: int, pos: Vector2) -> float:
    var best := INF
    for o in sim.team_lists[1 - team]:
        var d := (o as SimPlayer).pos.distance_to(pos)
        if d < best:
            best = d
    return best


func _lane_clearance(sim: MatchSim, team: int, a: Vector2, b: Vector2) -> float:
    var best := INF
    var ab := b - a
    var l2 := maxf(ab.length_squared(), 0.001)
    for o in sim.team_lists[1 - team]:
        var op: Vector2 = (o as SimPlayer).pos
        var t := clampf((op - a).dot(ab) / l2, 0.0, 1.0)
        var d := op.distance_to(a + ab * t)
        if d < best:
            best = d
    return best
