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
var opp_net: MLP = null
var own_keeper := true            # only used when the keeper is not controlled: keep the rule-based one?
var external_actions := false     # true -> step() leaves the players' inputs alone (set by MLBot etc.)

var sim: MatchSim
var agents: Array[SimPlayer] = []
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
    own_keeper = bool(c.get("own_keeper", opp != "none"))
    if c.has("seed"):
        rng.seed = int(c["seed"])


func obs_dim() -> int:
    return OBS_DIM


func n_agents() -> int:
    return n_active


func reset() -> void:
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
    else:
        _random_start()
    prev_pot = _potential()
    prev_scores = [0, 0]
    prev_playing = true


## Removes a player from the physics and the rule logic but keeps it in team_lists (observations).
func _ghost(g: SimPlayer) -> void:
    g.controller = null
    sim.movers.erase(g)
    sim.players.erase(g)
    g.pos = Vector2(0.0, sim.pitch.out_y * 2.5)
    g.vel = Vector2.ZERO


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


func observe() -> PackedFloat32Array:
    var out := PackedFloat32Array()
    for a in agents:
        out.append_array(MLBot.features(sim, a, true))
    return out


## actions: move idx (0..8) and kick (0/1) per agent, flat [m0, k0, m1, k1, ...].
## Returns [reward, done, outcome]. Does NOT auto-reset.
func step(actions: PackedByteArray) -> Array:
    for i in (0 if external_actions else agents.size()):
        sim.set_action(agents[i], clampi(actions[i * 2], 0, 8), actions[i * 2 + 1] != 0)
        agents[i].kick_intent = ""
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
    ep_return += r
    return [r, done, outcome]
