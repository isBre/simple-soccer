class_name MatchSim
extends RefCounted
## Headless, deterministic (seeded) Haxball-style match simulation at a fixed 60 Hz.
## No rendering or scene-tree access, so it can run in worker threads for fast
## tournament / experiment simulation.

const TICK := 1.0 / 60.0
const KICK_STRENGTH := 5.0
const KICK_RANGE := 4.0
const GOAL_PAUSE := 210
const AI_PERIOD := 2
const LegacyBotScript := preload("res://scripts/ai/legacy_bot.gd")
const HIST := 32

enum State { PLAYING, GOAL, ENDED }

var cfg: MatchConfig
var pitch: PitchDef
var rng := RandomNumberGenerator.new()

var ball: Disc
var statics: Array[Disc] = []
var movers: Array[Disc] = []
var players: Array[SimPlayer] = []
var team_lists: Array = [[], []]
var by_uid: Dictionary = {}
var brains: Array[TeamBrain] = []
var styles: Array[StyleDef] = []

# walls as struct-of-arrays (fast): ball walls and player walls
var bseg_a := PackedVector2Array()
var bseg_b := PackedVector2Array()
var bseg_c := PackedFloat32Array()
var pseg_a := PackedVector2Array()
var pseg_b := PackedVector2Array()
var pseg_c := PackedFloat32Array()

var scores: Array[int] = [0, 0]
var tick := 0
var time_left := 180.0
var overtime := false
var ot_left := 0.0
var state := State.PLAYING
var goal_timer := 0
var goal_scorer: SimPlayer = null   # the scoring team celebrates around him
var goal_pause := GOAL_PAUSE
var goal_center := Vector2.ZERO    # where the celebration happens (the scorer runs laps around it)
var goal_team := -1
var winner := -1                 # team index, -1 = draw
var shootout: Array = []         # [a, b] when decided on penalties
var kickoff_active := true
var kickoff_team := 0
var kickoff_taker: SimPlayer = null   # who takes the kickoff (random each time, or the human's player)
var kickoff_dir := Vector2.RIGHT      # direction the taker will kick in (random within a forward cone)
var kickoff_go := 0                   # tick from which the taker may kick (short random reaction delay)
var kickoff_start := 0          # tick when the current kickoff was set up
var kickoff_waits: Array = []   # ticks each kickoff took until the ball moved
var zone_ticks := [0, 0, 0, 0, 0]   # diagnostics: ticks the ball spent in each fifth of the pitch (x)
var idle_ticks := 0                  # diagnostics: ticks with an (almost) stationary ball

# touches / possession
var last_touch: SimPlayer = null
var last_touch_tick := 0
var last_touch_kicked := false
var last_touch_kind := ""
var assist_cand: SimPlayer = null
var assist_tick := 0
var pending_shot_team := -1
var pending_shot_tick := -999
var pending_shot_player: SimPlayer = null
var pending_shot_xg := 0.0
var last_shot_xg := 0.0
var last_shot_player: SimPlayer = null
# dribbling (a carry = consecutive touches by one player without kicking)
var carry_p: SimPlayer = null
var carry_start := Vector2.ZERO
var carry_last := Vector2.ZERO
var carry_pressed := false
# the kick that is currently travelling (for pass grading)
var kick_pos := Vector2.ZERO
var kick_dir := Vector2.ZERO
var kick_pressed := false
var team_touch_player: Array = [null, null]   # last toucher per team
var team_touch_tick: Array = [-999, -999]

var ball_hist := PackedVector2Array()
var hist_idx := 0

var stats := MatchStats.new()
var events: Array = []
var mom_uid := -1

# human control (set by the view)
var controlled: SimPlayer = null
var human_dir := Vector2.ZERO
var human_kick := false


func _init(config: MatchConfig) -> void:
    cfg = config
    pitch = config.pitch
    rng.seed = config.match_seed
    time_left = config.duration
    ball_hist.resize(HIST)
    _build_stadium()
    _build_players()
    _reset_positions()
    if cfg.control != MatchConfig.ControlMode.NONE:
        _pick_initial_controlled()
        _setup_kickoff_taker()


# ------------------------------------------------------------------ setup

func attack_dir(team: int) -> float:
    return 1.0 if team == 0 else -1.0


func team_players(team: int) -> Array:
    return team_lists[team]


func _static_disc(p: Vector2, r: float) -> Disc:
    var d := Disc.new()
    d.pos = p
    d.radius = r
    d.inv_mass = 0.0
    d.damping = 1.0
    d.b_coef = 0.5
    d.kind = Disc.KIND_STATIC
    return d


