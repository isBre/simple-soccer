extends Node
## Headless benchmark: where does a tick go?  Godot --headless --path . res://tools/bench_sim.tscn
## Needs `python3 tools/net_server.py --port 7301 --model data/models/rl_5v5_arena_v5.json` for the remote-net part.

const TICKS := 1200


func _ready() -> void:
    await get_tree().process_frame
    var cfg := Database.make_config("aurora", "cobalt", "arena", 5, 90.0, 3)
    print("rule bots only:       %6.0f ticks/s" % _ticks_per_s(MatchSim.new(cfg)))
    cfg = Database.make_config("aurora", "cobalt", "arena", 5, 90.0, 3)
    cfg.ml_models = [RemoteMLP.new(7301), RemoteMLP.new(7301)]
    cfg.ml_keeper = true
    var sim := MatchSim.new(cfg)
    print("two remote-net teams: %6.0f ticks/s (60 needed)" % _ticks_per_s(sim))
    var p: SimPlayer = sim.players[1]
    var t := Time.get_ticks_usec()
    for i in 2000:
        MLBot.features(sim, p, true)
    print("features():           %6.1f us/call" % ((Time.get_ticks_usec() - t) / 2000.0))
    var f := MLBot.features(sim, p, true)
    var net: RemoteMLP = cfg.ml_models[0]
    t = Time.get_ticks_usec()
    for i in 2000:
        net.forward(f)
    print("remote forward():     %6.1f us/call" % ((Time.get_ticks_usec() - t) / 2000.0))
    get_tree().quit()


func _ticks_per_s(sim: MatchSim) -> float:
    var t := Time.get_ticks_usec()
    for i in TICKS:
        sim.step()
    return TICKS * 1e6 / (Time.get_ticks_usec() - t)
