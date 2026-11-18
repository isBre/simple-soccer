class_name QuickMatchScreen
extends Control
## Configure and start a one-off match.

var teams: Array[TeamDef] = []     # every team (used by "Random teams")
var side_teams: Array = [[], []]   # per side: the teams of the league picked on that side
var pitches: Array[PitchDef] = []

var pitch_opt: OptionButton
var size_opt: OptionButton
var league_opt: Array = []
var team_opt: Array = []
var form_opt: Array = []
var mode_opt: OptionButton
var dur_opt: OptionButton
var logos: Array[LogoView] = []
var style_lbl: Array[Label] = []
var rating_view: Array = []
var pitch_info: Label

const DURATIONS := [60.0, 120.0, 180.0, 300.0]
const ArrowPicker := preload("res://scripts/ui/arrow_picker.gd")
const StarsView := preload("res://scripts/ui/stars_view.gd")


func _ready() -> void:
    teams = Database.team_list()
    pitches = Database.pitch_list()

    var page := UIKit.vbox(UIKit.SP_16)
    var mc := UIKit.margin(page, UIKit.SP_32)
    mc.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(mc)
    page.add_child(UIKit.screen_header("Quick Match", "Pick a pitch, a league and a team for each side, and how you want to play."))

    var body := UIKit.hbox(UIKit.SP_24)
    body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    page.add_child(body)

    # --- left: match options
    var left := UIKit.vbox(UIKit.SP_8)
    left.custom_minimum_size = Vector2(300, 0)
    var pitch_names: Array = []
    for p in pitches:
        pitch_names.append(p.name)
    var default_pitch := 0
    for i in pitches.size():
        if pitches[i].id == "arena":
            default_pitch = i
    pitch_opt = UIKit.option(pitch_names, default_pitch, _on_pitch_changed)
    left.add_child(UIKit.field("Pitch", pitch_opt))
    pitch_info = UIKit.label("", UIKit.FS_CAPTION, UIKit.MUTED)
    left.add_child(pitch_info)
    size_opt = UIKit.option(["1v1", "2v2", "3v3", "4v4", "5v5"], 2, _on_size_changed)
    left.add_child(UIKit.field("Team size", size_opt))
    mode_opt = UIKit.option(["Play (one player)", "Play (whole team, Q to switch)", "Watch (AI vs AI)"], 0, func(_i: int) -> void: pass)
    left.add_child(UIKit.field("Control", mode_opt))
    dur_opt = UIKit.option(["1 minute", "2 minutes", "3 minutes", "5 minutes"], 2, func(_i: int) -> void: pass)
    left.add_child(UIKit.field("Duration", dur_opt))
    var lcard := UIKit.card(left, "Match")
    lcard.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    body.add_child(lcard)

    # --- right: two team cards
    var right := UIKit.hbox(UIKit.SP_16)
    right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    body.add_child(right)
    for i in 2:
        right.add_child(_team_panel(i))
        _fill_teams(i, i)       # both sides start in the first league, on different teams

    _on_pitch_changed(pitch_opt.selected)
    _refresh_team_info(0)
    _refresh_team_info(1)

    var buttons := UIKit.hbox(UIKit.SP_12)
    page.add_child(buttons)
    buttons.add_child(UIKit.ghost_button("Back", func() -> void: App.menu(), Vector2(140, 52)))
    buttons.add_child(UIKit.spacer())
    buttons.add_child(UIKit.button("Random teams  (R)", _randomize_teams, Vector2(220, 52)))
    buttons.add_child(UIKit.primary_button("Kick Off", _start, Vector2(260, 52)))
    league_opt[0].call_deferred("grab_focus")


func _team_panel(i: int) -> Control:
    var v := UIKit.vbox(UIKit.SP_12)
    var lg := LogoView.new(teams[0], 60)
    lg.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    logos.append(lg)
    v.add_child(lg)

    var lnames: Array = []
    for league: Dictionary in Database.LEAGUES:
        lnames.append(league["name"])
    var lo: Control = ArrowPicker.new().setup(lnames, 0, func(_idx: int) -> void: _on_league(i, 0))
    league_opt.append(lo)
    v.add_child(UIKit.field("League", lo))
    var opt: Control = ArrowPicker.new().setup([], 0, func(_idx: int) -> void: _refresh_team_info(i), true)
    team_opt.append(opt)
    v.add_child(UIKit.field("Team", opt))

    var sl := UIKit.label("", UIKit.FS_BODY, UIKit.ACCENT)
    style_lbl.append(sl)
    v.add_child(sl)
    var rv: Control = StarsView.new().setup(teams[0], 22.0, 30)
    rv.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    rating_view.append(rv)
    v.add_child(rv)

    var fo: Control = ArrowPicker.new().setup(["-"], 0, Callable())
    form_opt.append(fo)
    v.add_child(UIKit.field("Formation", fo))
    var c := UIKit.card(v, "Home team" if i == 0 else "Away team")
    c.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    c.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    return c