func _add_seg(for_ball: bool, for_player: bool, a: Vector2, b: Vector2, bc: float) -> void:
    if for_ball:
        bseg_a.append(a)
        bseg_b.append(b)
        bseg_c.append(bc)
    if for_player:
        pseg_a.append(a)
        pseg_b.append(b)
        pseg_c.append(bc)


func _build_stadium() -> void:
    ball = Disc.new()
    ball.radius = 10.0
    ball.inv_mass = 1.0
    ball.damping = 0.99
    ball.b_coef = 0.5
    ball.kind = Disc.KIND_BALL

    var hw := pitch.half_w
    var hh := pitch.half_h
    var gh := pitch.goal_half
    var nd := pitch.net_depth
    for sx: float in [-1.0, 1.0]:
        for sy: float in [-1.0, 1.0]:
            statics.append(_static_disc(Vector2(sx * hw, sy * gh), pitch.post_r))
    for o in pitch.obstacles:
        statics.append(_static_disc(Vector2(float(o[0]), float(o[1])), float(o[2])))

    _add_seg(true, false, Vector2(-hw, -hh), Vector2(hw, -hh), 1.0)
    _add_seg(true, false, Vector2(-hw, hh), Vector2(hw, hh), 1.0)
    for sx: float in [-1.0, 1.0]:
        var bx: float = sx * (hw + nd)
        _add_seg(true, false, Vector2(sx * hw, -hh), Vector2(sx * hw, -gh), 1.0)
        _add_seg(true, false, Vector2(sx * hw, gh), Vector2(sx * hw, hh), 1.0)
        _add_seg(true, false, Vector2(sx * hw, -gh), Vector2(bx, -gh), 1.0)
        _add_seg(true, false, Vector2(bx, -gh), Vector2(bx, gh), 1.0)
        _add_seg(true, false, Vector2(bx, gh), Vector2(sx * hw, gh), 1.0)

    var ox := pitch.out_x
    var oy := pitch.out_y
    _add_seg(false, true, Vector2(-ox, -oy), Vector2(ox, -oy), 0.0)
    _add_seg(false, true, Vector2(-ox, oy), Vector2(ox, oy), 0.0)
    _add_seg(false, true, Vector2(-ox, -oy), Vector2(-ox, oy), 0.0)
    _add_seg(false, true, Vector2(ox, -oy), Vector2(ox, oy), 0.0)
    for w in pitch.walls:
        _add_seg(bool(w["ball"]), bool(w["player"]), w["a"], w["b"], float(w["bc"]))


func _build_players() -> void:
    for t in 2:
        styles.append(cfg.get_style(t))
        var b := TeamBrain.new()
        b.team = t
        b.style = styles[t]
        brains.append(b)
    movers.append(ball)
    for t in 2:
        var team_def: TeamDef = cfg.teams[t]
        var ax := attack_dir(t)
        var lineup: Array = team_def.lineup(cfg.team_size, cfg.formations[t])
        for i in lineup.size():
            var e: Dictionary = lineup[i]
            var p := SimPlayer.new()
            p.team = t
            p.slot = i
            p.uid = t * 16 + i
            p.def = e["def"]
            p.role = e["role"]
            p.home = Vector2(e["fx"], e["fy"])
            var sp := Vector2(ax * p.home.x * pitch.half_w, p.home.y * pitch.half_h)
            var minr := pitch.center_r + p.radius + 6.0
            if sp.length() < minr:
                sp = sp.normalized() * minr if sp.length() > 0.01 else Vector2(-ax * minr, 0.0)
            p.spawn = sp
            # No difficulty levels: a bot is exactly as good as its player's attributes, for every team
            # (allies and opponents alike). Strong teams are teams with strong players.
            var q_rea := SimPlayer.quality(p.def.reaction)
            var q_fin := SimPlayer.quality(p.def.finishing)
            var q_pas := SimPlayer.quality(p.def.passing)
            var q_pos := SimPlayer.quality(p.def.positioning)
            p.defend_q = SimPlayer.quality(p.def.defending)
            p.vision = (q_pas + q_pos + q_rea) / 3.0
            p.reaction_delay = roundi(lerpf(14.0, 0.0, q_rea))
            p.err_finish = lerpf(0.24, 0.005, q_fin)
            p.err_pass = lerpf(0.20, 0.005, q_pas)
            p.pos_noise = lerpf(70.0, 2.0, q_pos)
            p.think_ticks = roundi(lerpf(18.0, 6.0, p.vision))
            p.ps = stats.get_player(p.uid)
            var br := RandomNumberGenerator.new()
            br.seed = rng.randi()
            var ctrl: BotController = StyleBot.new(styles[t], br)
            if cfg.legacy_bot[t]:
                ctrl = LegacyBotScript.new(styles[t], br)
            if p.role != "GK" or (cfg.ml_keeper and cfg.ml_models[t] != null):
                if cfg.ml_models[t] != null:
                    var mb := MLBot.new(cfg.ml_models[t], br)
                    mb.temperature = cfg.ml_temperature
                    ctrl = mb
                elif cfg.dagger[t] != null:
                    var dg: Dictionary = cfg.dagger[t]
                    var st: MLBot = null
                    if dg["net"] != null:
                        st = MLBot.new(dg["net"], br)
                        st.temperature = float(dg["temp"])
                    ctrl = DaggerBot.new(ctrl, st, dg["rec"], float(dg["beta"]), br)
                elif cfg.recorders[t] != null:
                    ctrl = RecordingBot.new(ctrl, cfg.recorders[t])
            p.controller = ctrl
            players.append(p)
            movers.append(p)
            team_lists[t].append(p)
            by_uid[p.uid] = p


