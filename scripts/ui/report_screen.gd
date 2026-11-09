class_name ReportScreen
extends Control
## Post-match report: score, scorers, team stats and a grade for every player.

var res: Dictionary
var on_continue: Callable


func setup(result: Dictionary, cont: Callable) -> ReportScreen:
    res = result
    on_continue = cont
    return self


func _ready() -> void:
    var teams: Array[TeamDef] = [Database.teams[res["teams"][0]], Database.teams[res["teams"][1]]]
    var scroll := ScrollContainer.new()
    scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    add_child(scroll)
    var page := UIKit.vbox(16)
    page.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(UIKit.margin(page, 32))
    scroll.get_child(0).size_flags_horizontal = Control.SIZE_EXPAND_FILL

    # header
    var head := UIKit.hbox(24)
    head.alignment = BoxContainer.ALIGNMENT_CENTER
    head.add_child(LogoView.new(teams[0], 84))
    head.add_child(UIKit.label(teams[0].name, 32, Color.WHITE, HORIZONTAL_ALIGNMENT_RIGHT))
    head.add_child(UIKit.label("%d - %d" % [res["scores"][0], res["scores"][1]], 64, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER))
    head.add_child(UIKit.label(teams[1].name, 32))
    head.add_child(LogoView.new(teams[1], 84))
    page.add_child(head)

    var note := "Full time"
    if not res["shootout"].is_empty():
        note = "Decided on penalties: %d - %d" % [res["shootout"][0], res["shootout"][1]]
    elif res["overtime"]:
        note = "Golden goal in overtime"
    elif res["winner"] == -1:
        note = "Full time - draw"
    page.add_child(UIKit.label(note, 18, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))

    # scorers
    var sc := UIKit.hbox(60)
    sc.alignment = BoxContainer.ALIGNMENT_CENTER
    for t in 2:
        var col := UIKit.vbox(2)
        col.custom_minimum_size = Vector2(380, 0)
        var al := HORIZONTAL_ALIGNMENT_RIGHT if t == 0 else HORIZONTAL_ALIGNMENT_LEFT
        col.add_child(UIKit.label(teams[t].name, 14, teams[t].color_primary.lightened(0.25), al))
        var n_goals := 0
        for e: Dictionary in res["events"]:
            if int(e["team"]) == t:
                n_goals += 1
                var txt := "%d' %s%s" % [int(float(e["clock"]) / 60.0) + 1, e["scorer_name"], " (OG)" if e["own"] else ""]
                if e["assist_name"] != "":
                    txt += "   (assist %s)" % e["assist_name"]
                col.add_child(UIKit.label(txt, 16, UIKit.TEXT, HORIZONTAL_ALIGNMENT_RIGHT if t == 0 else HORIZONTAL_ALIGNMENT_LEFT))
        if n_goals == 0:
            col.add_child(UIKit.label("no goals", 15, UIKit.MUTED, al))
        sc.add_child(col)
    page.add_child(sc)

    # team stats
    var ts: Array = res["team_stats"]
    var sg := GridContainer.new()
    sg.columns = 3
    sg.add_theme_constant_override("h_separation", 60)
    sg.add_theme_constant_override("v_separation", 6)
    var rows := [
        ["Possession", "%.0f%%" % ts[0]["possession"], "%.0f%%" % ts[1]["possession"], ts[0]["possession"], ts[1]["possession"]],
        ["Shots", str(ts[0]["shots"]), str(ts[1]["shots"]), ts[0]["shots"], ts[1]["shots"]],
        ["On target", str(ts[0]["shots_on_target"]), str(ts[1]["shots_on_target"]), ts[0]["shots_on_target"], ts[1]["shots_on_target"]],
        ["Passes (completed)", "%d (%d)" % [ts[0]["passes"], ts[0]["passes_ok"]], "%d (%d)" % [ts[1]["passes"], ts[1]["passes_ok"]], ts[0]["passes_ok"], ts[1]["passes_ok"]],
        ["Expected goals (xG)", "%.1f" % ts[0]["xg"], "%.1f" % ts[1]["xg"], ts[0]["xg"], ts[1]["xg"]],
        ["Tackles / interceptions", str(ts[0]["recoveries"]), str(ts[1]["recoveries"]), ts[0]["recoveries"], ts[1]["recoveries"]],
        ["Dribbles won", str(ts[0]["dribbles"]), str(ts[1]["dribbles"]), ts[0]["dribbles"], ts[1]["dribbles"]],
        ["Saves", str(ts[0]["saves"]), str(ts[1]["saves"]), ts[0]["saves"], ts[1]["saves"]],
    ]
    var centre := CenterContainer.new()
    for r: Array in rows:
        var lc := UIKit.ACCENT if float(r[3]) > float(r[4]) else UIKit.TEXT
        var rc := UIKit.ACCENT if float(r[4]) > float(r[3]) else UIKit.TEXT
        sg.add_child(UIKit.label(r[1], 18, lc, HORIZONTAL_ALIGNMENT_RIGHT))
        var mid := UIKit.label(r[0], 16, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER)
        mid.custom_minimum_size = Vector2(240, 0)
        sg.add_child(mid)
        sg.add_child(UIKit.label(r[2], 18, rc))
    centre.add_child(UIKit.card(sg))
    page.add_child(centre)

    # player tables
    for t in 2:
        page.add_child(UIKit.label(teams[t].name + " - player ratings", UIKit.FS_H2, UIKit.TEXT))
        page.add_child(_player_table(t))

    var mom_name := ""
    var mom_why := ""
    for p: Dictionary in res["players"]:
        if int(p["uid"]) == int(res["mom"]):
            mom_name = "%s (%s) - %.1f" % [p["name"], teams[int(p["team"])].name, p["rating"]]
            mom_why = _why(p)
    page.add_child(UIKit.label("Man of the match:  " + mom_name, 20, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER))
    if mom_why != "":
        page.add_child(UIKit.label(mom_why, UIKit.FS_CAPTION, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))

    var b := UIKit.primary_button("Continue  (Enter)", func() -> void: on_continue.call(), Vector2(260, 52))
    b.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    page.add_child(b)


