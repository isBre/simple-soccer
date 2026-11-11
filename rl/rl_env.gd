class_name RLEnv
extends RefCounted
## One RL episode source on top of MatchSim. The learner controls players of team 0 with ONE shared
## policy (one observation per player: MLBot.features + slot one-hot, 54 inputs). With `with_keeper`
## the goalkeeper slot is a normal learner player too: no rule-based keeper, no fixed formation.
##
## Config (see configure()):
##   n_active     number of learner-controlled players (1..5); the rest of team 0 is removed ("ghosts")
##   with_keeper  true -> the keeper slot (slot 0) is one of the controlled players
##   opp          "none"    empty goal: team 1 removed from the physics
##                "keeper"  only team 1's rule-based keeper stays (outfield removed)
##                "a,b,c"   a full rule-based team 1, drawn per episode from this pool of team ids
##   match_mode   false -> first-goal episodes from random starts (curriculum stages)
##                true  -> a real match: kickoffs, both teams complete, ends at the final whistle
##   duration     match length in seconds (match_mode)
##   selfplay     probability that team 1 is driven by `opp_net` (all 5 players incl. keeper) instead of rules
##   own_team     id of the learner's team (only matters for a rule-based keeper / lineup)

const REPEAT := 2                 # sim ticks per decision (same as MLBot's AI_PERIOD)
const OUT_NONE := 0
const OUT_GOAL := 1
const OUT_OWN := 2
const OUT_TIMEOUT := 3
const OUT_CONCEDED := 4
const OUT_WIN := 5
const OUT_DRAW := 6
const OUT_LOSS := 7
const OBS_DIM := 54

var pitch_id := "arena"
var size := 5
var n_active := 5
var with_keeper := true
var opp := "none"
var opp_pool: PackedStringArray = []
var own_team := "owls"
var max_steps := 750
var spread := 1.0
var ball_speed := 0.0
var match_mode := false
var duration := 90.0
var selfplay := 0.0
var shaping := 1.0
var w_pass_prog := 0.0            # reward per completed progressive pass (team)
var w_pass_ok := 0.0              # reward per other completed pass
var w_pass_fail := 0.0            # penalty per failed pass
var w_key_pass := 0.0             # reward per key pass (completed pass followed by a shot of the receiver within 4 s)
var w_xa := 0.0                   # reward per unit of expected goals of the shots created by passes (xA)
var pass_individual := false      # pass terms go to the passer (and receiver) instead of the whole team: sharper credit
var w_recv := 0.0                 # reward to the receiver of a completed pass
var w_open := 0.0                 # per decision: reward for standing open (distance + clear lane) while a teammate has the ball
var random_start := 0.0           # match mode: probability that an episode starts from a completely random layout (all players incl. keepers + ball) instead of a kickoff
var coop_cap := 0.0               # max cooperation reward (key pass + xA + receive + ok-pass) a team can earn per episode; 0 = no cap
var coop_used := 0.0
var w_keeper := 0.0               # per decision: penalty for the keeper straying from its own goal (beyond keeper_free px)
var keeper_free := 350.0
var open_min := 120.0
var open_max := 450.0
var lane_clear := 45.0
var prev_ps: Dictionary = {}      # uid -> [ok, failed, progressive, key passes, xA, received]
var w_space := 0.0                # penalty per player and teammate closer than space_radius (not while fighting for the ball)
var space_radius := 140.0
var w_kick := 0.0                 # penalty for pressing kick while the ball is out of reach
var kick_reach := 40.0
var prev_pass := [0, 0, 0, 0, 0.0]  # team 0 totals: progressive, ok, failed, key passes, xA
var opp_external := false         # team 1 is controlled from Python too (self-play): its players are extra agents
var opp_net: MLP = null
var own_keeper := true            # only used when the keeper is not controlled: keep the rule-based one?
var external_actions := false     # true -> step() leaves the players' inputs alone (set by MLBot etc.)

