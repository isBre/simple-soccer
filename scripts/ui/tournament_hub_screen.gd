class_name TournamentHubScreen
extends Control
## Tournament home: match day, tables, results, player statistics.

var t: Tournament
var body: VBoxContainer
var overlay: Control
var progress: ProgressBar
var batch: SimBatch = null
var batch_fixtures: Array = []
var control_opt: OptionButton
var control_index := 0
var tab_index := 0


func _ready() -> void:
    t = App.tournament
    var page := UIKit.vbox(UIKit.SP_16)
    var mc := UIKit.margin(page, UIKit.SP_32)
    mc.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(mc)

    var head := UIKit.hbox(UIKit.SP_16)
    var ut: TeamDef = Database.teams[t.user_team]
    head.add_child(LogoView.new(ut, 56))
    var hv := UIKit.vbox(0)
    hv.add_child(UIKit.label(t.title, UIKit.FS_H1, UIKit.TEXT))
    hv.add_child(UIKit.label("Managing %s   -   %s, %dv%d, %d min matches" % [ut.name,
        Database.pitches[t.pitch_id].name, t.team_size, t.team_size, int(t.duration / 60.0)],
        UIKit.FS_CAPTION, UIKit.MUTED))
    head.add_child(hv)
    head.add_child(UIKit.spacer())
    head.add_child(UIKit.ghost_button("Save & Menu", _save_and_menu, Vector2(150, 44)))
    page.add_child(UIKit.card(head))

    body = UIKit.vbox(UIKit.SP_16)
    body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    page.add_child(body)

    overlay = ColorRect.new()
    (overlay as ColorRect).color = Color(0, 0, 0, 0.7)
    overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
    overlay.visible = false
    var oc := CenterContainer.new()
    oc.set_anchors_preset(Control.PRESET_FULL_RECT)
    var ov := UIKit.vbox(10)
    ov.add_child(UIKit.label("Simulating matches...", UIKit.FS_H1, Color.WHITE, HORIZONTAL_ALIGNMENT_CENTER))
    progress = ProgressBar.new()
    progress.custom_minimum_size = Vector2(420, 26)
    progress.max_value = 1.0
    ov.add_child(progress)
    oc.add_child(ov)
    overlay.add_child(oc)
    add_child(overlay)

    _rebuild()
    # after the user's own match the rest of the round is simulated automatically
    if not t.finished and t.user_fixture().is_empty() and not t.user_eliminated() \
            and not t.pending_fixtures(true).is_empty():
        _simulate(t.pending_fixtures(true))


func _process(_delta: float) -> void:
    if batch == null:
        return
    progress.value = batch.progress()
    if batch.is_done():
        batch.finish()
        for i in batch_fixtures.size():
            t.record(batch_fixtures[i], batch.results[i])
        batch = null
        batch_fixtures = []
        overlay.visible = false
        t.save()
        _rebuild()


func _simulate(fixtures: Array) -> void:
    if fixtures.is_empty():
        return
    var cfgs: Array = []
    for f: Dictionary in fixtures:
        cfgs.append(t.config_for(f))
    batch_fixtures = fixtures.duplicate()
    batch = SimBatch.new()
    batch.start(cfgs)
    overlay.visible = true
    progress.value = 0.0


# -------------------------------------------------------------------- ui

func _rebuild() -> void:
    for c in body.get_children():
        c.queue_free()
    body.add_child(UIKit.tab_bar(["Match Day", "Table", "Results", "Players"], tab_index,
        func(i: int) -> void:
            tab_index = i
            _rebuild()))
    var content: Control
    match tab_index:
        1:
            content = _tables_tab()
        2:
            content = _results_tab()
        3:
            content = _players_tab()
        _:
            content = _match_day_tab()
    content.size_flags_vertical = Control.SIZE_EXPAND_FILL
    content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body.add_child(content)


