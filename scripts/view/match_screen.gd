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
var _goal_team := ""
var _goal_scorer := ""
var _goal_own := false
var _goal_idx := 0
var _goal_banner_col := Color.WHITE
## Kickoff intro: the sim is held for a moment while the camera eases in.
const INTRO_TICKS := 130
const INTRO_ZOOM_FROM := 0.86
var _intro := 0              # ticks left of the intro hold (0 = playing)
var _intro_total := INTRO_TICKS
var _intro_id := -1          # kickoff_start of the kickoff we already introduced
var _zoom_mul := 1.0
## Screen-space confetti / sparks for the goal banner.
var _parts: Array = []
var effects := true          # false: no confetti or celebration rings (set_effects)
var _prng := RandomNumberGenerator.new()
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
    _zoom = CAM_ZOOM * _zoom_mul
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
    _step_particles()
    if sim.state == MatchSim.State.PLAYING and sim.kickoff_active and sim.kickoff_start != _intro_id:
        _intro_id = sim.kickoff_start
        _intro = INTRO_TICKS
        _intro_total = INTRO_TICKS
    if _intro > 0:
        _intro -= 1
        var k := 1.0 - float(_intro) / float(_intro_total)
        _zoom_mul = lerpf(INTRO_ZOOM_FROM, 1.0, 1.0 - pow(1.0 - k, 3.0))
        _zoom = CAM_ZOOM * _zoom_mul
        view.scale = Vector2(_zoom, _zoom)
        _update_camera(true)
        view.queue_redraw()
        hud.queue_redraw()
        return
    if _zoom_mul != 1.0:
        _zoom_mul = 1.0
        _fit()
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


## Turns the goal confetti and celebration rings on or off (off = cheaper drawing, e.g. on a Raspberry Pi).
func set_effects(on: bool) -> void:
    effects = on
    view.celebration = on


func _on_goal(ev: Dictionary) -> void:
    var t: TeamDef = cfg.teams[int(ev["team"])]
    _goal_idx = int(ev["team"])
    _goal_team = t.name.to_upper()
    _goal_scorer = str(ev["scorer_name"])
    _goal_own = bool(ev["own"])
    _goal_banner_col = cfg.kits[_goal_idx][0].lightened(0.15)
    _prng.randomize()
    _parts.clear()
    if not effects:
        return
    var cx := size.x * 0.5
    var cy := size.y * 0.5 + 5.0
    var palette := [Color("ffd54a"), Color.WHITE, _goal_banner_col, _goal_banner_col.lightened(0.4)]
    for i in 120:       # burst out of the banner centre
        var a := _prng.randf() * TAU
        var sp := _prng.randf_range(3.0, 16.0)
        _parts.append({"p": Vector2(cx, cy) + Vector2(_prng.randf_range(-120, 120), 0.0),
            "v": Vector2(cos(a) * sp * 1.4, sin(a) * sp * 0.8 - 3.0), "life": _prng.randi_range(70, 150),
            "age": 0, "col": palette[i % 4], "sz": _prng.randf_range(3.0, 7.0),
            "rot": _prng.randf() * TAU, "spin": _prng.randf_range(-0.4, 0.4), "grav": 0.22, "kind": 0})
    for i in 70:        # slow confetti rain from above
        _parts.append({"p": Vector2(_prng.randf_range(0.0, size.x), -_prng.randf_range(10.0, 400.0)),
            "v": Vector2(_prng.randf_range(-1.0, 1.0), _prng.randf_range(2.0, 4.5)), "life": _prng.randi_range(120, 190),
            "age": 0, "col": palette[i % 4], "sz": _prng.randf_range(4.0, 8.0),
            "rot": _prng.randf() * TAU, "spin": _prng.randf_range(-0.2, 0.2), "grav": 0.0, "kind": 0})


func _step_particles() -> void:
    var i := _parts.size() - 1
    while i >= 0:
        var q: Dictionary = _parts[i]
        q["age"] += 1
        if q["age"] >= q["life"]:
            _parts.remove_at(i)
        else:
            q["p"] += q["v"]
            q["v"] = Vector2(q["v"].x * 0.975, q["v"].y * 0.985 + q["grav"])
            q["rot"] += q["spin"]
        i -= 1
    # sparks shooting out of the banner edges while the word is on screen
    if sim != null and sim.state == MatchSim.State.GOAL:
        var age := sim.goal_pause - sim.goal_timer
        if age > 8 and age < 70 and age % 2 == 0:
            for sgn in [-1.0, 1.0]:
                _parts.append({"p": Vector2(size.x * 0.5 + sgn * _prng.randf_range(60.0, 260.0), size.y * 0.5 + 5.0),
                    "v": Vector2(sgn * _prng.randf_range(1.0, 5.0), _prng.randf_range(-7.0, -2.0)),
                    "life": _prng.randi_range(30, 55), "age": 0, "col": Color("ffd54a"),
                    "sz": _prng.randf_range(2.0, 4.0), "rot": 0.0, "spin": 0.0, "grav": 0.25, "kind": 1})