func _reset_positions() -> void:
    for p in players:
        p.pos = p.spawn
        p.vel = Vector2.ZERO
        p.input_dir = Vector2.ZERO
        p.input_kick = false
        p.kick_used = false
        p.in_contact = false
    ball.pos = Vector2.ZERO
    ball.vel = Vector2.ZERO
    kickoff_active = true
    kickoff_start = tick
    last_touch = null
    assist_cand = null
    pending_shot_team = -1
    carry_p = null
    for i in HIST:
        ball_hist[i] = Vector2.ZERO
    for b in brains:
        b.reset()
    _setup_kickoff_taker()


## Random taker (never the nominal GK), placed right behind the ball so the kickoff is immediate.
## The kick direction is random inside a forward cone and the taker waits a few ticks, so bot-vs-bot
## kickoffs differ every time. A human-controlled player on the kickoff team always takes it himself.
func _setup_kickoff_taker() -> void:
    kickoff_taker = null
    var list: Array = team_lists[kickoff_team]
    if list.is_empty():
        return
    for m in list:
        (m as SimPlayer).pos = (m as SimPlayer).spawn
    var ax := attack_dir(kickoff_team)
    var cands: Array = []
    for m in list:
        var sp: SimPlayer = m
        if sp.role != "GK" or list.size() == 1:
            cands.append(sp)
    if cands.is_empty():
        cands = list
    var forced: SimPlayer = null
    if cfg.control != MatchConfig.ControlMode.NONE and kickoff_team == cfg.human_team \
            and controlled != null and controlled.team == kickoff_team:
        forced = controlled
    var taker: SimPlayer = forced if forced != null else cands[rng.randi() % cands.size()]
    var ang := 0.0 if forced != null else clampf(rng.randfn(0.0, 0.55), -0.95, 0.95)
    kickoff_dir = Vector2(ax, 0.0).rotated(ang)
    taker.pos = -kickoff_dir * (taker.radius + ball.radius + 2.0)
    kickoff_taker = taker
    kickoff_go = tick + rng.randi_range(6, 28)


func _pick_initial_controlled() -> void:
    var best: SimPlayer = null
    for p: SimPlayer in team_lists[cfg.human_team]:
        if p.role == "GK" and team_lists[cfg.human_team].size() > 1:
            continue
        if cfg.control == MatchConfig.ControlMode.SINGLE:
            if best == null or (p.role == "FWD" and best.role != "FWD") or (p.role == best.role and p.slot > best.slot):
                best = p
        else:
            if best == null or p.pos.length() < best.pos.length():
                best = p
    set_controlled(best)


# ------------------------------------------------------ human control API

func set_controlled(p: SimPlayer) -> void:
    if controlled != null:
        controlled.is_human = false
        controlled.input_dir = Vector2.ZERO
        controlled.input_kick = false
    controlled = p
    if p != null:
        p.is_human = true


func set_human_input(dir: Vector2, kick: bool) -> void:
    human_dir = dir
    human_kick = kick


## TEAM control mode: hand control to the teammate nearest to the ball.
func switch_controlled() -> void:
    if cfg.control != MatchConfig.ControlMode.TEAM:
        return
    var best: SimPlayer = null
    var best_d := INF
    for p: SimPlayer in team_lists[cfg.human_team]:
        if p == controlled:
            continue
        var d := p.pos.distance_squared_to(ball.pos)
        if d < best_d:
            best_d = d
            best = p
    if best != null:
        set_controlled(best)


# ------------------------------------------------------------- simulation

func ball_at(delay: int) -> Vector2:
    return ball_hist[(hist_idx - 1 - delay + HIST * 2) % HIST]


func elapsed() -> float:
    var t := cfg.duration - time_left
    if overtime:
        t += cfg.overtime - ot_left
    return t


