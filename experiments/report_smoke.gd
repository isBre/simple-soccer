extends Node
## Renders only the match report (several seeds) to experiments/shots/report_N.png


func _ready() -> void:
    await get_tree().process_frame
    for sd in [21, 22]:
        var rcfg := Database.make_config("cobalt", "harbor", "arena", 5, 180.0, sd)
        var sim := MatchSim.new(rcfg)
        sim.run_to_end()
        var res := sim.make_result()
        App.show_screen(ReportScreen.new().setup(res, func() -> void: pass))
        for i in 8:
            await get_tree().process_frame
        var img := get_viewport().get_texture().get_image()
        img.save_png("res://experiments/shots/report_%d.png" % sd)
        var sc: ScrollContainer = App.current.get_child(0)
        sc.scroll_vertical = 640
        for i in 4:
            await get_tree().process_frame
        get_viewport().get_texture().get_image().save_png("res://experiments/shots/report_%d_b.png" % sd)
        print("shot report ", sd, " ", res["scores"])
    print("SMOKE OK")
    get_tree().quit()
