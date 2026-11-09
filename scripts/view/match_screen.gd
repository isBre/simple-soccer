class_name MatchScreen
extends Control
## Live match: runs the sim at 60 Hz, reads human input, draws HUD.
## Emits finished(result) after the final whistle (Enter) or quit_requested.

signal finished(result: Dictionary)
signal quit_requested

var cfg: MatchConfig
var sim: MatchSim
var view: MatchView
var hud: Control
var speed := 1
var paused := false
var _end_ticks := 0
var _goal_banner := ""
var _goal_banner_col := Color.WHITE
## Fixed zoom, the same on every pitch so players always look the same size.
## The camera follows the ball; pitches smaller than the screen are simply centred.
const CAM_ZOOM := 1.15
const CAM_SMOOTH := 0.08
var _zoom := 1.0
var _cam := Vector2.ZERO  # world point shown at the centre of the playfield


func setup(config: MatchConfig) -> MatchScreen:
    cfg = config
    return self


func _ready() -> void:
    set_anchors_preset(Control.PRESET_FULL_RECT)
    var bg := ColorRect.new()
    bg.color = Color("0b0e13")
    bg.set_anchors_preset(Control.PRESET_FULL_RECT)
    add_child(bg)

    sim = MatchSim.new(cfg)
    view = MatchView.new()
    view.sim = sim
    add_child(view)

    hud = Control.new()
    hud.set_anchors_preset(Control.PRESET_FULL_RECT)
    hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(hud)
    hud.draw.connect(_draw_hud)

    resized.connect(_fit)
    _fit()


func _fit() -> void:
    _zoom = CAM_ZOOM
    view.scale = Vector2(_zoom, _zoom)
    _update_camera(true)


func _update_camera(snap: bool = false) -> void:
    if sim == null:
        return
    var pd := cfg.pitch
    var target: Vector2 = sim.ball.pos
    _cam = target if snap else _cam.lerp(target, CAM_SMOOTH)
    # playfield = window below the 72px HUD bar
    var centre := Vector2(size.x * 0.5, 72.0 + (size.y - 72.0) * 0.5)
    var half_vis := Vector2(size.x * 0.5, (size.y - 72.0) * 0.5) / _zoom
    var bound := Vector2(pd.out_x + 8.0, pd.out_y + 4.0)
    var c := _cam
    c.x = 0.0 if half_vis.x >= bound.x else clampf(c.x, -bound.x + half_vis.x, bound.x - half_vis.x)
    c.y = 0.0 if half_vis.y >= bound.y else clampf(c.y, -bound.y + half_vis.y, bound.y - half_vis.y)
    view.position = centre - c * _zoom


func _physics_process(_delta: float) -> void:
    if paused or sim == null:
        return
    if sim.controlled != null:
        sim.set_human_input(_read_dir(), _read_kick())
    var prev_goals := sim.events.size()
    for i in speed:
        sim.step()
    if sim.events.size() > prev_goals:
        _on_goal(sim.events[sim.events.size() - 1])
    if sim.state == MatchSim.State.ENDED:
        _end_ticks += 1
    _update_camera()
    view.queue_redraw()
    hud.queue_redraw()


func _read_dir() -> Vector2:
    var d := Vector2.ZERO
    if Input.is_physical_key_pressed(KEY_LEFT) or Input.is_physical_key_pressed(KEY_A):
        d.x -= 1.0
    if Input.is_physical_key_pressed(KEY_RIGHT) or Input.is_physical_key_pressed(KEY_D):
        d.x += 1.0
    if Input.is_physical_key_pressed(KEY_UP) or Input.is_physical_key_pressed(KEY_W):
        d.y -= 1.0
    if Input.is_physical_key_pressed(KEY_DOWN) or Input.is_physical_key_pressed(KEY_S):
        d.y += 1.0
    return d.normalized()


func _read_kick() -> bool:
    return Input.is_physical_key_pressed(KEY_X) or Input.is_physical_key_pressed(KEY_SPACE)


func _on_goal(ev: Dictionary) -> void:
    var t: TeamDef = cfg.teams[int(ev["team"])]
    _goal_banner = "GOAL!  %s" % t.name
    if ev["scorer_name"] != "":
        _goal_banner += "  -  %s%s" % [ev["scorer_name"], " (own goal)" if ev["own"] else ""]
    _goal_banner_col = cfg.kits[int(ev["team"])][0]