func step() -> void:
    if state == State.ENDED:
        return
    tick += 1

    if tick % AI_PERIOD == 0:
        for b in brains:
            b.update(self)

    for p in players:
        if p.is_human:
            p.input_dir = human_dir
            p.input_kick = human_kick
        elif p.controller != null and (tick + p.slot) % AI_PERIOD == 0:
            p.controller.decide(self, p)

    if state == State.GOAL:
        _celebrate()
    if cfg.auto_switch and cfg.control == MatchConfig.ControlMode.TEAM and tick % 20 == 0:
        _auto_switch()

    for p in players:
        _handle_kick(p)

    for p in players:
        var a := p.kick_accel if p.input_kick else p.accel
        var d := p.input_dir
        if d.length_squared() > 1.0:
            d = d.normalized()
        p.vel += d * a

    for m in movers:
        m.pos += m.vel

    for i in movers.size():
        var a: Disc = movers[i]
        for j in range(i + 1, movers.size()):
            _collide_discs(a, movers[j])
        for s in statics:
            _collide_discs(a, s)
        if a.kind == Disc.KIND_BALL:
            _collide_walls(a, bseg_a, bseg_b, bseg_c)
        else:
            _collide_walls(a, pseg_a, pseg_b, pseg_c)

    _apply_kickoff_limits()

    var lim := (ball.radius + 15.0 + 0.6)
    lim *= lim
    for p in players:
        var touching := p.pos.distance_squared_to(ball.pos) < lim
        if touching and not p.in_contact:
            _register_touch(p, false)
        p.in_contact = touching
        p.ps.distance += p.vel.length()
        if _is_keeper(p):
            p.ps.keeper_ticks += 1

    for m in movers:
        m.vel *= m.damping

    if kickoff_active and ball.vel.length_squared() > 0.01:
        kickoff_active = false
        kickoff_waits.append(tick - kickoff_start)

    ball_hist[hist_idx] = ball.pos
    hist_idx = (hist_idx + 1) % HIST

    if state == State.PLAYING and not kickoff_active and last_touch != null:
        stats.possession_ticks[last_touch.team] += 1
        zone_ticks[clampi(int((ball.pos.x / pitch.half_w + 1.0) * 2.5), 0, 4)] += 1
        if ball.vel.length_squared() < 0.04:
            idle_ticks += 1

    _update_rules()


func run_to_end(max_ticks: int = 60 * 60 * 8) -> void:
    while state != State.ENDED and tick < max_ticks:
        step()
    if state != State.ENDED:
        _end_match()


func _auto_switch() -> void:
    var best: SimPlayer = null
    var best_d := INF
    for p: SimPlayer in team_lists[cfg.human_team]:
        var d := p.pos.distance_to(ball.pos)
        if d < best_d:
            best_d = d
            best = p
    if best != null and best != controlled and controlled != null \
            and controlled.pos.distance_to(ball.pos) > best_d + 40.0:
        set_controlled(best)


func _handle_kick(p: SimPlayer) -> void:
    if not p.input_kick:
        p.kick_used = false
        return
    if p.kick_used:
        return
    var diff := ball.pos - p.pos
    var dist := diff.length()
    if dist - p.radius - ball.radius < KICK_RANGE:
        var n := diff / maxf(dist, 0.0001)
        ball.vel += n * KICK_STRENGTH * ball.inv_mass
        p.kick_used = true
        _register_touch(p, true)


func _collide_discs(a: Disc, b: Disc) -> void:
    var diff := a.pos - b.pos
    var rsum := a.radius + b.radius
    var d2 := diff.length_squared()
    if d2 >= rsum * rsum or d2 < 0.00000001:
        return
    var mass_sum := a.inv_mass + b.inv_mass
    if mass_sum == 0.0:
        return
    var dist := sqrt(d2)
    var n := diff / dist
    var share := a.inv_mass / mass_sum
    var pen := rsum - dist
    a.pos += n * pen * share
    b.pos -= n * pen * (1.0 - share)
    var rel := (a.vel - b.vel).dot(n)
    if rel < 0.0:
        var bc := a.b_coef * b.b_coef
        var j := rel * (bc + 1.0) / mass_sum
        a.vel -= n * j * a.inv_mass
        b.vel += n * j * b.inv_mass


func _collide_walls(d: Disc, sa: PackedVector2Array, sb: PackedVector2Array, sc: PackedFloat32Array) -> void:
    for i in sa.size():
        var a := sa[i]
        var b := sb[i]
        var ab := b - a
        var t := clampf((d.pos - a).dot(ab) / ab.length_squared(), 0.0, 1.0)
        var diff := d.pos - (a + ab * t)
        var d2 := diff.length_squared()
        if d2 >= d.radius * d.radius or d2 < 0.00000001:
            continue
        var dist := sqrt(d2)
        var n := diff / dist
        d.pos += n * (d.radius - dist)
        var vn := d.vel.dot(n)
        if vn < 0.0:
            d.vel -= n * vn * (1.0 + d.b_coef * sc[i])