## The team picked on side i.
func _team(i: int) -> TeamDef:
    return side_teams[i][team_opt[i].selected]


## Lists the teams of the league picked on side i and selects the one at `pick`.
func _fill_teams(i: int, pick: int) -> void:
    side_teams[i] = Database.league_teams(Database.LEAGUES[league_opt[i].selected]["id"])
    team_opt[i].clear()
    for t: TeamDef in side_teams[i]:
        team_opt[i].add_item(t.name)
    team_opt[i].select(pick)


func _on_league(i: int, pick: int) -> void:
    _fill_teams(i, pick)
    _refresh_team_info(i)


## Picks two different teams at random from any league (the league pickers follow).
func _randomize_teams() -> void:
    if teams.size() < 2:
        return
    var a := randi() % teams.size()
    var b := randi() % (teams.size() - 1)
    if b >= a:
        b += 1
    for side in 2:
        var t: TeamDef = teams[[a, b][side]]
        league_opt[side].select(Database.league_index(t.league))
        _fill_teams(side, 0)
        team_opt[side].select(side_teams[side].find(t))
        _refresh_team_info(side)


func _selected_size() -> int:
    return size_opt.selected + 1


func _on_pitch_changed(_idx: int) -> void:
    var p: PitchDef = pitches[pitch_opt.selected]
    size_opt.select(clampi(p.recommended_size(), 1, 5) - 1)
    pitch_info.text = "%d x %d  -  goal %d wide" % [int(p.half_w * 2.0), int(p.half_h * 2.0), int(p.goal_half * 2.0)]
    _refresh_formations()


func _on_size_changed(_idx: int) -> void:
    _refresh_formations()


func _refresh_formations() -> void:
    for i in 2:
        var opts := Formations.options_for(_selected_size())
        form_opt[i].clear()
        for f in opts:
            form_opt[i].add_item(str(f))
        var t := _team(i)
        var want := t.formation_for(_selected_size())
        form_opt[i].select(maxi(0, opts.find(want)))


func _refresh_team_info(i: int) -> void:
    var t := _team(i)
    logos[i].set_team(t)
    style_lbl[i].text = t.style_label()
    rating_view[i].set_team(t)
    _refresh_formations()


func _start() -> void:
    var a := _team(0)
    var b := _team(1)
    var p: PitchDef = pitches[pitch_opt.selected]
    var n_size := _selected_size()
    var cfg := Database.make_config(a.id, b.id, p.id, n_size, DURATIONS[dur_opt.selected], randi())
    cfg.control = mode_opt.selected as MatchConfig.ControlMode
    if mode_opt.selected == 1:
        cfg.control = MatchConfig.ControlMode.TEAM
    elif mode_opt.selected == 0:
        cfg.control = MatchConfig.ControlMode.SINGLE
    else:
        cfg.control = MatchConfig.ControlMode.NONE
    cfg.human_team = 0
    cfg.allow_draw = true
    for i in 2:
        var fi: int = form_opt[i].selected
        if fi >= 0 and n_size == _selected_size():
            cfg.formations[i] = form_opt[i].get_item_text(fi)
    App.play_match(cfg, _on_match_done, App.menu)


func _on_match_done(res: Dictionary) -> void:
    App.show_screen(ReportScreen.new().setup(res, App.menu))


func _unhandled_input(e: InputEvent) -> void:
    if not (e is InputEventKey and e.pressed and not e.echo):
        return
    if e.keycode == KEY_ESCAPE:
        App.menu()
    elif e.keycode == KEY_R:
        _randomize_teams()
    elif e.keycode == KEY_ENTER or e.keycode == KEY_KP_ENTER:
        _start()
