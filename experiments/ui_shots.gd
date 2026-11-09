extends Node
## Captures mid-play screenshots into res://experiments/shots2/.

func _ready() -> void:
    await get_tree().process_frame
    await _run()
    print("SHOTS OK")
    get_tree().quit()

func _shot(n: String) -> void:
    for i in 3:
        await get_tree().process_frame
    get_viewport().get_texture().get_image().save_png("res://experiments/shots2/%s.png" % n)
    print("shot ", n)

func _play(cfg: MatchConfig, secs: float, n: String) -> void:
    App.play_match(cfg, func(_r: Dictionary) -> void: pass, func() -> void: pass)
    await get_tree().create_timer(secs).timeout
    await _shot(n)

func _run() -> void:
    var c1 := Database.make_config("aurora", "borealis", "classic", 3, 180.0, 31)
    c1.control = MatchConfig.ControlMode.NONE
    await _play(c1, 25.0, "a_classic_play")
    var c2 := Database.make_config("dune", "fern", "big", 5, 180.0, 32)
    c2.control = MatchConfig.ControlMode.NONE
    await _play(c2, 25.0, "b_big_5v5_play")
    var c3 := Database.make_config("granite", "ember", "big_pillars", 5, 180.0, 33)
    c3.control = MatchConfig.ControlMode.NONE
    await _play(c3, 25.0, "c_pillars_play")
    var rcfg := Database.make_config("cobalt", "harbor", "classic", 3, 120.0, 21)
    var sim := MatchSim.new(rcfg)
    sim.run_to_end()
    App.show_screen(ReportScreen.new().setup(sim.make_result(), func() -> void: pass))
    await _shot("d_report")
    App.show_screen(QuickMatchScreen.new())
    await _shot("e_quickmatch")