func _team_label(id: String, align: HorizontalAlignment, color: Color = UIKit.TEXT) -> Label:
    var tm: TeamDef = Database.teams[id]
    var l := UIKit.label(tm.name, 20, color, align)
    l.custom_minimum_size = Vector2(240, 0)
    return l


func _score_box(f: Dictionary, col: Color) -> Control:
    var pc := PanelContainer.new()
    pc.add_theme_stylebox_override("panel", UIKit.box(UIKit.PANEL2, 8, 8))
    pc.custom_minimum_size = Vector2(110, 0)
    var v := UIKit.vbox(0)
    pc.add_child(v)
    if f["played"]:
        v.add_child(UIKit.label("%d - %d" % [int(f["hg"]), int(f["ag"])], UIKit.FS_H2, col, HORIZONTAL_ALIGNMENT_CENTER))
        if not f["pens"].is_empty():
            v.add_child(UIKit.label("pens %d-%d" % [int(f["pens"][0]), int(f["pens"][1])], UIKit.FS_COLHEAD,
                UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))
    else:
        v.add_child(UIKit.label("vs", UIKit.FS_H2, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))
    return pc


## One match: [home name] [logo] [score] [logo] [away name]; the user's match is highlighted.
func _fixture_row(f: Dictionary, detail: bool = false) -> Control:
    var mine: bool = f["home"] == t.user_team or f["away"] == t.user_team
    var col := UIKit.ACCENT if mine else UIKit.TEXT
    var row_box := PanelContainer.new()
    row_box.add_theme_stylebox_override("panel", UIKit.box(UIKit.HILITE if mine else Color(0, 0, 0, 0), 8, 8))
    var outer := UIKit.vbox(UIKit.SP_4)
    row_box.add_child(outer)
    var row := UIKit.hbox(UIKit.SP_16)
    row.alignment = BoxContainer.ALIGNMENT_CENTER
    row.add_child(_team_label(f["home"], HORIZONTAL_ALIGNMENT_RIGHT, col))
    row.add_child(LogoView.new(Database.teams[f["home"]], 36))
    row.add_child(_score_box(f, col))
    row.add_child(LogoView.new(Database.teams[f["away"]], 36))
    row.add_child(_team_label(f["away"], HORIZONTAL_ALIGNMENT_LEFT, col))
    outer.add_child(row)
    if detail and f["played"]:
        var parts: Array = []
        for g: Dictionary in f["goals"]:
            parts.append("%d' %s%s" % [int(float(g["clock"]) / 60.0) + 1, g["scorer"], " (OG)" if g["own"] else ""])
        var txt := ", ".join(parts)
        if f["mom"] != "":
            txt += ("   |   " if txt != "" else "") + "MoM: " + str(f["mom"])
        if txt != "":
            var l := UIKit.label(txt, UIKit.FS_CAPTION, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER)
            l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
            outer.add_child(l)
    return row_box


