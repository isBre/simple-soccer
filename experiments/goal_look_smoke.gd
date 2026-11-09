extends Node
## Prints the goal frame colour chosen for each team on every pitch, with its distance from the pitch colour.


func _ready() -> void:
    await get_tree().process_frame
    var lines: PackedStringArray = []
    for pt: PitchDef in Database.pitch_list():
        for t: TeamDef in Database.team_list():
            var cfg := Database.make_config(t.id, "dune" if t.id != "dune" else "fern", pt.id, 3, 60.0, 1)
            var col := MatchView._goal_colour(cfg.kits[0], pt.color_pitch)
            lines.append("%s %s: kit %s/%s -> goal %s  dist %.2f (was %.2f)" % [pt.id, t.id, cfg.kits[0][0].to_html(false),
                cfg.kits[0][1].to_html(false), col.to_html(false), MatchView._colour_dist(col, pt.color_pitch),
                MatchView._colour_dist(cfg.kits[0][0], pt.color_pitch)])
    var f := FileAccess.open("res://experiments/results_goal_colours.txt", FileAccess.WRITE)
    f.store_string("\n".join(lines) + "\n")
    get_tree().quit()
