extends Node
## Shows live matches of the newest training checkpoint (out_5v5/ckpt/<tag>_u*.json) against random rule teams.
## Needs a window: Godot --path . res://tools/watch_training.tscn -- --tag jit1

const OPPS := ["aurora", "cobalt", "ember", "granite", "onyx", "tide", "bulls", "arrows", "rose", "dune"]
var tag := "jit2"
var rng := RandomNumberGenerator.new()


func _ready() -> void:
    var a := OS.get_cmdline_user_args()
    for i in a.size() - 1:
        if a[i] == "--tag":
            tag = a[i + 1]
    rng.randomize()
    get_viewport().msaa_2d = Viewport.MSAA_DISABLED
    await get_tree().process_frame
    _next()


func _latest() -> String:
    var dir := DirAccess.open("res://out_5v5/ckpt")
    var best := -1
    var best_name := ""
    if dir != null:
        for f in dir.get_files():
            if f.begins_with(tag + "_u") and f.ends_with(".json"):
                var n := int(f.trim_prefix(tag + "_u").trim_suffix(".json"))
                if n > best:
                    best = n
                    best_name = f
    return "res://out_5v5/ckpt/" + best_name if best_name != "" else "res://data/models/rl_5v5_arena_v5.json"


func _next() -> void:
    print("watching newest ", tag, " checkpoint (served by tools/net_server.py)")
    var cfg := Database.make_config("rl_team_5", "rl_team_4", "arena", 5, 90.0, rng.randi())
    cfg.control = MatchConfig.ControlMode.NONE
    cfg.ml_models[0] = RemoteMLP.new(7301)
    cfg.ml_models[1] = RemoteMLP.new(7302)
    cfg.ml_keeper = true
    App.play_match(cfg, func(_r): _next.call_deferred(), func(): get_tree().quit())
    # no keyboard needed: once the final whistle has blown, continue by itself after a short pause
    var ms: MatchScreen = App.current
    while is_instance_valid(ms) and ms.sim.state != MatchSim.State.ENDED:
        await get_tree().create_timer(1.0).timeout
    if is_instance_valid(ms) and App.current == ms:
        await get_tree().create_timer(4.0).timeout
        if is_instance_valid(ms) and App.current == ms:
            ms.finished.emit(ms.sim.make_result())