func _unhandled_input(e: InputEvent) -> void:
    if not (e is InputEventKey and e.pressed and not e.echo):
        return
    var k: int = e.keycode
    if k == KEY_ESCAPE or k == KEY_P:
        paused = not paused
    elif paused and k == KEY_M:
        quit_requested.emit()
    elif k == KEY_T:
        speed = 2 if speed == 1 else (4 if speed == 2 else (8 if speed == 4 else 1))
    elif k == KEY_Q:
        sim.switch_controlled()
    elif (k == KEY_ENTER or k == KEY_KP_ENTER) and sim.state == MatchSim.State.ENDED:
        finished.emit(sim.make_result())
    get_viewport().set_input_as_handled()


func _draw_hud() -> void:
    var font := ThemeDB.fallback_font
    var w := size.x
    var cx := w * 0.5
    hud.draw_rect(Rect2(0, 0, w, 72), Color(0, 0, 0, 0.55))

    for t in 2:
        var team: TeamDef = cfg.teams[t]
        var sgn := -1.0 if t == 0 else 1.0
        LogoDraw.draw_logo(hud, Vector2(cx + sgn * 150.0, 34), 24.0, team.logo)
        var col: Color = cfg.kits[t][0]
        var nx := cx + sgn * 190.0
        if t == 0:
            hud.draw_string(font, Vector2(nx - 320.0, 40), team.name, HORIZONTAL_ALIGNMENT_RIGHT, 320.0, 28, Color.WHITE)
            hud.draw_string(font, Vector2(nx - 320.0, 62), sim.styles[t].name, HORIZONTAL_ALIGNMENT_RIGHT, 320.0, 15, UIKit.MUTED)
        else:
            hud.draw_string(font, Vector2(nx, 40), team.name, HORIZONTAL_ALIGNMENT_LEFT, 320.0, 28, Color.WHITE)
            hud.draw_string(font, Vector2(nx, 62), sim.styles[t].name, HORIZONTAL_ALIGNMENT_LEFT, 320.0, 15, UIKit.MUTED)
        hud.draw_rect(Rect2(cx + sgn * 118.0 - 3.0 + (0.0 if t == 0 else 0.0), 8, 6, 52), col)

    hud.draw_string(font, Vector2(cx - 90, 44), "%d - %d" % [sim.scores[0], sim.scores[1]],
        HORIZONTAL_ALIGNMENT_CENTER, 180.0, 40, Color.WHITE)
    var clock := ""
    if sim.overtime:
        clock = "OVERTIME  " + UIKit.clock_text(sim.ot_left)
    else:
        clock = UIKit.clock_text(sim.time_left)
    hud.draw_string(font, Vector2(cx - 90, 66), clock, HORIZONTAL_ALIGNMENT_CENTER, 180.0, 18, UIKit.ACCENT)

    var msg := ""
    var col2 := Color.WHITE
    if sim.state == MatchSim.State.GOAL:
        msg = _goal_banner
        col2 = _goal_banner_col
    elif sim.state == MatchSim.State.ENDED:
        if sim.winner == -1:
            msg = "FULL TIME - DRAW"
        else:
            msg = "FULL TIME - %s WIN" % cfg.teams[sim.winner].name.to_upper()
            col2 = cfg.kits[sim.winner][0]
        if not sim.shootout.is_empty():
            msg += "  (pens %d-%d)" % [sim.shootout[0], sim.shootout[1]]
    elif sim.kickoff_active and sim.tick < 5:
        msg = ""
    if msg != "":
        hud.draw_rect(Rect2(0, size.y * 0.5 - 30, w, 70), Color(0, 0, 0, 0.55))
        hud.draw_string(font, Vector2(0, size.y * 0.5 + 18), msg, HORIZONTAL_ALIGNMENT_CENTER, w, 40, col2)
        if sim.state == MatchSim.State.ENDED:
            hud.draw_string(font, Vector2(0, size.y * 0.5 + 38), "Enter - match report", HORIZONTAL_ALIGNMENT_CENTER, w, 16, UIKit.MUTED)
    if paused:
        hud.draw_rect(Rect2(0, 0, w, size.y), Color(0, 0, 0, 0.6))
        hud.draw_string(font, Vector2(0, size.y * 0.5), "PAUSED", HORIZONTAL_ALIGNMENT_CENTER, w, 56, Color.WHITE)
        hud.draw_string(font, Vector2(0, size.y * 0.5 + 34), "Esc / P resume    M quit to menu", HORIZONTAL_ALIGNMENT_CENTER, w, 20, UIKit.MUTED)