func _match_day_tab() -> Control:
    var v := UIKit.vbox(UIKit.SP_16)
    v.name = "MatchDay"
    if t.finished:
        var champ: TeamDef = Database.teams[t.champion]
        var box := UIKit.vbox(UIKit.SP_8)
        box.add_child(UIKit.label("CHAMPIONS", UIKit.FS_H2, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))
        var lg := LogoView.new(champ, 140)
        lg.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
        box.add_child(lg)
        box.add_child(UIKit.label(champ.name, 48, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER))
        var won := t.champion == t.user_team
        box.add_child(UIKit.label("You won the tournament!" if won else "Better luck next time.", UIKit.FS_BODY + 2,
            UIKit.GOOD if won else UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))
        box.add_child(UIKit.spacer(false))
        var b := UIKit.primary_button("Main menu", func() -> void: App.menu(), Vector2(260, 52))
        b.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
        box.add_child(b)
        v.add_child(UIKit.card(box))
        return v

    var rows := UIKit.vbox(UIKit.SP_4)
    for f: Dictionary in t.current_round()["fixtures"]:
        rows.add_child(_fixture_row(f))
    v.add_child(UIKit.card(rows, t.round_name()))

    var actions := UIKit.hbox(UIKit.SP_16)
    actions.alignment = BoxContainer.ALIGNMENT_CENTER
    v.add_child(actions)
    var uf := t.user_fixture()
    if not uf.is_empty():
        actions.add_child(UIKit.label("Control", UIKit.FS_CAPTION, UIKit.MUTED))
        control_opt = UIKit.option(["One player", "Whole team (Q to switch)", "Watch (AI vs AI)"], control_index,
            func(i: int) -> void: control_index = i)
        control_opt.custom_minimum_size = Vector2(260, 44)
        actions.add_child(control_opt)
        actions.add_child(UIKit.primary_button("Play my match", _play_user, Vector2(240, 52)))
        actions.add_child(UIKit.button("Simulate round", func() -> void: _simulate(t.pending_fixtures(true)), Vector2(200, 52)))
    else:
        if t.user_eliminated():
            actions.add_child(UIKit.label("You have been eliminated.", UIKit.FS_BODY + 2, UIKit.BAD))
        actions.add_child(UIKit.primary_button("Simulate round", func() -> void: _simulate(t.pending_fixtures(true)), Vector2(240, 52)))
    return v


func _table_grid(rows: Array, qualify: int = 0) -> Control:
    var cols := [
        {"title": "#", "w": 36, "align": "l"},
        {"title": "Team", "w": 0, "align": "l"},
        {"title": "P", "w": 52, "align": "r"},
        {"title": "W", "w": 52, "align": "r"},
        {"title": "D", "w": 52, "align": "r"},
        {"title": "L", "w": 52, "align": "r"},
        {"title": "GF", "w": 56, "align": "r"},
        {"title": "GA", "w": 56, "align": "r"},
        {"title": "GD", "w": 60, "align": "r"},
        {"title": "Pts", "w": 72, "align": "r"},
    ]
    var out: Array = []
    var pos := 1
    for r: Dictionary in rows:
        var tm: TeamDef = Database.teams[r["id"]]
        var mine: bool = r["id"] == t.user_team
        var col := UIKit.ACCENT if mine else UIKit.TEXT
        var gd := int(r["gd"])
        var gd_txt := ("+%d" % gd) if gd > 0 else str(gd)
        var row := {
            "cells": [
                {"text": str(pos), "color": UIKit.MUTED},
                UIKit.team_cell(tm, tm.name, col),
                str(r["p"]), str(r["w"]), str(r["d"]), str(r["l"]), str(r["gf"]), str(r["ga"]),
                {"text": gd_txt, "color": UIKit.GOOD if gd > 0 else (UIKit.BAD if gd < 0 else UIKit.MUTED)},
                {"text": str(r["pts"]), "color": col if mine else Color.WHITE, "size": 20},
            ],
            "highlight": mine,
            "color": col,
        }
        if not mine and pos <= qualify:
            row["zone"] = UIKit.GOOD
        out.append(row)
        pos += 1
    return UIKit.table(cols, out)


func _tables_tab() -> Control:
    var scroll := ScrollContainer.new()
    scroll.name = "Table"
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    var v := UIKit.vbox(14)
    v.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(v)
    match t.format:
        Tournament.Format.LEAGUE:
            v.add_child(_table_grid(t.standings()))
        Tournament.Format.GROUPS:
            for g in 2:
                v.add_child(UIKit.label("Group %s" % ["A", "B"][g], UIKit.FS_H2, UIKit.TEXT))
                v.add_child(_table_grid(t.standings(g), 2))
            v.add_child(UIKit.label("Green bar = qualifies for the knockout stage", UIKit.FS_CAPTION, UIKit.MUTED))
        _:
            v.add_child(UIKit.label("Knockout cup - see Results for the bracket.", 18, UIKit.MUTED))
    return scroll