## After a goal the scorer's bot teammates run to him and form a huddle around him; the other team stands
## still. Nobody kicks. A human-controlled player is never steered: he decides himself whether to join.
func _celebrate() -> void:
    var mates: Array = []
    if goal_scorer != null:
        for m: SimPlayer in team_lists[goal_team]:
            if m != goal_scorer and not m.is_human:
                mates.append(m)
    for p in players:
        p.input_kick = false
        if not p.is_human:          # the human keeps full control of his player and can walk wherever he likes
            p.input_dir = Vector2.ZERO
    if goal_scorer == null:
        return
    # a bot scorer runs a victory lap around the spot, his mates gather in a wider ring around it
    if not goal_scorer.is_human:
        var age := float(goal_pause - goal_timer)
        var dir := 1.0 if goal_scorer.uid % 2 == 0 else -1.0
        var ang := dir * age * 0.03 + goal_scorer.uid
        var tgt := goal_center + Vector2.from_angle(ang) * 80.0
        goal_scorer.input_dir = (tgt - goal_scorer.pos).limit_length(1.0)
    for i in mates.size():
        var m: SimPlayer = mates[i]
        var ang2 := TAU * float(i) / float(maxi(mates.size(), 1)) + goal_scorer.uid * 0.7
        var spot := goal_center + Vector2.from_angle(ang2) * (125.0 + 12.0 * float(i % 2))
        spot.x = clampf(spot.x, -pitch.half_w + 40.0, pitch.half_w - 40.0)
        spot.y = clampf(spot.y, -pitch.half_h + 40.0, pitch.half_h - 40.0)
        var cmd := ((spot - m.pos) - m.vel * 20.0) / 30.0
        if (spot - m.pos).length() > 80.0:
            cmd = (spot - m.pos).normalized()
        m.input_dir = cmd.limit_length(1.0)


func _apply_kickoff_limits() -> void:
    if not kickoff_active:
        return
    for p in players:
        var wrong_side: bool = p.pos.x > -p.radius if p.team == 0 else p.pos.x < p.radius
        if wrong_side:
            var allow := pitch.center_r - p.radius
            if p.team == kickoff_team and absf(p.pos.y) < allow and p.pos.length() > allow:
                # the team that kicks off may use the whole centre circle (e.g. to play the ball back),
                # but not leave it on the opponents' side
                var n := p.pos / maxf(p.pos.length(), 0.001)
                p.pos = n * allow
                var vn := p.vel.dot(n)
                if vn > 0.0:
                    p.vel -= n * vn
            elif p.team != kickoff_team or absf(p.pos.y) >= allow:
                if p.team == 0:
                    p.pos.x = -p.radius
                    p.vel.x = minf(p.vel.x, 0.0)
                else:
                    p.pos.x = p.radius
                    p.vel.x = maxf(p.vel.x, 0.0)
        if p.team != kickoff_team:
            var dist := p.pos.length()
            var minr := pitch.center_r + p.radius
            if dist < minr:
                var n := p.pos / maxf(dist, 0.001)
                p.pos = n * minr
                var vn := p.vel.dot(n)
                if vn < 0.0:
                    p.vel -= n * vn


# ------------------------------------------------------- touches & stats

func _is_keeper(p: SimPlayer) -> bool:
    var k: SimPlayer = brains[p.team].keeper if brains.size() > p.team else null
    return k == p if k != null else p.role == "GK"


## An opponent is close enough to bother this player.
func _pressed(p: SimPlayer) -> bool:
    for o: SimPlayer in team_lists[1 - p.team]:
        if o.pos.distance_squared_to(p.pos) < 3844.0:    # 62 px
            return true
    return false


func _end_carry() -> void:
    if carry_p == null:
        return
    var fwd := (carry_last.x - carry_start.x) * attack_dir(carry_p.team)
    if fwd > 0.0:
        carry_p.ps.carry_dist += fwd
        if carry_pressed and fwd > pitch.half_w * 0.06:
            carry_p.ps.dribbles += 1
    carry_p = null