var sim: MatchSim
var agents: Array[SimPlayer] = []
var opp_agents: Array[SimPlayer] = []
var rng := RandomNumberGenerator.new()
var steps := 0
var ep_return := 0.0
var prev_pot := 0.0
var prev_scores := [0, 0]
var prev_playing := true
var episode_id := 0
var used_selfplay := false


func configure(c: Dictionary) -> void:
    pitch_id = str(c.get("pitch", pitch_id))
    size = int(c.get("size", size))
    n_active = int(c.get("n_active", n_active))
    with_keeper = bool(c.get("with_keeper", with_keeper))
    opp = str(c.get("opp", opp))
    opp_pool = PackedStringArray(opp.split(",", false)) if opp not in ["none", "keeper"] else PackedStringArray()
    own_team = str(c.get("own_team", own_team))
    max_steps = int(c.get("max_steps", max_steps))
    spread = float(c.get("spread", spread))
    ball_speed = float(c.get("ball_speed", ball_speed))
    match_mode = bool(c.get("match_mode", match_mode))
    duration = float(c.get("duration", duration))
    selfplay = float(c.get("selfplay", selfplay))
    shaping = float(c.get("shaping", shaping))
    opp_external = bool(c.get("opp_external", opp_external))
    w_pass_prog = float(c.get("w_pass_prog", w_pass_prog))
    w_pass_ok = float(c.get("w_pass_ok", w_pass_ok))
    w_pass_fail = float(c.get("w_pass_fail", w_pass_fail))
    w_key_pass = float(c.get("w_key_pass", w_key_pass))
    w_xa = float(c.get("w_xa", w_xa))
    pass_individual = bool(c.get("pass_individual", pass_individual))
    w_recv = float(c.get("w_recv", w_recv))
    w_open = float(c.get("w_open", w_open))
    random_start = float(c.get("random_start", random_start))
    coop_cap = float(c.get("coop_cap", coop_cap))
    w_keeper = float(c.get("w_keeper", w_keeper))
    keeper_free = float(c.get("keeper_free", keeper_free))
    open_min = float(c.get("open_min", open_min))
    open_max = float(c.get("open_max", open_max))
    w_space = float(c.get("w_space", w_space))
    space_radius = float(c.get("space_radius", space_radius))
    w_kick = float(c.get("w_kick", w_kick))
    own_keeper = bool(c.get("own_keeper", opp != "none"))
    if c.has("seed"):
        rng.seed = int(c["seed"])


func obs_dim() -> int:
    return OBS_DIM


## Learner agents first, then (self-play) the opponent team's players.
func n_agents() -> int:
    return n_active + (size if opp_external else 0)


func reset() -> void:
    coop_used = 0.0
    var cfg := MatchConfig.new()
    cfg.pitch = Database.pitches[pitch_id]
    cfg.team_size = size
    cfg.duration = duration if match_mode else 600.0
    cfg.match_seed = rng.randi()
    var opp_id := own_team
    if not opp_pool.is_empty():
        opp_id = opp_pool[rng.randi() % opp_pool.size()]
    cfg.teams = [Database.teams[own_team], Database.teams[opp_id]]
    cfg.resolve_kits()
    used_selfplay = opp_net != null and rng.randf() < selfplay
    if used_selfplay:
        cfg.ml_models[1] = opp_net
        cfg.ml_keeper = true
    sim = MatchSim.new(cfg)
    episode_id += 1
    steps = 0
    ep_return = 0.0

    # learner team: controlled players, the rest are ghosts (or the rule-based keeper)
    agents.clear()
    var ghosts: Array[SimPlayer] = []
    var ordered: Array[SimPlayer] = []
    for p: SimPlayer in sim.team_lists[0]:
        if p.role == "GK":
            ordered.push_front(p)
        else:
            ordered.append(p)
    for p in ordered:
        var is_gk := p.role == "GK"
        if agents.size() < n_active and (with_keeper or not is_gk):
            agents.append(p)
            p.controller = null
        elif is_gk and own_keeper and not with_keeper:
            pass                                   # stays a rule-based keeper
        else:
            ghosts.append(p)
    opp_agents.clear()
    if opp_external:
        var ordered1: Array[SimPlayer] = []
        for p: SimPlayer in sim.team_lists[1]:
            if p.role == "GK":
                ordered1.push_front(p)
            else:
                ordered1.append(p)
        for p in ordered1:
            opp_agents.append(p)
            p.controller = null
    if opp == "none":
        for p: SimPlayer in sim.team_lists[1]:
            ghosts.append(p)
    elif opp == "keeper":
        for p: SimPlayer in sim.team_lists[1]:
            if p.role != "GK":
                ghosts.append(p)
    for g in ghosts:
        _ghost(g)

    if match_mode:
        sim.kickoff_team = rng.randi() % 2
        sim._reset_positions()
        if random_start > 0.0 and rng.randf() < random_start:
            _random_layout()
    else:
        _random_start()
    prev_pot = _potential()
    prev_scores = [0, 0]
    prev_playing = true
    prev_pass = _pass_totals()
    prev_ps.clear()
    for a in agents:
        prev_ps[a.uid] = _ps_vec(a)