func _draw_particles() -> void:
    for q in _parts:
        var a := clampf(1.0 - float(q["age"]) / float(q["life"]), 0.0, 1.0)
        var c: Color = q["col"]
        c.a = minf(1.0, a * 2.0)
        if q["kind"] == 1:
            hud.draw_circle(q["p"], q["sz"] * a + 0.5, c)
        else:
            hud.draw_set_transform(q["p"], q["rot"], Vector2(1.0, absf(cos(q["rot"] * 0.7)) * 0.8 + 0.2))
            hud.draw_rect(Rect2(-q["sz"], -q["sz"] * 0.5, q["sz"] * 2.0, q["sz"]), c)
            hud.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


func _ease_out_back(t: float) -> float:
    var c1 := 1.9
    var c3 := c1 + 1.0
    return 1.0 + c3 * pow(t - 1.0, 3.0) + c1 * pow(t - 1.0, 2.0)


## "GOAL" in big letters that pop in one by one, an accent band, team + scorer lines underneath.
func _draw_goal_banner(font: Font, w: float) -> void:
    var age := float(sim.goal_pause - sim.goal_timer)
    var left := float(sim.goal_timer)
    var fade := clampf(left / 22.0, 0.0, 1.0)
    var cy := size.y * 0.5 + 5.0
    var col := _goal_banner_col
    # band opening from the centre line
    var open := clampf(age / 12.0, 0.0, 1.0)
    open = 1.0 - pow(1.0 - open, 3.0)
    var half_h := 92.0 * open
    hud.draw_rect(Rect2(0, cy - half_h, w, half_h * 2.0), Color(0, 0, 0, 0.62 * fade))
    var edge := col
    edge.a = fade
    hud.draw_rect(Rect2(0, cy - half_h - 3.0, w, 3.0), edge)
    hud.draw_rect(Rect2(0, cy + half_h, w, 3.0), edge)
    # light sweep across the band
    var sw := clampf((age - 4.0) / 40.0, 0.0, 1.0)
    if sw > 0.0 and sw < 1.0:
        var sx := lerpf(-200.0, w + 200.0, sw)
        var sc := Color(1, 1, 1, 0.16 * fade)
        hud.draw_colored_polygon(PackedVector2Array([Vector2(sx - 40, cy - half_h), Vector2(sx + 20, cy - half_h),
            Vector2(sx - 10, cy + half_h), Vector2(sx - 70, cy + half_h)]), sc)
    # letters
    var word := "GOAL"
    var fs := 104
    var track := 10.0
    var widths: Array = []
    var total := 0.0
    for ch in word:
        var wd := font.get_string_size(ch, HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x
        widths.append(wd)
        total += wd + track
    total -= track
    var x := w * 0.5 - total * 0.5
    var base_y := cy - 6.0
    for i in word.length():
        var la := age - 6.0 - float(i) * 4.0
        var t := clampf(la / 16.0, 0.0, 1.0)
        if t > 0.0:
            var sc := _ease_out_back(t)
            var drop := (1.0 - t) * -50.0
            var wob := sin(age * 0.12 + float(i)) * 2.0 * t
            var pivot := Vector2(x + widths[i] * 0.5, base_y - fs * 0.3 + drop + wob)
            hud.draw_set_transform(pivot, 0.0, Vector2(sc, sc))
            var o := Vector2(-widths[i] * 0.5, fs * 0.3)
            var shadow := Color(0, 0, 0, 0.55 * fade)
            hud.draw_string(font, o + Vector2(4, 5), word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, fs, shadow)
            hud.draw_string_outline(font, o, word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, fs, 10, Color(0, 0, 0, fade * t))
            var fill := Color.WHITE.lerp(col, clampf((age - 30.0) / 30.0, 0.0, 0.45))
            fill.a = fade * t
            hud.draw_string(font, o, word[i], HORIZONTAL_ALIGNMENT_LEFT, -1, fs, fill)
            hud.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
        x += widths[i] + track
    # underline that draws out
    var ul := clampf((age - 24.0) / 14.0, 0.0, 1.0)
    if ul > 0.0:
        var uw := total * ul
        edge.a = fade
        hud.draw_rect(Rect2(w * 0.5 - uw * 0.5, cy + 12.0, uw, 4.0), edge)
    # team + scorer
    var ta := clampf((age - 28.0) / 12.0, 0.0, 1.0)
    if ta > 0.0:
        var slide := (1.0 - ta) * 18.0
        var tc := col.lightened(0.25)
        tc.a = ta * fade
        hud.draw_string(font, Vector2(0, cy + 44.0 + slide), _goal_team, HORIZONTAL_ALIGNMENT_CENTER, w, 26, tc)
        if _goal_scorer != "":
            var line := _goal_scorer + ("  (own goal)" if _goal_own else "")
            var sa := clampf((age - 36.0) / 12.0, 0.0, 1.0)
            var wc := Color(1, 1, 1, sa * fade)
            hud.draw_string(font, Vector2(0, cy + 74.0 + (1.0 - sa) * 18.0), line, HORIZONTAL_ALIGNMENT_CENTER, w, 20, wc)


## "KICK OFF" tag that fades in during the intro hold.
func _draw_kickoff_intro(font: Font, w: float) -> void:
    var k := 1.0 - float(_intro) / float(_intro_total)
    var a := clampf(k / 0.2, 0.0, 1.0) * clampf((1.0 - k) / 0.2, 0.0, 1.0)
    if a <= 0.0:
        return
    var col: Color = cfg.kits[sim.kickoff_team][0].lightened(0.25)
    var cy := size.y * 0.5 - 170.0
    var spread := 18.0 * (1.0 - a)
    hud.draw_rect(Rect2(w * 0.5 - 150.0 - spread, cy - 36.0, 300.0 + spread * 2.0, 2.0), Color(col.r, col.g, col.b, a))
    hud.draw_rect(Rect2(w * 0.5 - 150.0 - spread, cy + 38.0, 300.0 + spread * 2.0, 2.0), Color(col.r, col.g, col.b, a))
    hud.draw_string_outline(font, Vector2(0, cy + 14.0), "KICK OFF", HORIZONTAL_ALIGNMENT_CENTER, w, 52, 8, Color(0, 0, 0, a))
    hud.draw_string(font, Vector2(0, cy + 14.0), "KICK OFF", HORIZONTAL_ALIGNMENT_CENTER, w, 52, Color(1, 1, 1, a))
    hud.draw_string(font, Vector2(0, cy + 62.0), cfg.teams[sim.kickoff_team].name.to_upper() + " TO KICK OFF",
        HORIZONTAL_ALIGNMENT_CENTER, w, 16, Color(col.r, col.g, col.b, a))


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
        _draw_goal_banner(font, w)
    elif sim.state == MatchSim.State.ENDED:
        if sim.winner == -1:
            msg = "FULL TIME - DRAW"
        else:
            msg = "FULL TIME - %s WIN" % cfg.teams[sim.winner].name.to_upper()
            col2 = cfg.kits[sim.winner][0]
        if not sim.shootout.is_empty():
            msg += "  (pens %d-%d)" % [sim.shootout[0], sim.shootout[1]]
    elif _intro > 0:
        _draw_kickoff_intro(font, w)
    if msg != "":
        hud.draw_rect(Rect2(0, size.y * 0.5 - 30, w, 70), Color(0, 0, 0, 0.55))
        hud.draw_string(font, Vector2(0, size.y * 0.5 + 18), msg, HORIZONTAL_ALIGNMENT_CENTER, w, 40, col2)
        if sim.state == MatchSim.State.ENDED:
            hud.draw_string(font, Vector2(0, size.y * 0.5 + 38), "Enter - match report", HORIZONTAL_ALIGNMENT_CENTER, w, 16, UIKit.MUTED)
    _draw_particles()
    if paused:
        hud.draw_rect(Rect2(0, 0, w, size.y), Color(0, 0, 0, 0.6))
        hud.draw_string(font, Vector2(0, size.y * 0.5), "PAUSED", HORIZONTAL_ALIGNMENT_CENTER, w, 56, Color.WHITE)
        hud.draw_string(font, Vector2(0, size.y * 0.5 + 34), "Esc / P resume    M quit to menu", HORIZONTAL_ALIGNMENT_CENTER, w, 20, UIKit.MUTED)
