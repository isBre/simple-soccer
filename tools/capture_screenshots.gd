extends Node
## Dev tool: drives the real UI and saves README screenshots to docs/screenshots/.
## Run: Godot --path . res://tools/capture_screenshots.tscn   (needs a window, not --headless)

const OUT := "res://docs/screenshots/"


func _ready() -> void:
    await _run()
    get_tree().quit()


func _frames(n: int) -> void:
    for i in n:
        await get_tree().process_frame


func _shot(name: String) -> void:
    await RenderingServer.frame_post_draw
    var img := get_viewport().get_texture().get_image()
    img.save_png(ProjectSettings.globalize_path(OUT + name + ".png"))
    print("saved ", name, " ", img.get_size())


func _run() -> void:
    await _frames(10)
    App.menu()
    await _frames(15)
    await _shot("menu")

    App.show_screen(QuickMatchScreen.new())
    await _frames(15)
    await _shot("quick_match")

    App.show_screen(TeamsScreen.new())
    await _frames(15)
    await _shot("teams")

    App.show_screen(TournamentSetupScreen.new())
    await _frames(15)
    await _shot("tournament_setup")

    # Live match: RL Team vs a strong team, AI vs AI, fast-forwarded to key moments.
    var cfg := Database.make_config("rl_team", "aurora", "arena", 5, 180.0, 7)
    cfg.control = MatchConfig.ControlMode.NONE
    App.play_match(cfg, func(_r): pass, func(): pass)
    await _frames(5)
    var ms: MatchScreen = App.current
    await _frames(40)
    await _shot("match_kickoff")
    await _frames(200)
    # Play at real speed, keep a ring buffer of small frames, dump a clip around each goal.
    var ring: Array = []
    var shot_play := false
    var clips := 0
    var post := -1
    var seen := 0
    var clip_frames: Array = []
    var tick := 0
    while ms.sim.state != MatchSim.State.ENDED and clips < 3:
        await RenderingServer.frame_post_draw
        tick += 1
        if tick % 3 == 0:
            var im := get_viewport().get_texture().get_image()
            im.resize(640, 360, Image.INTERPOLATE_BILINEAR)
            if post >= 0:
                clip_frames.append(im)
                post += 1
            else:
                ring.append(im)
                if ring.size() > 45:
                    ring.pop_front()
        if not shot_play and ms.sim.elapsed() > 40.0:
            shot_play = true
            await _shot("match_play")
        if post < 0 and ms.sim.events.size() > seen:
            seen = ms.sim.events.size()
            post = 0
            clip_frames = ring.duplicate()
        if post >= 70:
            var dir := ProjectSettings.globalize_path(OUT + "clip%d/" % clips)
            DirAccess.make_dir_recursive_absolute(dir)
            for i in clip_frames.size():
                clip_frames[i].save_png(dir + "f%03d.png" % i)
            print("clip ", clips, " frames ", clip_frames.size())
            clips += 1
            post = -1
            ring.clear()
            clip_frames = []
    ms.sim.run_to_end()
    ms.speed = 1
    var res := ms.sim.make_result()
    App.show_screen(ReportScreen.new().setup(res, App.menu))
    await _frames(15)
    await _shot("report")
