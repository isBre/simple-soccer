extends Node
## Records the training environments of tests/env_scenarios.json in Godot's rl_env.gd (the reference checkout), every step:
## the env's bookkeeping, the match state (tests/state_codec.py layout), the actions, the AI's inputs of each tick, the
## rewards and the observations. Needs the TAP hook in the reference's match_sim.gd (added by tests/test_env.py --record).
##   Godot --headless --path REF res://tests/godot/record_env.tscn -- OUT_DIR [names...]

const Rec := preload("res://tests/godot/record_match.gd")
var taps: Array = []


func _tap(sim: MatchSim) -> void:
    var inp := []
    for t in 2:
        for p: SimPlayer in sim.team_lists[t]:
            inp.append([p.input_dir.x, p.input_dir.y, p.input_kick, p.kick_intent])
    taps.append({"tick": sim.tick, "inputs": inp, "keepers": [sim.keeper_uid[0], sim.keeper_uid[1]]})


static func env_state(e: RLEnv) -> Dictionary:
    return {"steps": e.steps, "ep_return": e.ep_return, "prev_pot": e.prev_pot, "prev_scores": e.prev_scores.duplicate(),
        "prev_playing": e.prev_playing, "prev_pass": e.prev_pass.duplicate(), "coop_used": e.coop_used, "xg_used": e.xg_used, "def_used": e.def_used, "prev_opp_xg": e.prev_opp_xg,
        "rng": [e.rng.state & 0xffffffff, (e.rng.state >> 32) & 0xffffffff], "prev_ps": e.prev_ps.duplicate(true),
        "prev_def": e.prev_def.duplicate(true), "prev_dir": _vecs(e.prev_dir), "wall_streak": e.wall_streak.duplicate(),
        "term_sums": e.term_sums.duplicate(), "term_steps": e.term_steps,
        "agents": e.agents.map(func(p): return p.uid), "opp_agents": e.opp_agents.map(func(p): return p.uid),
        "used_selfplay": e.used_selfplay, "movers": e.sim.movers.size(), "players": e.sim.players.map(func(p): return p.uid)}


static func _vecs(d: Dictionary) -> Dictionary:
    var o := {}
    for k in d:
        o[k] = [d[k].x, d[k].y]
    return o


func _ready() -> void:
    await get_tree().process_frame
    var args := OS.get_cmdline_user_args()
    var out_dir: String = args[0]
    var only: Array = args.slice(1)
    var spec = JSON.parse_string(FileAccess.get_file_as_string("res://tests/env_scenarios.json"))
    MatchSim.TAP = _tap
    for sc: Dictionary in spec["scenarios"]:
        if not only.is_empty() and not only.has(sc["name"]):
            continue
        _record(sc, out_dir)
    print("RECORDED")
    get_tree().quit()


func _record(sc: Dictionary, out_dir: String) -> void:
    var e := RLEnv.new()
    var c: Dictionary = sc["cfg"].duplicate()
    c["seed"] = 4242
    e.configure(c)
    if sc.has("selfplay_net"):
        e.opp_net = {"model": ProjectSettings.globalize_path(sc["selfplay_net"])}
    var arng := RandomNumberGenerator.new()
    arng.seed = 99
    var bin := FileAccess.open(out_dir.path_join(sc["name"] + ".bin"), FileAccess.WRITE)
    var lines := FileAccess.open(out_dir.path_join(sc["name"] + ".jsonl"), FileAccess.WRITE)
    var pre_rng := [e.rng.state & 0xffffffff, (e.rng.state >> 32) & 0xffffffff]
    taps.clear()
    e.reset()
    bin.store_buffer(Rec.export_state(e.sim).to_byte_array())
    lines.store_line(JSON.stringify({"kind": "reset", "pre_rng": pre_rng, "env": env_state(e), "obs": Array(e.observe()), "taps": taps}))
    for s in int(sc["steps"]):
        var n := e.n_agents()
        var acts := PackedByteArray()
        for k in n:
            acts.append(arng.randi() % 9)
            acts.append(1 if arng.randf() < 0.2 else 0)
        var before := env_state(e)
        bin.store_buffer(Rec.export_state(e.sim).to_byte_array())
        taps.clear()
        var res := e.step(acts)
        var rec := {"kind": "step", "env": before, "actions": Array(acts), "taps": taps.duplicate(), "r": res[0], "done": res[1],
            "outcome": res[2], "indiv": Array(res[3]), "after": env_state(e)}
        bin.store_buffer(Rec.export_state(e.sim).to_byte_array())
        if res[1]:
            rec["pre_rng"] = [e.rng.state & 0xffffffff, (e.rng.state >> 32) & 0xffffffff]
            taps.clear()
            e.reset()
            rec["reset_env"] = env_state(e)
            rec["reset_taps"] = taps.duplicate()
            bin.store_buffer(Rec.export_state(e.sim).to_byte_array())
        rec["obs"] = Array(e.observe())
        lines.store_line(JSON.stringify(rec))
    bin.close()
    lines.close()
    print("  %s: %d steps" % [sc["name"], int(sc["steps"])])
