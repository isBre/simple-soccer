extends Node
## Records the 8 matches of rl/behaviour_stats.gd (same configs and seeds, so the very same matches) tick by tick, for
## tests/test_evaluate.py: OUT_DIR/behaviour_<i>.bin (state after every tick, tests/state_codec.py layout) and .json (event log,
## result).   Godot --headless --path REF res://tests/godot/record_behaviour.tscn -- OUT_DIR

const Rec := preload("res://tests/godot/record_match.gd")


func _ready() -> void:
    await get_tree().process_frame
    var out_dir: String = OS.get_cmdline_user_args()[0]
    for i in 8:
        var c := MatchConfig.new()
        c.pitch = Database.pitches["arena"]
        c.team_size = 5
        c.duration = 60.0
        c.match_seed = 900 + i
        c.teams = [Database.teams["rl_team"], Database.teams[["owls", "cobalt", "tide", "dune"][i % 4]]]
        c.resolve_kits()
        var sim := MatchSim.new(c)
        sim.log_events = true
        var f := FileAccess.open(out_dir.path_join("behaviour_%d.bin" % i), FileAccess.WRITE)
        while sim.state != MatchSim.State.ENDED and sim.tick < 60 * 120:
            sim.step()
            f.store_buffer(Rec.export_state(sim).to_byte_array())
        f.close()
        var mf := FileAccess.open(out_dir.path_join("behaviour_%d.json" % i), FileAccess.WRITE)
        mf.store_string(JSON.stringify({"ev_log": sim.ev_log, "result": sim.make_result()}))
        mf.close()
    print("RECORDED")
    get_tree().quit()
