class_name MatchView
extends Node2D
## Draws a MatchSim (pitch, nets, kits, ball). Pure rendering, no logic.

var sim: MatchSim


func _draw() -> void:
    if sim == null:
        return
    var pd := sim.pitch
    var hw := pd.half_w
    var hh := pd.half_h
    var font := ThemeDB.fallback_font

    draw_rect(Rect2(-2000, -1200, 4000, 2400), pd.color_outer.darkened(0.25))
    draw_rect(Rect2(-pd.out_x, -pd.out_y, pd.out_x * 2.0, pd.out_y * 2.0), pd.color_outer)
    draw_rect(Rect2(-hw, -hh, hw * 2.0, hh * 2.0), pd.color_pitch)
    if pd.stripes > 0:
        var w := hw * 2.0 / pd.stripes
        for i in pd.stripes:
            if i % 2 == 0:
                draw_rect(Rect2(-hw + i * w, -hh, w, hh * 2.0), pd.color_pitch.darkened(0.07))

    # goals / nets coloured by the team defending them
    for t in 2:
        var sx := -1.0 if t == 0 else 1.0
        var col := _goal_colour(sim.cfg.kits[t], pd.color_pitch)
        var x0 := sx * hw
        var x1 := sx * (hw + pd.net_depth)
        draw_rect(Rect2(minf(x0, x1), -pd.goal_half, pd.net_depth, pd.goal_half * 2.0), pd.color_pitch.darkened(0.2))
        var nc := Color(col, 0.55)
        var gx := 0.0
        while gx <= pd.net_depth:
            var xx := x0 + sx * gx
            draw_line(Vector2(xx, -pd.goal_half), Vector2(xx, pd.goal_half), nc, 1.0)
            gx += 10.0
        var gy := -pd.goal_half
        while gy <= pd.goal_half:
            draw_line(Vector2(x0, gy), Vector2(x1, gy), nc, 1.0)
            gy += 10.0
        var frame := PackedVector2Array([Vector2(x0, -pd.goal_half), Vector2(x1, -pd.goal_half),
            Vector2(x1, pd.goal_half), Vector2(x0, pd.goal_half)])
        # dark outline under the team colour keeps the frame readable on any pitch colour
        draw_polyline(frame, Color(0, 0, 0, 0.75), 6.5)
        draw_line(Vector2(x0, -pd.goal_half), Vector2(x0, pd.goal_half), Color(0, 0, 0, 0.75), 7.5)
        draw_polyline(frame, col, 3.0)
        draw_line(Vector2(x0, -pd.goal_half), Vector2(x0, pd.goal_half), col, 4.0)

    # lines
    var lc := pd.color_line
    draw_rect(Rect2(-hw, -hh, hw * 2.0, hh * 2.0), lc, false, 3.0)
    draw_line(Vector2(0, -hh), Vector2(0, hh), lc, 3.0)
    draw_arc(Vector2.ZERO, pd.center_r, 0.0, TAU, 72, lc, 3.0, true)
    draw_circle(Vector2.ZERO, 4.0, lc)
    if pd.box_depth > 0.0:
        for sx: float in [-1.0, 1.0]:
            var bx := sx * hw - (pd.box_depth if sx > 0.0 else 0.0)
            draw_rect(Rect2(bx, -pd.box_half, pd.box_depth, pd.box_half * 2.0), lc, false, 2.5)

    # posts / obstacles
    for s in sim.statics:
        draw_circle(s.pos, s.radius, Color("f2f2f2"), true, -1.0, true)
        draw_arc(s.pos, s.radius, 0.0, TAU, 24, Color.BLACK, 2.0, true)

    # players
    for p in sim.players:
        var kit: Array = sim.cfg.kits[p.team]
        var primary: Color = kit[0]
        var secondary: Color = kit[1]
        LogoDraw.draw_kit(self, p.pos, p.radius, primary, secondary, sim.cfg.teams[p.team].kit_pattern)
        var outline := Color.WHITE if (p.input_kick and not p.kick_used) else Color.BLACK
        draw_arc(p.pos, p.radius - 1.0, 0.0, TAU, 32, outline, 2.5, true)
        # shirt number: white with a dark outline, readable on every kit colour and pattern
        var num_pos := p.pos + Vector2(-p.radius, 5.5)
        draw_string_outline(font, num_pos, str(p.def.number), HORIZONTAL_ALIGNMENT_CENTER,
            p.radius * 2.0, 14, 5, Color(0, 0, 0, 0.9))
        draw_string(font, num_pos, str(p.def.number), HORIZONTAL_ALIGNMENT_CENTER,
            p.radius * 2.0, 14, Color.WHITE)
        if p.is_human:
            var tip := p.pos + Vector2(0, -p.radius - 6.0)
            draw_colored_polygon(PackedVector2Array([tip, tip + Vector2(-6, -9), tip + Vector2(6, -9)]),
                Color("ffd54a"))
            var nm: String = p.def.name.get_slice(" ", 1)
            var np := p.pos + Vector2(-60, -p.radius - 14.0)
            draw_string_outline(font, np, nm, HORIZONTAL_ALIGNMENT_CENTER, 120.0, 13, 4, Color(0, 0, 0, 0.8))
            draw_string(font, np, nm, HORIZONTAL_ALIGNMENT_CENTER, 120.0, 13, Color("ffd54a"))

    # ball
    if sim.state == MatchSim.State.GOAL and sim.goal_scorer != null:
        _draw_celebration()
    draw_circle(sim.ball.pos, sim.ball.radius, Color.WHITE, true, -1.0, true)
    draw_arc(sim.ball.pos, sim.ball.radius - 1.0, 0.0, TAU, 24, Color.BLACK, 2.0, true)


## Pulsing rings and a burst of confetti around the scorer.
func _draw_celebration() -> void:
    var sc := sim.goal_scorer
    var age := float(sim.goal_pause - sim.goal_timer)
    var col: Color = sim.cfg.kits[sc.team][0].lightened(0.35)
    for k in 2:
        var ph := fmod(age * 0.025 + float(k) * 0.5, 1.0)
        var c := col
        c.a = 0.7 * (1.0 - ph)
        draw_arc(sc.pos, sc.radius + 6.0 + ph * 60.0, 0.0, TAU, 40, c, 3.0, true)
    var palette := [Color("ffd54a"), Color.WHITE, col]
    for i in 24:
        var ang := float(i) * 2.399 + 0.5
        var spd := 0.9 + 0.5 * fmod(float(i) * 0.37, 1.0)
        var t := minf(age, 70.0)
        var pos := sc.pos + Vector2.from_angle(ang) * (sc.radius + t * spd) + Vector2(0.0, 0.012 * t * t)
        var cc: Color = palette[i % 3]
        cc.a = clampf(1.0 - age / 110.0, 0.0, 1.0)
        draw_circle(pos, 3.0, cc)


## Colour for a team's goal: the kit colour that stands out most from the pitch, brightened if it is still
## too close to it (e.g. a green kit on a green pitch).
static func _goal_colour(kit: Array, pitch_col: Color) -> Color:
    var best: Color = kit[0]
    var best_d := -1.0
    for c: Color in kit:
        var d := _colour_dist(c, pitch_col)
        if d > best_d + 0.08:      # prefer the primary colour unless the secondary is clearly better
            best_d = d
            best = c
    if best_d < 0.5:
        var to := Color.WHITE if pitch_col.get_luminance() < 0.6 else Color.BLACK
        best = best.lerp(to, 0.65)
    return best


static func _colour_dist(a: Color, b: Color) -> float:
    return Vector3(a.r - b.r, a.g - b.g, a.b - b.b).length()
