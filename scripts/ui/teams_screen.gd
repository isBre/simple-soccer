class_name TeamsScreen
extends Control
## Browse teams: identity, style and squads with attributes.

var teams: Array[TeamDef] = []
var detail: VBoxContainer
var list_buttons: Array[Button] = []
var current := 0

const StarsView := preload("res://scripts/ui/stars_view.gd")


func _ready() -> void:
    teams = Database.team_list()
    var page := UIKit.vbox(UIKit.SP_16)
    var mc := UIKit.margin(page, UIKit.SP_32)
    mc.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(mc)
    var head := UIKit.hbox(UIKit.SP_12)
    page.add_child(head)
    head.add_child(UIKit.screen_header("Teams & Squads", "Identity, play style and squad attributes."))
    head.add_child(UIKit.spacer())
    head.add_child(UIKit.ghost_button("Back", func() -> void: App.menu(), Vector2(140, 44)))

    var body := UIKit.hbox(UIKit.SP_24)
    body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    page.add_child(body)

    var list := UIKit.vbox(UIKit.SP_8)
    var lscroll := ScrollContainer.new()
    lscroll.custom_minimum_size = Vector2(300, 0)
    lscroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    lscroll.add_child(list)
    list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body.add_child(lscroll)
    for t in teams:
        var row := UIKit.hbox(UIKit.SP_12)
        row.add_child(LogoView.new(t, 40))
        var b := UIKit.button(t.name, _show_team.bind(t), Vector2(230, 44))
        b.alignment = HORIZONTAL_ALIGNMENT_LEFT
        b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        list_buttons.append(b)
        row.add_child(b)
        list.add_child(row)

    var dscroll := ScrollContainer.new()
    dscroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    dscroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    detail = UIKit.vbox(10)
    detail.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    dscroll.add_child(detail)
    body.add_child(dscroll)
    _show_team(teams[0])


func _show_team(t: TeamDef) -> void:
    current = teams.find(t)
    for c in detail.get_children():
        c.queue_free()
    for i in list_buttons.size():
        list_buttons[i].theme_type_variation = "TabActiveButton" if teams[i] == t else ""
    var head := UIKit.hbox(18)
    head.add_child(LogoView.new(t, 110))
    var info := UIKit.vbox(4)
    info.add_child(UIKit.label(t.name, UIKit.FS_H1))
    info.add_child(UIKit.label("%s  -  %s" % [t.short, t.style.name], UIKit.FS_BODY, UIKit.ACCENT))
    var d := UIKit.label(t.style.description, UIKit.FS_BODY, UIKit.MUTED)
    d.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    d.custom_minimum_size = Vector2(480, 0)
    info.add_child(d)
    var sw := UIKit.hbox(8)
    for c in [t.color_primary, t.color_secondary]:
        var r := ColorRect.new()
        r.color = c
        r.custom_minimum_size = Vector2(36, 18)
        sw.add_child(r)
    sw.add_child(UIKit.label("kit: %s" % t.kit_pattern, UIKit.FS_CAPTION, UIKit.MUTED))
    info.add_child(sw)
    info.add_child(StarsView.new().setup(t, 20.0, 28))
    head.add_child(info)
    detail.add_child(UIKit.card(head))

    # style parameters
    var sgrid := GridContainer.new()
    sgrid.columns = 6
    sgrid.add_theme_constant_override("h_separation", 22)
    for k in ["line_height", "press", "marking", "directness", "pass_bias", "width"]:
        sgrid.add_child(UIKit.label("%s %.2f" % [k.replace("_", " "), t.style.get(k)], UIKit.FS_CAPTION, UIKit.MUTED))
    detail.add_child(sgrid)

    # squad table
    var cols := [
        {"title": "#", "w": 44, "align": "l"},
        {"title": "Player", "w": 0, "align": "l"},
        {"title": "Pos", "w": 64, "align": "l"},
        {"title": "OVR", "w": 64, "align": "r"},
        {"title": "Fin", "w": 56, "align": "r"},
        {"title": "Pas", "w": 56, "align": "r"},
        {"title": "Def", "w": 56, "align": "r"},
        {"title": "Mov", "w": 56, "align": "r"},
        {"title": "Rea", "w": 56, "align": "r"},
    ]
    var sorted: Array = t.players.duplicate()
    var order := {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    sorted.sort_custom(func(a: PlayerDef, b: PlayerDef) -> bool: return order[a.pos] < order[b.pos])
    var out: Array = []
    for p: PlayerDef in sorted:
        var cells: Array = [
            {"text": str(p.number), "color": UIKit.MUTED},
            p.name,
            {"text": p.pos, "color": UIKit.MUTED},
            {"text": str(p.overall()), "color": UIKit.rating_color(p.overall() / 10.0), "size": 20},
        ]
        for v in [p.finishing, p.passing, p.defending, p.positioning, p.reaction]:
            cells.append({"text": str(v), "color": UIKit.rating_color(v / 10.0)})
        out.append({"cells": cells})
    detail.add_child(UIKit.table(cols, out))
    var note := UIKit.label("Fin = finishing, Pas = passing, Def = defending, Mov = positioning, Rea = reaction. "
        + "Attributes only change AI decisions, never the physics.", UIKit.FS_CAPTION, UIKit.MUTED)
    note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    detail.add_child(note)


func _unhandled_input(e: InputEvent) -> void:
    if not (e is InputEventKey and e.pressed):
        return
    if e.keycode == KEY_ESCAPE and not e.echo:
        App.menu()
    elif e.keycode == KEY_RIGHT or e.keycode == KEY_DOWN:
        _show_team(teams[posmod(current + 1, teams.size())])
    elif e.keycode == KEY_LEFT or e.keycode == KEY_UP:
        _show_team(teams[posmod(current - 1, teams.size())])
