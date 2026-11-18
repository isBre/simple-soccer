class_name TournamentSetupScreen
extends Control

var teams: Array[TeamDef] = []     # teams of the chosen league
var pitches: Array[PitchDef] = []
var league_opt: OptionButton
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
    teams = Database.league_teams(Database.LEAGUES[0]["id"])
    pitches = Database.pitch_list()
    var page := UIKit.vbox(UIKit.SP_16)
    var mc := UIKit.margin(page, UIKit.SP_32)
    mc.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(mc)
    page.add_child(UIKit.screen_header("New Tournament",
        "Pick a league, your team, the format and how many teams take part."))

    var body := UIKit.hbox(UIKit.SP_24)
    body.size_flags_vertical = Control.SIZE_EXPAND_FILL
    page.add_child(body)

    # --- left: settings
    var form := UIKit.vbox(UIKit.SP_12)
    form.custom_minimum_size = Vector2(420, 0)
    var lnames: Array = []
    for lg: Dictionary in Database.LEAGUES:
        lnames.append("%s  (%d teams)" % [lg["name"], Database.league_teams(lg["id"]).size()])
    league_opt = UIKit.option(lnames, 0, _on_league)
    form.add_child(UIKit.field("League", league_opt))
    team_opt = ArrowPicker.new().setup([], 0, func(_i: int) -> void: _refresh(), true)
    form.add_child(UIKit.field("Your team", team_opt))
    format_opt = UIKit.option(Tournament.FORMAT_NAMES, 2, func(_i: int) -> void: pass)
    count_opt = UIKit.option(["-"], 0, func(_i: int) -> void: _sync_format())
    form.add_child(_pair(UIKit.field("Format", format_opt), UIKit.field("Teams in tournament", count_opt)))
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
    dur_opt = UIKit.option(["1 minute", "2 minutes", "3 minutes"], 2, func(_i: int) -> void: pass)
    form.add_child(_pair(UIKit.field("Team size", size_opt), UIKit.field("Match length", dur_opt)))
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
    _on_league(0)

    var buttons := UIKit.hbox(UIKit.SP_12)
    page.add_child(buttons)
    buttons.add_child(UIKit.ghost_button("Back", func() -> void: App.menu(), Vector2(140, 52)))
    buttons.add_child(UIKit.spacer())
    buttons.add_child(UIKit.primary_button("Start Tournament", _start, Vector2(280, 52)))
    team_opt.call_deferred("grab_focus")


## Two form fields side by side, equal width.
func _pair(a: Control, b: Control) -> Control:
    var h := UIKit.hbox(UIKit.SP_12)
    for c in [a, b]:
        c.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        h.add_child(c)
    return h


func _on_pitch(_i: int) -> void:
    var p: PitchDef = pitches[pitch_opt.selected]
    size_opt.select(clampi(p.recommended_size(), 1, 5) - 1)


## Fills the team and team-count pickers with the chosen league's teams.
func _on_league(i: int) -> void:
    teams = Database.league_teams(Database.LEAGUES[i]["id"])
    team_opt.clear()
    for t in teams:
        team_opt.add_item(t.name)
    count_opt.clear()
    for c in [4, 8, 16]:                    # knockout / groups need a power of two
        if c < teams.size():
            count_opt.add_item("%d teams" % c)
    count_opt.add_item("%d teams (whole league)" % teams.size())
    var default_count := count_opt.item_count - 1      # 8 teams when the league has more, else all
    for k in count_opt.item_count:
        if count_opt.get_item_text(k).begins_with("8 "):
            default_count = k
    count_opt.select(default_count)
    _sync_format()
    _refresh()


## Knockout and groups need 4, 8 or 16 teams; any other count plays a league (round robin).
func _sync_format() -> void:
    var ko_ok := _is_pow2(_count())
    for f in [Tournament.Format.KNOCKOUT, Tournament.Format.GROUPS]:
        format_opt.set_item_disabled(f, not ko_ok)
    if not ko_ok:
        format_opt.select(Tournament.Format.LEAGUE)


func _count() -> int:
    return int(count_opt.get_item_text(count_opt.selected).split(" ")[0])


static func _is_pow2(n: int) -> bool:
    return n >= 4 and (n & (n - 1)) == 0


func _refresh() -> void:
    if teams.is_empty():
        return
    var t: TeamDef = teams[team_opt.selected]
    logo.set_team(t)
    name_lbl.text = t.name
    style_lbl.text = t.style_label()
    info.text = t.style_description()
    rating_view.set_team(t)


func _start() -> void:
    if teams.size() < 2:
        return
    var t: TeamDef = teams[team_opt.selected]
    var count := _count()
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
    tour.title = "%s - %s" % [Database.league_name(t.league), tour.title]
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