## Short "why this grade" line made of the player's most notable contributions.
func _why(p: Dictionary) -> String:
    var parts: PackedStringArray = []
    var items := [["goals", "goal", "goals"], ["assists", "assist", "assists"], ["saves", "save", "saves"],
        ["key_passes", "key pass", "key passes"], ["tackles", "tackle", "tackles"],
        ["interceptions", "interception", "interceptions"], ["dribbles", "dribble won", "dribbles won"],
        ["progressive_passes", "progressive pass", "progressive passes"],
        ["clearances", "clearance", "clearances"]]
    for it: Array in items:
        var n := int(p[it[0]])
        if n > 0:
            parts.append("%d %s" % [n, it[1] if n == 1 else it[2]])
    if float(p["xg"]) >= 0.5:
        parts.append("%.1f xG" % p["xg"])
    return ", ".join(parts.slice(0, 5))


func _player_table(team: int) -> Control:
    var cols := [
        {"title": "#", "w": 44, "align": "l"},
        {"title": "Player", "w": 0, "align": "l"},
        {"title": "Pos", "w": 64, "align": "l"},
        {"title": "Grade", "w": 80, "align": "r"},
        {"title": "G", "w": 48, "align": "r"},
        {"title": "A", "w": 48, "align": "r"},
        {"title": "Shots", "w": 80, "align": "r"},
        {"title": "Passes", "w": 90, "align": "r"},
        {"title": "Key", "w": 52, "align": "r"},
        {"title": "Tkl", "w": 52, "align": "r"},
        {"title": "Int", "w": 52, "align": "r"},
        {"title": "Drb", "w": 52, "align": "r"},
        {"title": "Sv", "w": 52, "align": "r"},
    ]
    var out: Array = []
    for p: Dictionary in res["players"]:
        if int(p["team"]) != team:
            continue
        var is_mom := int(p["uid"]) == int(res["mom"])
        var nm: String = ("★ " if is_mom else "") + str(p["name"])
        out.append({
            "cells": [
                {"text": str(p["number"]), "color": UIKit.MUTED},
                {"text": nm, "color": UIKit.ACCENT if is_mom else UIKit.TEXT},
                {"text": str(p["played"]), "color": UIKit.MUTED},
                {"text": "%.1f" % p["rating"], "color": UIKit.rating_color(float(p["rating"])), "size": 20},
                str(p["goals"]), str(p["assists"]),
                "%d/%d" % [p["shots_on_target"], p["shots"]],
                "%d/%d" % [p["passes_ok"], int(p["passes_ok"]) + int(p["passes_failed"])],
                str(p["key_passes"]), str(p["tackles"]), str(p["interceptions"]),
                str(p["dribbles"]), str(p["saves"]),
            ],
            "highlight": is_mom,
        })
    return UIKit.table(cols, out)


func _unhandled_input(e: InputEvent) -> void:
    if e is InputEventKey and e.pressed and not e.echo and (e.keycode == KEY_ENTER or e.keycode == KEY_KP_ENTER):
        get_viewport().set_input_as_handled()
        on_continue.call()
