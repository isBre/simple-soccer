extends Control
## Small line chart over rows (Dictionaries): x = row[x_key], one line per series [key, colour]. NAN values are skipped.
## `fixed` = Vector2(min, max) for a fixed range (gridlines at 1 and 2 for points), null for an auto range printed in the corner.

var title := ""
var rows: Array = []
var x_key := "upd"
var series: Array = []
var fixed: Variant = null
var font_size := 10


func _draw() -> void:
    var w := size.x
    var h := size.y
    var font := ThemeDB.fallback_font
    draw_string(font, Vector2(0, font_size), title, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color("8a93a3"))
    var top := font_size + 6.0
    var plot := h - top - 2.0
    draw_rect(Rect2(0, top, w, plot), Color(1, 1, 1, 0.05))
    if rows.is_empty():
        return
    var lo := INF
    var hi := -INF
    for sr in series:
        for row in rows:
            if not is_nan(row[sr[0]]):
                lo = minf(lo, row[sr[0]])
                hi = maxf(hi, row[sr[0]])
    if fixed != null:
        lo = fixed.x
        hi = fixed.y
    if lo == INF:
        return
    if hi - lo < 1e-6:
        hi = lo + 1.0
    if fixed != null:
        for g in [1.0, 2.0]:
            var gy: float = top + plot * (1.0 - (g - lo) / (hi - lo))
            draw_line(Vector2(0, gy), Vector2(w, gy), Color(1, 1, 1, 0.12))
    var x0: float = rows[0][x_key]
    var span := maxf(float(rows[-1][x_key]) - x0, 1.0)
    for sr in series:
        var pts := PackedVector2Array()
        for row in rows:
            if not is_nan(row[sr[0]]):
                pts.append(Vector2((float(row[x_key]) - x0) / span * w, top + plot * (1.0 - (row[sr[0]] - lo) / (hi - lo))))
        if pts.size() >= 2:
            draw_polyline(pts, Color(sr[1]), 1.5)
        elif pts.size() == 1:
            draw_circle(pts[0], 2.5, Color(sr[1]))
    if fixed == null:
        draw_string(font, Vector2(0, font_size), "%s .. %s" % [snappedf(lo, 0.001), snappedf(hi, 0.001)], HORIZONTAL_ALIGNMENT_RIGHT, w, font_size, Color("8a93a3"))
