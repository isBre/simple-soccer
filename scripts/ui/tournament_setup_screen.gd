class_name TournamentSetupScreen
extends Control

var teams: Array[TeamDef] = []
var pitches: Array[PitchDef] = []
var team_opt: Control
var count_opt: OptionButton
var format_opt: OptionButton
var pitch_opt: OptionButton
var size_opt: OptionButton
var dur_opt: OptionButton
var logo: LogoView
var info: Label
var name_lbl: Label
var style_lbl: Label
var rating_view: Control

const DURATIONS := [60.0, 120.0, 180.0]
const ArrowPicker := preload("res://scripts/ui/arrow_picker.gd")
const StarsView := preload("res://scripts/ui/stars_view.gd")


func _ready() -> void:
    teams = Database.team_list()
    pitches = Database.pitch_list()
    var page := UIKit.vbox(UIKit.SP_16)
    var mc := UIKit.margin(page, UIKit.SP_32)
    mc.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(mc)
    page.add_child(UIKit.screen_header("New Tournament",
        "Pick your team, the format and how many teams take part (%d teams exist)." % teams.size()))

    var body := UIKit.hbox(UIKit.SP_24)
    body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    page.add_child(body)

    # --- left: settings
    var form := UIKit.vbox(UIKit.SP_12)
    form.custom_minimum_size = Vector2(420, 0)
    var names: Array = []
    for t in teams:
        names.append(t.name)
    team_opt = ArrowPicker.new().setup(names, 0, func(_i: int) -> void: _refresh(), true)
    form.add_child(UIKit.field("Your team", team_opt))
    format_opt = UIKit.option(Tournament.FORMAT_NAMES, 2, func(_i: int) -> void: pass)
    form.add_child(UIKit.field("Format", format_opt))
    var counts: Array = []
    if teams.size() > 8:
        counts.append("8 teams")
    if teams.size() >= 16:
        counts.append("16 teams")
    if counts.is_empty():
        counts.append("%d teams" % teams.size())
    count_opt = UIKit.option(counts, 0, func(_i: int) -> void: pass)
    form.add_child(UIKit.field("Teams in tournament", count_opt))
    var pnames: Array = []
    for p in pitches:
        pnames.append(p.name)
    var default_pitch := 0
    for i in pitches.size():
        if pitches[i].id == "arena":
            default_pitch = i
    pitch_opt = UIKit.option(pnames, default_pitch, _on_pitch)
    form.add_child(UIKit.field("Pitch", pitch_opt))
    size_opt = UIKit.option(["1v1", "2v2", "3v3", "4v4", "5v5"], 2, func(_i: int) -> void: pass)
    form.add_child(UIKit.field("Team size", size_opt))
    dur_opt = UIKit.option(["1 minute", "2 minutes", "3 minutes"], 2, func(_i: int) -> void: pass)
    form.add_child(UIKit.field("Match length", dur_opt))
    var fcard := UIKit.card(form, "Settings")
    fcard.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    body.add_child(fcard)

    # --- right: live preview of the chosen team
    var side := UIKit.vbox(UIKit.SP_8)
    logo = LogoView.new(teams[0], 140)
    logo.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    side.add_child(logo)
    name_lbl = UIKit.label("", UIKit.FS_H1, UIKit.TEXT, HORIZONTAL_ALIGNMENT_CENTER)
    side.add_child(name_lbl)
    style_lbl = UIKit.label("", UIKit.FS_BODY, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER)
    side.add_child(style_lbl)
    info = UIKit.label("", UIKit.FS_BODY, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER)
    info.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    side.add_child(info)
    rating_view = StarsView.new().setup(teams[0], 30.0, 40)
    rating_view.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
    side.add_child(rating_view)
    var scard := UIKit.card(side, "Your team")
    scard.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scard.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
    body.add_child(scard)

    _on_pitch(pitch_opt.selected)
    _refresh()

    var buttons := UIKit.hbox(UIKit.SP_12)
    page.add_child(buttons)
    buttons.add_child(UIKit.ghost_button("Back", func() -> void: App.menu(), Vector2(140, 52)))
    buttons.add_child(UIKit.spacer())
    buttons.add_child(UIKit.primary_button("Start Tournament", _start, Vector2(280, 52)))
    team_opt.call_deferred("grab_focus")


func _on_pitch(_i: int) -> void:
    var p: PitchDef = pitches[pitch_opt.selected]
    size_opt.select(clampi(p.recommended_size(), 1, 5) - 1)


func _refresh() -> void:
    var t: TeamDef = teams[team_opt.selected]
    logo.set_team(t)
    name_lbl.text = t.name
    style_lbl.text = t.style.name
    info.text = t.style.description
    rating_view.set_team(t)


func _start() -> void:
    var t: TeamDef = teams[team_opt.selected]
    var count := int(count_opt.get_item_text(count_opt.selected).split(" ")[0])
    var ids: Array = [t.id]
    var others: Array = []
    for x in teams:
        if x.id != t.id:
            others.append(x.id)
    var rng := RandomNumberGenerator.new()
    rng.randomize()
    for i in range(others.size() - 1, 0, -1):          # random opponents when fewer than all teams play
        var j := rng.randi() % (i + 1)
        var tmp = others[i]
        others[i] = others[j]
        others[j] = tmp
    ids.append_array(others.slice(0, count - 1))
    var p: PitchDef = pitches[pitch_opt.selected]
    var tour := Tournament.create(format_opt.selected, ids, t.id, p.id, size_opt.selected + 1,
        DURATIONS[dur_opt.selected], randi() % 100000)
    App.tournament = tour
    tour.save()
    App.show_screen(TournamentHubScreen.new())


func _unhandled_input(e: InputEvent) -> void:
    if not (e is InputEventKey and e.pressed and not e.echo):
        return
    if e.keycode == KEY_ESCAPE:
        App.menu()
    elif e.keycode == KEY_ENTER or e.keycode == KEY_KP_ENTER:
        _start()
