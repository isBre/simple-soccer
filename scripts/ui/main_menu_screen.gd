class_name MainMenuScreen
extends Control


func _ready() -> void:
    var center := CenterContainer.new()
    center.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(center)
    var v := UIKit.vbox(UIKit.SP_12)
    v.custom_minimum_size = Vector2(420, 0)
    center.add_child(v)

    v.add_child(UIKit.label("SIMPLE SOCCER", UIKit.FS_DISPLAY, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER))
    v.add_child(UIKit.label("Haxball-style football vs AI", UIKit.FS_BODY + 2, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))
    var gap := UIKit.spacer(false)
    gap.custom_minimum_size = Vector2(0, UIKit.SP_24)
    v.add_child(gap)

    # one primary action: resume the tournament if there is a save, else a quick match
    var has_save := Tournament.has_save()
    var quick := func() -> void: App.show_screen(QuickMatchScreen.new())
    if has_save:
        v.add_child(UIKit.primary_button("Continue Tournament", _continue_tournament))
        v.add_child(UIKit.button("Quick Match", quick, Vector2(0, 52)))
    else:
        v.add_child(UIKit.primary_button("Quick Match", quick))
    v.add_child(UIKit.button("New Tournament", func() -> void: App.show_screen(TournamentSetupScreen.new()), Vector2(0, 52)))
    v.add_child(UIKit.button("Teams & Squads", func() -> void: App.show_screen(TeamsScreen.new()), Vector2(0, 52)))
    v.add_child(UIKit.ghost_button("Quit", func() -> void: get_tree().quit(), Vector2(0, 52)))

    var gap2 := UIKit.spacer(false)
    gap2.custom_minimum_size = Vector2(0, UIKit.SP_16)
    v.add_child(gap2)
    v.add_child(UIKit.label("Add pitches, teams and play styles by dropping JSON files in data/", UIKit.FS_CAPTION,
        UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER))


func _continue_tournament() -> void:
    var t := Tournament.load_saved()
    if t == null:
        return
    App.tournament = t
    App.show_screen(TournamentHubScreen.new())