func _register_touch(p: SimPlayer, kicked: bool) -> void:
    if state == State.GOAL:
        return
    if last_touch == p and tick - last_touch_tick < 8:
        last_touch_tick = tick
        if not kicked:
            carry_last = ball.pos
            if not carry_pressed and _pressed(p):
                carry_pressed = true
        if kicked and not last_touch_kicked:
            last_touch_kicked = true
            _classify_kick(p)
        return
    p.ps.touches += 1
    var half_w := pitch.half_w
    if last_touch != null and last_touch != p:
        var lt := last_touch
        var ax_lt := attack_dir(lt.team)
        if lt.team == p.team:
            _end_carry()
            if last_touch_kicked and last_touch_kind == "pass" and tick - last_touch_tick < 240:
                lt.ps.passes_ok += 1
                p.ps.passes_received += 1
                var gain := (ball.pos.x - kick_pos.x) * ax_lt
                var prog_thr := half_w * 0.2
                if gain >= prog_thr:
                    lt.ps.progressive_passes += 1
                lt.ps.pass_value += Rating.pass_value(true, gain, false, kick_pressed,
                    kick_pos.x * ax_lt / half_w, prog_thr)
            assist_cand = lt
            assist_tick = tick
        else:
            var was_dribbling := carry_p == lt and not last_touch_kicked and tick - last_touch_tick < 14
            if was_dribbling:
                lt.ps.dispossessed += 1
                carry_p = null
            else:
                _end_carry()
            if last_touch_kicked and last_touch_kind == "pass":
                lt.ps.passes_failed += 1
                lt.ps.pass_value += Rating.pass_value(false, 0.0, kick_dir.x * ax_lt > 0.5,
                    kick_pressed, kick_pos.x * ax_lt / half_w, half_w * 0.2)
            if pending_shot_team == lt.team and tick - pending_shot_tick < 150:
                if _is_keeper(p):
                    p.ps.saves += 1
                    p.ps.save_xg += pending_shot_xg
                else:
                    p.ps.blocks += 1
                pending_shot_team = -1
            elif was_dribbling:
                p.ps.tackles += 1
                p.rec_tick = tick
            elif last_touch_kicked and (last_touch_kind == "pass" or last_touch_kind == "clear") \
                    and tick - last_touch_tick < 90 and tick - p.rec_tick >= 30:
                p.ps.interceptions += 1
                p.rec_tick = tick
            elif tick - last_touch_tick >= 12 and tick - p.rec_tick >= 60:
                p.ps.recoveries += 1
                p.rec_tick = tick
            assist_cand = null
    # a new possession by this player starts a carry (a kick ends it again straight away)
    if carry_p == p and last_touch == p and not kicked:
        carry_last = ball.pos      # same dribble, the ball just got away for a moment
    else:
        _end_carry()
        if not kicked:
            carry_p = p
            carry_start = ball.pos
            carry_last = ball.pos
            carry_pressed = _pressed(p)
    last_touch = p
    last_touch_tick = tick
    last_touch_kicked = kicked
    last_touch_kind = "touch"
    team_touch_player[p.team] = p
    team_touch_tick[p.team] = tick
    if kicked:
        _classify_kick(p)


func _classify_kick(p: SimPlayer) -> void:
    var ax := attack_dir(p.team)
    var kind := "pass"
    var v := ball.vel
    _end_carry()
    kick_pos = ball.pos
    kick_dir = v.normalized()
    kick_pressed = _pressed(p)
    var gx := ax * pitch.half_w
    if v.x * ax > 0.5:
        var t := (gx - ball.pos.x) / v.x
        if t > 0.0:
            var y_at := ball.pos.y + v.y * t
            var dcross := Vector2(gx - ball.pos.x, y_at - ball.pos.y).length()
            if dcross < v.length() * 55.0 and absf(y_at) < pitch.goal_half + 45.0:
                kind = "shot"
                p.ps.shots += 1
                var xg := Rating.shot_xg(ball.pos, gx, pitch.goal_half)
                p.ps.xg += xg
                if xg >= 0.3:
                    p.ps.big_chances += 1
                last_shot_xg = xg
                last_shot_player = p
                if assist_cand != null and assist_cand != p and assist_cand.team == p.team \
                        and tick - assist_tick < 240:
                    assist_cand.ps.key_passes += 1
                    assist_cand.ps.xa += xg
                if absf(y_at) < pitch.goal_half - ball.radius:
                    p.ps.shots_on_target += 1
                    pending_shot_team = p.team
                    pending_shot_tick = tick
                    pending_shot_player = p
                    pending_shot_xg = xg
    if kind == "pass" and p.kick_intent == "shoot":
        # the bot aimed at goal but the ball is not heading into the mouth (aim error): a wide shot,
        # not a failed pass (it must not count against the shooter's passing nor inflate pass failures)
        kind = "shot"
        p.ps.shots += 1
        var xg_wide := Rating.shot_xg(ball.pos, gx, pitch.goal_half)
        p.ps.xg += xg_wide
        if xg_wide >= 0.3:
            p.ps.big_chances += 1
    if kind == "pass" and (p.kick_intent == "clear" or p.kick_intent == "long"):
        kind = "clear"
        if kick_pos.x * ax < -pitch.half_w * 0.25:
            p.ps.clearances += 1
    last_touch_kind = kind


# ------------------------------------------------------------------ rules