## Removes a player from the physics and the rule logic but keeps it in team_lists (observations).
func _ghost(g: SimPlayer) -> void:
    g.controller = null
    sim.movers.erase(g)
    sim.players.erase(g)
    g.pos = Vector2(0.0, sim.pitch.out_y * 2.5)
    g.vel = Vector2.ZERO


## Match-mode variant: every player (both teams, keepers too) and the ball anywhere on the pitch, play starts at once.
func _random_layout() -> void:
    var pt := sim.pitch
    sim.kickoff_active = false
    sim.kickoff_taker = null
    sim.state = MatchSim.State.PLAYING
    var hw := pt.half_w * 0.92
    var hh := pt.half_h * 0.92
    sim.ball.pos = Vector2(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
    sim.ball.vel = Vector2.from_angle(rng.randf() * TAU) * rng.randf_range(0.0, 3.0)
    var placed: Array[Vector2] = [sim.ball.pos]
    for p: SimPlayer in sim.players:
        var pos := Vector2.ZERO
        for _try in 40:
            pos = Vector2(rng.randf_range(-hw, hw), rng.randf_range(-hh, hh))
            var ok := true
            for q in placed:
                if q.distance_to(pos) < 45.0:
                    ok = false
                    break
            if ok:
                break
        p.pos = pos
        p.vel = Vector2.ZERO
        placed.append(pos)


func _random_start() -> void:
    var pt := sim.pitch
    sim.kickoff_active = false
    sim.kickoff_taker = null
    sim.state = MatchSim.State.PLAYING
    var hw := pt.half_w
    var hh := pt.half_h
    var bx := rng.randf_range(-hw * 0.6, hw * (0.15 + 0.45 * spread))
    if spread < 0.2:
        bx = rng.randf_range(0.0, hw * 0.35)
    sim.ball.pos = Vector2(bx, rng.randf_range(-hh * 0.8, hh * 0.8))
    var sp := rng.randf_range(0.0, ball_speed)
    sim.ball.vel = Vector2.from_angle(rng.randf() * TAU) * sp
    var placed: Array[Vector2] = [sim.ball.pos]
    var all_players: Array[SimPlayer] = []
    for p: SimPlayer in sim.players:
        all_players.append(p)
    for p in all_players:
        if p.team == 1 and p.role == "GK":
            p.pos = p.spawn                       # an opposing keeper starts on its line
            p.vel = Vector2.ZERO
            placed.append(p.pos)
            continue
        var pos := Vector2.ZERO
        for _try in 40:
            pos = Vector2(rng.randf_range(-hw * 0.9, hw * 0.5), rng.randf_range(-hh * 0.9, hh * 0.9))
            if p.team == 1:
                pos.x = -pos.x
            var ok := true
            for q in placed:
                if q.distance_to(pos) < 45.0:
                    ok = false
                    break
            if ok:
                break
        p.pos = pos
        p.vel = Vector2.ZERO
        p.input_dir = Vector2.ZERO
        p.input_kick = false
        p.in_contact = false
        placed.append(pos)
    sim.last_touch = null
    sim.assist_cand = null
    sim.pending_shot_team = -1
    for i in MatchSim.HIST:
        sim.ball_hist[i] = sim.ball.pos


func _goal_center() -> Vector2:
    return Vector2(sim.pitch.half_w, 0.0)


## Shaping potential: ball close to the opponent goal, nearest agent close to the ball.
func _potential() -> float:
    var hw := sim.pitch.half_w
    var d_goal := sim.ball.pos.distance_to(_goal_center())
    var near := 1.0e9
    for a in agents:
        near = minf(near, a.pos.distance_to(sim.ball.pos))
    return shaping * (-4.0 * d_goal / hw - 4.0 * minf(near, hw) / hw)


func _pass_totals() -> Array:
    var prog := 0
    var ok := 0
    var fail := 0
    var kp := 0
    var xa := 0.0
    for p: SimPlayer in sim.team_lists[0]:
        prog += p.ps.progressive_passes
        ok += p.ps.passes_ok
        fail += p.ps.passes_failed
        kp += p.ps.key_passes
        xa += p.ps.xa
    return [prog, ok, fail, kp, xa]


func _ps_vec(p: SimPlayer) -> Array:
    return [p.ps.passes_ok, p.ps.passes_failed, p.ps.progressive_passes, p.ps.key_passes, p.ps.xa, p.ps.passes_received]


static func _seg_dist(p: Vector2, a: Vector2, b: Vector2) -> float:
    var ab := b - a
    var l2 := ab.length_squared()
    if l2 < 0.0001:
        return p.distance_to(a)
    var t := clampf((p - a).dot(ab) / l2, 0.0, 1.0)
    return p.distance_to(a + ab * t)


## Individual reward terms, one per learner agent: kick discipline, spacing, pass credit (passer / receiver)
## and "standing open" for the ball carrier.
func _individual() -> PackedFloat32Array:
    var out := PackedFloat32Array()
    out.resize(agents.size() + opp_agents.size())
    var credit := match_mode and pass_individual
    if w_kick == 0.0 and w_space == 0.0 and not credit and w_open == 0.0 and w_keeper == 0.0:
        return out
    var bp := sim.ball.pos
    # the carrier: the learner agent that last touched the ball and is next to it
    var carrier: SimPlayer = null
    if w_open > 0.0 and sim.last_touch != null and sim.last_touch.team == 0 and agents.has(sim.last_touch) \
            and sim.last_touch.pos.distance_to(bp) < 45.0:
        carrier = sim.last_touch
    for i in agents.size():
        var a := agents[i]
        var da := a.pos.distance_to(bp)
        var r := 0.0
        if w_kick > 0.0 and a.input_kick and da > kick_reach:
            r -= w_kick
        if w_space > 0.0 and da > 70.0:
            for j in agents.size():
                if j != i:
                    var b := agents[j]
                    var d := a.pos.distance_to(b.pos)
                    if d < space_radius and b.pos.distance_to(bp) > 70.0:
                        r -= w_space * (1.0 - d / space_radius)
        if credit:
            var cur := _ps_vec(a)
            var prev: Array = prev_ps.get(a.uid, cur)
            var d_ok: int = cur[0] - prev[0]
            var d_fail: int = cur[1] - prev[1]
            var d_prog: int = cur[2] - prev[2]
            var d_kp: int = cur[3] - prev[3]
            var d_xa: float = cur[4] - prev[4]
            var d_recv: int = cur[5] - prev[5]
            r += w_pass_prog * float(d_prog) - w_pass_fail * float(d_fail)
            var coop := w_pass_ok * float(maxi(d_ok - d_prog, 0)) + w_key_pass * float(d_kp) + w_xa * d_xa + w_recv * float(d_recv)
            if coop_cap > 0.0 and coop > 0.0:
                coop = minf(coop, maxf(coop_cap - coop_used, 0.0))
                coop_used += coop
            r += coop
            prev_ps[a.uid] = cur
        if w_keeper > 0.0 and a.role == "GK":
            var dg := a.pos.distance_to(Vector2(-sim.pitch.half_w, 0.0))
            if dg > keeper_free:
                r -= w_keeper * minf((dg - keeper_free) / keeper_free, 1.0)
        if carrier != null and a != carrier:
            var dc := a.pos.distance_to(carrier.pos)
            if dc >= open_min and dc <= open_max:
                var clear := true
                for o: SimPlayer in sim.team_lists[1]:
                    if _seg_dist(o.pos, carrier.pos, a.pos) < lane_clear:
                        clear = false
                        break
                if clear:
                    r += w_open
        out[i] = r
    return out


func observe() -> PackedFloat32Array:
    var out := PackedFloat32Array()
    for a in agents:
        out.append_array(MLBot.features(sim, a, true))
    for a in opp_agents:
        out.append_array(MLBot.features(sim, a, true))
    return out


## actions: move idx (0..8) and kick (0/1) per agent, flat [m0, k0, m1, k1, ...].
## Returns [reward, done, outcome]. Does NOT auto-reset.
func step(actions: PackedByteArray) -> Array:
    var all_agents: Array[SimPlayer] = agents + opp_agents
    for i in (0 if external_actions else all_agents.size()):
        sim.set_action(all_agents[i], clampi(actions[i * 2], 0, 8), actions[i * 2 + 1] != 0)
        all_agents[i].kick_intent = ""
    for _k in REPEAT:
        sim.step()
        if not match_mode and sim.state != MatchSim.State.PLAYING:
            break
        if sim.state == MatchSim.State.ENDED:
            break
    steps += 1
    var r := -0.0005
    var done := false
    var outcome := OUT_NONE
    var playing := sim.state == MatchSim.State.PLAYING
    var pot := _potential()
    if playing and prev_playing:
        r += pot - prev_pot                       # no shaping across goals / kickoffs (the ball teleports)
    prev_pot = pot
    prev_playing = playing

    if match_mode:
        r += 10.0 * float(sim.scores[0] - prev_scores[0]) - 10.0 * float(sim.scores[1] - prev_scores[1])
        prev_scores = [sim.scores[0], sim.scores[1]]
        if sim.state == MatchSim.State.ENDED or steps >= max_steps:
            done = true
            outcome = OUT_WIN if sim.scores[0] > sim.scores[1] else (OUT_LOSS if sim.scores[0] < sim.scores[1] else OUT_DRAW)
    else:
        if sim.scores[0] > 0:
            r += 10.0
            done = true
            outcome = OUT_GOAL
        elif sim.scores[1] > 0:
            r -= 10.0
            done = true
            outcome = OUT_OWN if opp == "none" else OUT_CONCEDED
        elif steps >= max_steps:
            done = true
            outcome = OUT_TIMEOUT
    if match_mode and not pass_individual and (w_pass_prog != 0.0 or w_pass_ok != 0.0 or w_pass_fail != 0.0 or w_key_pass != 0.0 or w_xa != 0.0):
        var pt := _pass_totals()
        var d_prog: int = pt[0] - prev_pass[0]
        var d_ok: int = pt[1] - prev_pass[1]
        var d_fail: int = pt[2] - prev_pass[2]
        # progressive passes are a subset of the completed ones: pay the bonus rate for those, the base rate for the rest
        r += w_pass_prog * float(d_prog) + w_pass_ok * float(maxi(d_ok - d_prog, 0)) - w_pass_fail * float(d_fail)
        r += w_key_pass * float(int(pt[3]) - int(prev_pass[3])) + w_xa * (float(pt[4]) - float(prev_pass[4]))
        prev_pass = pt
    ep_return += r
    return [r, done, outcome, _individual()]
