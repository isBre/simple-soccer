extends Node
## Opens Quick Match, presses "Random teams" repeatedly, checks the teams are always different.


func _ready() -> void:
    await get_tree().process_frame
    var q := QuickMatchScreen.new()
    App.show_screen(q)
    await get_tree().process_frame
    var same := 0
    var seen: Dictionary = {}
    for i in 200:
        q._randomize_teams()
        if q.team_opt[0].selected == q.team_opt[1].selected:
            same += 1
        seen[q.team_opt[0].selected] = true
    for i in 6:
        await get_tree().process_frame
    get_viewport().get_texture().get_image().save_png("res://experiments/shots/quick_random.png")
    var f := FileAccess.open("res://experiments/results_quick.txt", FileAccess.WRITE)
    f.store_string("same-team picks: %d / 200, distinct home teams seen: %d\n%s vs %s\n" % [same, seen.size(),
        q.teams[q.team_opt[0].selected].name, q.teams[q.team_opt[1].selected].name])
    get_tree().quit()