func _update_rules() -> void:
    match state:
        State.PLAYING:
            if absf(ball.pos.x) > pitch.half_w + ball.radius:      # the whole ball is over the line
                _goal_scored(0 if ball.pos.x > 0.0 else 1)
            elif not kickoff_active:
                if not overtime:
                    time_left -= TICK
                    if time_left <= 0.0:
                        time_left = 0.0
                        if scores[0] != scores[1] or cfg.allow_draw:
                            _end_match()
                        else:
                            overtime = true
                            ot_left = cfg.overtime
                else:
                    ot_left -= TICK
                    if ot_left <= 0.0:
                        ot_left = 0.0
                        _run_shootout()
                        _end_match()
        State.GOAL:
            goal_timer -= 1
            if goal_timer <= 0:
                var limit_hit: bool = cfg.score_limit > 0 and (scores[0] >= cfg.score_limit or scores[1] >= cfg.score_limit)
                if limit_hit or overtime:
                    _end_match()
                else:
                    state = State.PLAYING
                    kickoff_team = 1 - goal_team
                    _reset_positions()


func _goal_scored(team: int) -> void:
    scores[team] += 1
    goal_team = team
    state = State.GOAL
    goal_timer = GOAL_PAUSE
    var scorer: SimPlayer = last_touch
    if scorer != null and scorer.team != team:
        if pending_shot_player != null and pending_shot_team == team and tick - pending_shot_tick < 200:
            scorer = pending_shot_player      # deflected / saved-into-net shot belongs to the shooter
        else:
            var cand: SimPlayer = team_touch_player[team]
            # a mere body-touch by the defender does not turn a dribbled-in ball into an own goal
            if cand != null and not last_touch_kicked and tick - int(team_touch_tick[team]) < 180:
                scorer = cand
    goal_scorer = scorer if (scorer != null and scorer.team == team) else null
    if goal_scorer != null:
        goal_center = Vector2(clampf(goal_scorer.pos.x, -pitch.half_w + 140.0, pitch.half_w - 140.0),
            clampf(goal_scorer.pos.y, -pitch.half_h + 110.0, pitch.half_h - 110.0))
    # the pause lasts long enough for the scorer's teammates to run over to him (up to ~4.3 s)
    goal_pause = GOAL_PAUSE
    if goal_scorer != null:
        var far := 0.0
        for m: SimPlayer in team_lists[team]:
            far = maxf(far, m.pos.distance_to(goal_scorer.pos))
        goal_pause = clampi(130 + int(far / 5.0), 150, 260)
    goal_timer = goal_pause
    var ev := {"type": "goal", "team": team, "clock": elapsed(), "scorer": -1, "scorer_name": "",
        "assist": -1, "assist_name": "", "own": false, "last_kind": last_touch_kind,
        "last_role": last_touch.role if last_touch != null else "", "dt": tick - last_touch_tick,
        "ball_speed": ball.vel.length()}
    if scorer != null:
        ev["scorer"] = scorer.uid
        ev["scorer_name"] = scorer.def.name
        if scorer.team == team:
            scorer.ps.goals += 1
            if assist_cand != null and assist_cand != scorer and assist_cand.team == team \
                    and tick - assist_tick < 420:
                ev["assist"] = assist_cand.uid
                ev["assist_name"] = assist_cand.def.name
                assist_cand.ps.assists += 1
        else:
            ev["own"] = true
            scorer.ps.own_goals += 1
    var shot_goal: bool = last_touch_kind == "shot" and last_shot_player != null and last_shot_player.team == team
    if scorer != null and scorer.team == team and shot_goal and last_shot_player == scorer \
            and last_shot_xg >= 0.3:
        scorer.ps.big_scored += 1
    for p: SimPlayer in team_lists[team]:
        p.ps.scored_for += 1
    for p: SimPlayer in team_lists[1 - team]:
        p.ps.conceded += 1
        if _is_keeper(p):
            p.ps.conceded_xg += last_shot_xg if shot_goal else 0.3
    events.append(ev)
    pending_shot_team = -1


func _run_shootout() -> void:
    var res := [0, 0]
    var takers: Array = []
    var keepers: Array = []
    for t in 2:
        var list: Array = []
        var gk := 60.0
        for p: SimPlayer in team_lists[t]:
            if p.role == "GK":
                gk = (p.def.positioning + p.def.reaction) / 2.0
            else:
                list.append(p)
        if list.is_empty():
            list = team_lists[t].duplicate()
        list.sort_custom(func(a: SimPlayer, b: SimPlayer) -> bool: return a.def.finishing > b.def.finishing)
        takers.append(list)
        keepers.append(gk)
    var rd := 0
    while rd < 30:
        for t in 2:
            var tk: SimPlayer = takers[t][rd % takers[t].size()]
            var chance := clampf(0.72 + (tk.def.finishing - keepers[1 - t]) / 250.0, 0.5, 0.92)
            if rng.randf() < chance:
                res[t] += 1
        rd += 1
        if rd >= 5 and res[0] != res[1]:
            break
    if res[0] == res[1]:
        res[rng.randi() % 2] += 1
    shootout = res