func _results_tab() -> Control:
    var scroll := ScrollContainer.new()
    scroll.name = "Results"
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    var v := UIKit.vbox(UIKit.SP_16)
    v.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(v)
    var shown := 0
    for i in range(t.rounds.size() - 1, -1, -1):   # newest round first
        var r: Dictionary = t.rounds[i]
        var any_played := false
        for f: Dictionary in r["fixtures"]:
            if f["played"]:
                any_played = true
        if not any_played:
            continue
        var col := UIKit.vbox(UIKit.SP_8)
        for f: Dictionary in r["fixtures"]:
            if f["played"]:
                col.add_child(_fixture_row(f, true))
        v.add_child(UIKit.card(col, str(r["name"])))
        shown += 1
    if shown == 0:
        v.add_child(UIKit.label("No matches played yet", UIKit.FS_BODY, UIKit.MUTED))
    return scroll


func _players_tab() -> Control:
    var scroll := ScrollContainer.new()
    scroll.name = "Players"
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    var grid := GridContainer.new()
    grid.columns = 2
    grid.add_theme_constant_override("h_separation", UIKit.SP_24)
    grid.add_theme_constant_override("v_separation", UIKit.SP_24)
    grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(grid)
    var lists := [["Top scorers", "goals", "Goals"], ["Top assists", "assists", "Assists"],
        ["Best average grade", "rating", "Grade"], ["Most man-of-the-match awards", "motm", "MoM"]]
    for entry: Array in lists:
        var col := UIKit.vbox(UIKit.SP_8)
        col.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        col.add_child(UIKit.label(entry[0], UIKit.FS_H2, UIKit.TEXT))
        var rows := t.top_players(entry[1], 8)
        if rows.is_empty():
            col.add_child(UIKit.label("No matches played yet", UIKit.FS_CAPTION, UIKit.MUTED))
        else:
            var cols := [
                {"title": "#", "w": 36, "align": "l"},
                {"title": "Player", "w": 0, "align": "l"},
                {"title": str(entry[2]), "w": 80, "align": "r"},
            ]
            var out: Array = []
            var i := 1
            for ps: Dictionary in rows:
                var val := ""
                if entry[1] == "rating":
                    val = "%.2f" % (float(ps["rating_sum"]) / maxf(1.0, float(ps["apps"])))
                else:
                    val = str(int(ps[entry[1]]))
                var tm: TeamDef = Database.teams[ps["team"]]
                var mine: bool = ps["team"] == t.user_team
                out.append({
                    "cells": [
                        {"text": str(i), "color": UIKit.MUTED},
                        UIKit.team_cell(tm, str(ps["name"]), UIKit.ACCENT if mine else UIKit.TEXT, 24.0),
                        {"text": val, "color": UIKit.ACCENT, "size": 20},
                    ],
                    "highlight": mine,
                })
                i += 1
            col.add_child(UIKit.table(cols, out))
        grid.add_child(col)
    return scroll


# ----------------------------------------------------------- live match

func _play_user() -> void:
    var fix := t.user_fixture()
    if fix.is_empty():
        return
    var cfg := t.config_for(fix)
    match control_index:
        0: cfg.control = MatchConfig.ControlMode.SINGLE
        1: cfg.control = MatchConfig.ControlMode.TEAM
        _: cfg.control = MatchConfig.ControlMode.NONE
    cfg.human_team = 0 if fix["home"] == t.user_team else 1
    App.play_match(cfg, _on_user_done.bind(fix), _back_to_hub)


func _on_user_done(res: Dictionary, fix: Dictionary) -> void:
    t.record(fix, res)
    t.save()
    App.show_screen(ReportScreen.new().setup(res, TournamentHubScreen._back_to_hub))


## Static on purpose: the hub instance is freed while the report screen is showing.
static func _back_to_hub() -> void:
    App.show_screen(TournamentHubScreen.new())


func _save_and_menu() -> void:
    t.save()
    App.menu()
