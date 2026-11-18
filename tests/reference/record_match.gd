extends Node
## Records the matches of tests/scenarios.json in Godot's MatchSim, every tick: the complete match state (the vector layout
## of tests/state_codec.py), so tests/test_match.py can replay them tick by tick in Python's soccer.match.
##   Godot --headless --path . res://tests/godot/record_match.tscn -- OUT_DIR [scenario names...]
## Writes OUT_DIR/<name>.bin (float64 state vectors, one per tick, before the step; the last one after the final step) and
## OUT_DIR/<name>.json (setup, players, events, kickoff waits, result).

const KINDS := ["", "touch", "pass", "shot", "clear"]
const INTENTS := ["", "pass", "shoot", "clear", "long"]
const PS_INT := ["touches", "passes_ok", "passes_failed", "passes_received", "progressive_passes", "key_passes", "shots",
    "shots_on_target", "goals", "assists", "own_goals", "big_chances", "big_scored", "tackles", "interceptions",
    "recoveries", "clearances", "blocks", "saves", "dribbles", "dispossessed", "conceded", "scored_for", "keeper_ticks"]
const PS_FLOAT := ["pass_value", "xg", "xa", "save_xg", "conceded_xg", "carry_dist", "distance", "rating"]


static func _uid(p) -> int:
    return p.uid if p != null else -1


static func _b(v: bool) -> float:
    return 1.0 if v else 0.0


static func export_state(sim: MatchSim) -> PackedFloat64Array:
    var v := PackedFloat64Array()
    v.append_array([sim.tick, sim.state, sim.scores[0], sim.scores[1], sim.time_left, _b(sim.overtime), sim.ot_left,
        sim.goal_timer, _uid(sim.goal_scorer), sim.goal_pause, sim.goal_center.x, sim.goal_center.y, sim.goal_team, sim.winner,
        _b(sim.kickoff_active), sim.kickoff_team, _uid(sim.kickoff_taker), sim.kickoff_dir.x, sim.kickoff_dir.y, sim.kickoff_go,
        sim.kickoff_start, _uid(sim.last_touch), sim.last_touch_tick, _b(sim.last_touch_kicked), KINDS.find(sim.last_touch_kind),
        _uid(sim.assist_cand), sim.assist_tick, sim.pending_shot_team, sim.pending_shot_tick, _uid(sim.pending_shot_player),
        sim.pending_shot_xg, sim.last_shot_xg, _uid(sim.last_shot_player), _uid(sim.carry_p), sim.carry_start.x, sim.carry_start.y,
        sim.carry_last.x, sim.carry_last.y, _b(sim.carry_pressed), sim.kick_pos.x, sim.kick_pos.y, sim.kick_dir.x, sim.kick_dir.y,
        _b(sim.kick_pressed), _uid(sim.team_touch_player[0]), _uid(sim.team_touch_player[1]), sim.team_touch_tick[0],
        sim.team_touch_tick[1], sim.hist_idx, sim.idle_ticks])
    v.append_array(sim.zone_ticks)
    v.append_array([sim.stats.possession_ticks[0], sim.stats.possession_ticks[1], _uid(sim.controlled), sim.human_dir.x,
        sim.human_dir.y, _b(sim.human_kick), sim.keeper_uid[0], sim.keeper_uid[1], sim.reset_count,
        sim.rng.state & 0xffffffff, (sim.rng.state >> 32) & 0xffffffff, sim.mom_uid, sim.events.size(), sim.kickoff_waits.size(),
        sim.shootout[0] if sim.shootout.size() == 2 else -1, sim.shootout[1] if sim.shootout.size() == 2 else -1,
        sim.ball.pos.x, sim.ball.pos.y, sim.ball.vel.x, sim.ball.vel.y])
    for i in MatchSim.HIST:
        v.append(sim.ball_hist[i].x)
        v.append(sim.ball_hist[i].y)
    for t in 2:
        for p: SimPlayer in sim.team_lists[t]:
            v.append_array([p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.input_dir.x, p.input_dir.y, _b(p.input_kick), _b(p.kick_used),
                _b(p.in_contact), p.rec_tick, _b(p.is_human), _b(p.bot), INTENTS.find(p.kick_intent)])
            for k in PS_INT:
                v.append(p.ps.get(k))
            for k in PS_FLOAT:
                v.append(p.ps.get(k))
    return v


func _ready() -> void:
    await get_tree().process_frame
    var args := OS.get_cmdline_user_args()
    var out_dir: String = args[0]
    var only: Array = args.slice(1)
    var spec = JSON.parse_string(FileAccess.get_file_as_string("res://tests/scenarios.json"))
    var done := 0
    for sc: Dictionary in spec["scenarios"]:
        if not only.is_empty() and not only.has(sc["name"]):
            continue
        _record(sc, spec["pitches"], out_dir)
        done += 1
    print("RECORDED %d" % done)
    get_tree().quit()


func _record(sc: Dictionary, pitches: Dictionary, out_dir: String) -> void:
    var pid: String = sc["pitch"]
    var cfg := Database.make_config(sc["home"], sc["away"], pid if Database.pitches.has(pid) else "arena", int(sc["size"]),
        float(sc["duration"]), int(sc["seed"]))
    if pitches.has(pid):
        cfg.pitch = PitchDef.from_dict(pitches[pid])
    cfg.control = int(sc.get("control", 0)) as MatchConfig.ControlMode
    cfg.human_team = int(sc.get("human_team", 0))
    cfg.auto_switch = bool(sc.get("auto_switch", false))
    cfg.allow_draw = bool(sc.get("allow_draw", true))
    cfg.overtime = float(sc.get("overtime", 60.0))
    cfg.score_limit = int(sc.get("score_limit", 0))
    cfg.net_temperature = float(sc.get("temperature", 1.0))
    var sim := MatchSim.new(cfg)
    var hr := RandomNumberGenerator.new()
    hr.seed = int(sc["seed"]) * 7 + 1
    var hdir := Vector2.ZERO
    var f := FileAccess.open(out_dir.path_join(sc["name"] + ".bin"), FileAccess.WRITE)
    var n := 0
    while sim.state != MatchSim.State.ENDED and sim.tick < 60 * 60 * 8:
        if sim.controlled != null:           # a scripted human: random walk with kicks, switches in TEAM mode
            if sim.tick % 12 == 0:
                hdir = MatchSim.DIRS[hr.randi() % 9].normalized()
            var kick := hr.randf() < 0.15
            if sim.kickoff_active and sim.kickoff_taker == sim.controlled:     # takes his kickoffs
                sim.set_human_input((sim.ball.pos - sim.controlled.pos).normalized(), true)
            else:
                sim.set_human_input(hdir, kick)
            if cfg.control == MatchConfig.ControlMode.TEAM and sim.tick % 90 == 45:
                sim.switch_controlled()
        f.store_buffer(export_state(sim).to_byte_array())
        sim.step()
        n += 1
    f.store_buffer(export_state(sim).to_byte_array())
    f.close()
    var players := []
    for t in 2:
        for p: SimPlayer in sim.team_lists[t]:
            players.append({"uid": p.uid, "id": p.def.id, "role": p.role})
    var meta := {"scenario": sc, "ticks": n, "events": sim.events, "kickoff_waits": sim.kickoff_waits, "players": players,
        "result": sim.make_result(), "nets": sim.cfg.nets}
    var mf := FileAccess.open(out_dir.path_join(sc["name"] + ".json"), FileAccess.WRITE)
    mf.store_string(JSON.stringify(meta))
    mf.close()
    print("  %s: %d ticks, %d-%d" % [sc["name"], n, sim.scores[0], sim.scores[1]])