func _end_match() -> void:
    if state == State.ENDED:
        return
    state = State.ENDED
    if not shootout.is_empty():
        winner = 0 if shootout[0] > shootout[1] else 1
    elif scores[0] == scores[1]:
        winner = -1
    else:
        winner = 0 if scores[0] > scores[1] else 1
    var best_r := -1.0
    for p in players:
        var won := winner == p.team
        var lost := winner != -1 and winner != p.team
        p.ps.rating = Rating.grade(played_role(p), p.ps, won, lost, scores[1 - p.team])
        var score := p.ps.rating + (p.ps.goals + p.ps.assists) * 0.001
        if score > best_r:
            best_r = score
            mom_uid = p.uid


## The role a player actually filled: whoever spent most of the match in goal is the keeper,
## a nominal goalkeeper who was not is judged as a defender.
func played_role(p: SimPlayer) -> String:
    if p.ps.keeper_ticks * 2 > maxi(tick, 1):
        return "GK"
    return "DEF" if p.role == "GK" else p.role


# ----------------------------------------------------------------- output

func make_result() -> Dictionary:
    var plist: Array = []
    for p in players:
        var d := p.ps.to_dict()
        d["uid"] = p.uid
        d["id"] = p.def.id
        d["name"] = p.def.name
        d["team"] = p.team
        d["role"] = p.role
        d["played"] = played_role(p)
        d["number"] = p.def.number
        plist.append(d)
    var tstats: Array = []
    var total_poss: int = stats.possession_ticks[0] + stats.possession_ticks[1]
    for t in 2:
        var ts := {"shots": 0, "shots_on_target": 0, "passes": 0, "passes_ok": 0, "recoveries": 0,
            "saves": 0, "touches": 0, "goals": scores[t], "xg": 0.0, "dribbles": 0}
        for p: SimPlayer in team_lists[t]:
            ts["shots"] += p.ps.shots
            ts["shots_on_target"] += p.ps.shots_on_target
            ts["passes"] += p.ps.passes()
            ts["passes_ok"] += p.ps.passes_ok
            ts["recoveries"] += p.ps.tackles + p.ps.interceptions
            ts["xg"] += p.ps.xg
            ts["dribbles"] += p.ps.dribbles
            ts["saves"] += p.ps.saves
            ts["touches"] += p.ps.touches
        ts["possession"] = 50.0 if total_poss == 0 else 100.0 * stats.possession_ticks[t] / total_poss
        tstats.append(ts)
    return {"teams": [cfg.teams[0].id, cfg.teams[1].id], "scores": [scores[0], scores[1]],
        "shootout": shootout, "winner": winner, "overtime": overtime, "events": events,
        "players": plist, "team_stats": tstats, "mom": mom_uid, "duration": cfg.duration,
        "ticks": tick, "kickoff_waits": kickoff_waits, "zones": zone_ticks, "idle": idle_ticks}


# --------------------------------------------------- agent / RL interface

const DIRS: Array[Vector2] = [
    Vector2(0, 0), Vector2(0, -1), Vector2(1, -1), Vector2(1, 0), Vector2(1, 1),
    Vector2(0, 1), Vector2(-1, 1), Vector2(-1, 0), Vector2(-1, -1),
]


## Normalized state, mirrored so the agent always attacks toward +x.
## Layout: self, ball, teammates, opponents; each = [x, y, vx, vy].
func get_observation(p: SimPlayer) -> PackedFloat32Array:
    var s := attack_dir(p.team)
    var obs := PackedFloat32Array()
    _push_disc(obs, p, s)
    _push_disc(obs, ball, s)
    for m: SimPlayer in team_lists[p.team]:
        if m != p:
            _push_disc(obs, m, s)
    for o: SimPlayer in team_lists[1 - p.team]:
        _push_disc(obs, o, s)
    return obs


func _push_disc(obs: PackedFloat32Array, d: Disc, s: float) -> void:
    obs.append(d.pos.x * s / pitch.out_x)
    obs.append(d.pos.y / pitch.out_y)
    obs.append(d.vel.x * s / 5.0)
    obs.append(d.vel.y / 5.0)


## Discrete action: move_idx 0..8 (DIRS, in the agent's own frame where +x is
## toward the opponent goal) plus kick.
func set_action(p: SimPlayer, move_idx: int, kick: bool) -> void:
    var d: Vector2 = DIRS[move_idx]
    d.x *= attack_dir(p.team)
    p.input_dir = d.normalized()
    p.input_kick = kick
