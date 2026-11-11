extends Node
## Dev tool: records one goal clip per scenario (different teams / pitches / sizes) into docs/screenshots/clip_<name>/.
## Run (needs a window; on a server use xvfb-run):
##   xvfb-run -a Godot --path . --resolution 1280x720 res://tools/capture_gifs.tscn
## then `python3 tools/make_gifs.py` builds docs/screenshots/<name>.gif and removes the clip folders.
## A scenario is pre-simulated headless to find the first goal, then replayed in the real MatchScreen: fast-forward
## to ~2.5 s before the goal, record at real speed.

const OUT := "res://docs/screenshots/"
# name, team 0, team 1, pitch, team size, seed
const SCENARIOS := [
    ["rl4_vs_cobalt", "rl_team_4", "cobalt", "arena", 5, 11],
    ["rl_derby", "rl_team_2", "rl_team_4", "arena", 5, 5],
    ["classic_3v3", "owls", "ember", "classic", 3, 3],
    ["pillars_5v5", "rose", "tide", "big_pillars", 5, 8],
    ["futsal_2v2", "harbor", "dune", "futsal", 2, 4],
    ["big_4v4", "arrows", "bulls", "big", 4, 6],
    ["rl3_vs_aurora", "rl_team_3", "aurora", "arena", 5, 21],
]
const PRE_TICKS := 150
const POST_FRAMES := 70
const STRIDE := 3


func _ready() -> void:
    await _frames(10)
    for sc in SCENARIOS:
        await _record(sc)
    get_tree().quit()


func _frames(n: int) -> void:
    for i in n:
        await get_tree().process_frame


func _cfg(sc: Array, seed_value: int) -> MatchConfig:
    var cfg := Database.make_config(sc[1], sc[2], sc[3], sc[4], 180.0, seed_value)
    cfg.control = MatchConfig.ControlMode.NONE
    return cfg


func _first_goal(sc: Array, seed_value: int) -> int:
    var sim := MatchSim.new(_cfg(sc, seed_value))
    var limit := 60 * 150
    while sim.state != MatchSim.State.ENDED and sim.events.is_empty() and sim.tick < limit:
        sim.step()
    return sim.tick if not sim.events.is_empty() else -1


func _record(sc: Array) -> void:
    var seed_value: int = sc[5]
    var goal_tick := -1
    for attempt in 4:
        goal_tick = _first_goal(sc, seed_value)
        if goal_tick > 400:
            break
        seed_value += 1
    if goal_tick < 0:
        print("no goal for ", sc[0])
        return
    print(sc[0], ": goal at tick ", goal_tick, " seed ", seed_value)
    App.play_match(_cfg(sc, seed_value), func(_r): pass, func(): pass)
    await _frames(3)
    var ms: MatchScreen = App.current
    ms.speed = 8
    while ms.sim.tick < goal_tick - PRE_TICKS - 20 and ms.sim.state != MatchSim.State.ENDED:
        await get_tree().physics_frame
    ms.speed = 1
    var frames: Array = []
    var tick := 0
    var post := -1
    var guard := 0
    while post < POST_FRAMES and guard < 3000:
        guard += 1
        await RenderingServer.frame_post_draw
        tick += 1
        if tick % STRIDE == 0:
            var im := get_viewport().get_texture().get_image()
            im.resize(640, 360, Image.INTERPOLATE_BILINEAR)
            frames.append(im)
            if post >= 0:
                post += 1
        if post < 0 and not ms.sim.events.is_empty():
            post = 0
    var dir := ProjectSettings.globalize_path(OUT + "clip_%s/" % sc[0])
    DirAccess.make_dir_recursive_absolute(dir)
    for i in frames.size():
        frames[i].save_png(dir + "f%03d.png" % i)
    print("clip ", sc[0], " frames ", frames.size())
    App.menu()
    await _frames(5)
