extends Node
## Headless speed benchmark: rule-vs-rule matches (ticks/s) and the RL training environment (steps/s, rule opponents),
## both with the AI in the brain server.  Godot --headless --path . res://tools/bench_sim.tscn

func _ready() -> void:
    await get_tree().process_frame
    var ids := ["aurora", "cobalt", "granite", "tide"]
    var t0 := Time.get_ticks_usec()
    var ticks := 0
    for i in 4:
        var cfg := Database.make_config(ids[i], ids[(i + 1) % 4], "arena", 5, 60.0, 100 + i)
        var sim := MatchSim.new(cfg)
        sim.run_to_end()
        ticks += sim.tick
        print("match ", i, " ", sim.scores)
    var dt := (Time.get_ticks_usec() - t0) / 1e6
    print("rules: %d ticks in %.2f s = %.0f ticks/s" % [ticks, dt, ticks / dt])
    var e := RLEnv.new()
    e.configure({"pitch": "arena", "size": 5, "n_active": 5, "with_keeper": true, "opp": "aurora,cobalt,granite", "match_mode": true,
        "duration": 90.0, "obs": "team", "seed": 3, "own_team": "owls"})
    e.reset()
    var rng := RandomNumberGenerator.new()
    rng.seed = 5
    var acts := PackedByteArray()
    acts.resize(10)
    t0 = Time.get_ticks_usec()
    var n := 2000
    for s in n:
        for k in 5:
            acts[k * 2] = rng.randi() % 9
            acts[k * 2 + 1] = rng.randi() % 2
        var r := e.step(acts)
        e.observe()
        if r[1]:
            e.reset()
    dt = (Time.get_ticks_usec() - t0) / 1e6
    print("env: %d steps in %.2f s = %.0f steps/s" % [n, dt, n / dt])
    get_tree().quit()
