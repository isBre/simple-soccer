extends Node
## Plays a match until the first goal, renders the celebration and checks the kickoff-circle rule.
## Output goes to experiments/results_celebration.txt

var log_lines: PackedStringArray = []


func _say(t: String) -> void:
    print(t)
    log_lines.append(t)


func _ready() -> void:
    await get_tree().process_frame
    var cfg := Database.make_config("aurora", "borealis", "arena", 5, 180.0, 31)
    var sim := MatchSim.new(cfg)
    var guard := 0
    while sim.state != MatchSim.State.GOAL and guard < 60000:
        guard += 1
        sim.step()
    _say("goal after %d ticks; scorer %s" % [guard, sim.goal_scorer.def.name if sim.goal_scorer != null else "none"])
    var v := MatchView.new()
    v.sim = sim
    v.position = Vector2(640, 360)
    v.scale = Vector2(0.9, 0.9)
    v.z_index = 100
    add_child(v)
    var dmin := 1e9
    var dmax := 0.0
    var travelled := 0.0
    var last := sim.goal_scorer.pos
    for i in 150:
        sim.step()
        var d := sim.goal_scorer.pos.distance_to(sim.goal_center)
        if i > 40:
            dmin = minf(dmin, d)
            dmax = maxf(dmax, d)
        travelled += sim.goal_scorer.pos.distance_to(last)
        last = sim.goal_scorer.pos
    _say("scorer lap: distance from centre %.0f..%.0f, travelled %.0f px, human=%s" % [dmin, dmax, travelled, str(sim.goal_scorer.is_human)])
    v.position = Vector2(get_viewport().get_visible_rect().size.x * 0.5, get_viewport().get_visible_rect().size.y * 0.55)
    v.scale = Vector2(0.75, 0.75)
    for i in 10:
        v.queue_redraw()
        await get_tree().process_frame
    get_viewport().get_texture().get_image().save_png("res://experiments/shots/celebration.png")
    if sim.goal_scorer != null:
        var ds: PackedStringArray = []
        for m: SimPlayer in sim.team_lists[sim.goal_team]:
            ds.append("%.0f" % m.pos.distance_to(sim.goal_scorer.pos))
        _say("mate distances to scorer after 150 ticks: " + ", ".join(ds))
    var wait := 0
    while sim.state == MatchSim.State.GOAL and wait < 600:
        wait += 1
        sim.step()
    _say("state after pause: %d kickoff_active %s" % [sim.state, str(sim.kickoff_active)])
    var kt := sim.kickoff_team
    var dirx := 1.0 if kt == 0 else -1.0
    var p: SimPlayer = sim.team_lists[kt][1]
    p.controller = null      # drive him by hand
    p.pos = Vector2(-dirx * 60.0, 0.0)
    var crossed := false
    var maxd := 0.0
    for i in 200:
        p.input_dir = Vector2(dirx, 0.0)
        sim.kickoff_taker = null
        sim.kickoff_active = true
        sim.ball.pos = Vector2(0.0, 250.0)
        sim.ball.vel = Vector2.ZERO
        sim.step()
        sim.kickoff_active = true
        if p.pos.x * dirx > 0.0:
            crossed = true
        maxd = maxf(maxd, p.pos.length())
    _say("kickoff team player crossed midline: %s, max dist from centre %.0f (circle r %.0f)" % [str(crossed), maxd, sim.pitch.center_r])
    _say("SMOKE OK")
    var f := FileAccess.open("res://experiments/results_celebration.txt", FileAccess.WRITE)
    f.store_string("\n".join(log_lines) + "\n")
    await get_tree().create_timer(25.0).timeout
    get_tree().quit()
