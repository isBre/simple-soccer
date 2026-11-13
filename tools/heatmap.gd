extends Control
## Position heatmap of one player slot (or the ball) on a small pitch. Values are per mille of the time spent in each cell,
## row by row from the top; the team attacks to the right (the goal it defends is on the left).

var title := ""
var grid_w := 14
var grid_h := 8
var values := PackedFloat32Array()


func _draw() -> void:
    var font := ThemeDB.fallback_font
    draw_string(font, Vector2(0, 12), title, HORIZONTAL_ALIGNMENT_LEFT, size.x, 12, Color("8a93a3"))
    var area := Rect2(0, 18, size.x, size.y - 18)
    draw_rect(area, Color(0.08, 0.1, 0.14))
    if values.size() != grid_w * grid_h:
        return
    var peak := 1.0
    for v in values:
        peak = maxf(peak, v)
    var cw := area.size.x / grid_w
    var ch := area.size.y / grid_h
    for gy in grid_h:
        for gx in grid_w:
            var t := sqrt(values[gy * grid_w + gx] / peak)           # sqrt: small values stay visible next to the peak
            if t > 0.02:
                draw_rect(Rect2(area.position.x + gx * cw, area.position.y + gy * ch, cw + 0.5, ch + 0.5), Color(0.1, 0.18, 0.3).lerp(Color("ffd54a"), t))
    var line := Color(1, 1, 1, 0.35)
    draw_rect(area, line, false, 1.0)
    draw_line(Vector2(area.get_center().x, area.position.y), Vector2(area.get_center().x, area.end.y), line)
    draw_circle(area.get_center(), area.size.y * 0.16, Color(0, 0, 0, 0), true)
    draw_arc(area.get_center(), area.size.y * 0.16, 0.0, TAU, 24, line, 1.0)
