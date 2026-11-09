class_name LogoDraw
extends RefCounted
## Procedural team logos and kit patterns. Everything is drawn with polygons
## from a small spec, so logos are original, scalable and fully data-driven.
##
## logo spec: {shape: shield|circle|hex|diamond, pattern: solid|stripes|halves|chevron|band|quarters,
##             symbol: none|star|bolt|crown|ring|cross, c1, c2, c3 (hex colors)}

static func _col(spec: Dictionary, key: String, fallback: String) -> Color:
    return Color.html(str(spec.get(key, fallback)))


static func shape_points(shape: String, c: Vector2, s: float) -> PackedVector2Array:
    var pts := PackedVector2Array()
    match shape:
        "circle":
            for i in 40:
                var a := TAU * i / 40.0
                pts.append(c + Vector2(cos(a), sin(a)) * s)
        "hex":
            for i in 6:
                var a := TAU * i / 6.0 + PI / 6.0
                pts.append(c + Vector2(cos(a), sin(a)) * s)
        "diamond":
            for v in [Vector2(0, -1), Vector2(0.8, 0), Vector2(0, 1), Vector2(-0.8, 0)]:
                pts.append(c + v * s)
        _:
            for v in [Vector2(-0.9, -0.85), Vector2(0.9, -0.85), Vector2(0.9, 0.1), Vector2(0.55, 0.62),
                    Vector2(0, 1.0), Vector2(-0.55, 0.62), Vector2(-0.9, 0.1)]:
                pts.append(c + v * s)
    return pts


static func _rect(c: Vector2, s: float, x0: float, y0: float, x1: float, y1: float) -> PackedVector2Array:
    return PackedVector2Array([c + Vector2(x0, y0) * s, c + Vector2(x1, y0) * s,
        c + Vector2(x1, y1) * s, c + Vector2(x0, y1) * s])


static func _pattern_polys(pattern: String, c: Vector2, s: float) -> Array:
    var out: Array = []
    match pattern:
        "stripes":
            out.append(_rect(c, s, -0.62, -1.2, -0.28, 1.2))
            out.append(_rect(c, s, 0.28, -1.2, 0.62, 1.2))
        "halves":
            out.append(_rect(c, s, 0.0, -1.2, 1.2, 1.2))
        "band":
            out.append(_rect(c, s, -1.2, -0.22, 1.2, 0.22))
        "quarters":
            out.append(_rect(c, s, -1.2, -1.2, 0.0, 0.0))
            out.append(_rect(c, s, 0.0, 0.0, 1.2, 1.2))
        "chevron":
            out.append(PackedVector2Array([c + Vector2(-1.2, 0.0) * s, c + Vector2(0.0, -0.55) * s,
                c + Vector2(1.2, 0.0) * s, c + Vector2(1.2, 0.4) * s, c + Vector2(0.0, -0.15) * s,
                c + Vector2(-1.2, 0.4) * s]))
    return out


static func draw_logo(ci: CanvasItem, c: Vector2, s: float, spec: Dictionary) -> void:
    var c1 := _col(spec, "c1", "e56e56")
    var c2 := _col(spec, "c2", "ffffff")
    var c3 := _col(spec, "c3", "ffffff")
    var shape_poly := shape_points(str(spec.get("shape", "shield")), c, s)
    ci.draw_colored_polygon(shape_poly, c1)
    for pp: PackedVector2Array in _pattern_polys(str(spec.get("pattern", "solid")), c, s):
        var clipped := Geometry2D.intersect_polygons(shape_poly, pp)
        for poly: PackedVector2Array in clipped:
            if poly.size() >= 3:
                ci.draw_colored_polygon(poly, c2)
    draw_symbol(ci, c + Vector2(0, -s * 0.02), s * 0.42, str(spec.get("symbol", "none")), c3)
    var outline := shape_poly.duplicate()
    outline.append(shape_poly[0])
    ci.draw_polyline(outline, Color(0, 0, 0, 0.85), maxf(1.5, s * 0.07), true)


static func draw_symbol(ci: CanvasItem, c: Vector2, s: float, symbol: String, col: Color) -> void:
    var dark := Color(0, 0, 0, 0.55)
    match symbol:
        "star":
            var pts := PackedVector2Array()
            for i in 10:
                var r := s if i % 2 == 0 else s * 0.42
                var a := -PI / 2.0 + TAU * i / 10.0
                pts.append(c + Vector2(cos(a), sin(a)) * r)
            _fill_outlined(ci, pts, col, dark)
        "bolt":
            var pts2 := PackedVector2Array([c + Vector2(0.25, -1.0) * s, c + Vector2(-0.6, 0.15) * s,
                c + Vector2(-0.05, 0.15) * s, c + Vector2(-0.3, 1.0) * s, c + Vector2(0.65, -0.2) * s,
                c + Vector2(0.1, -0.2) * s])
            _fill_outlined(ci, pts2, col, dark)
        "crown":
            var pts3 := PackedVector2Array([c + Vector2(-1.0, 0.7) * s, c + Vector2(-1.0, -0.5) * s,
                c + Vector2(-0.5, 0.1) * s, c + Vector2(0.0, -0.8) * s, c + Vector2(0.5, 0.1) * s,
                c + Vector2(1.0, -0.5) * s, c + Vector2(1.0, 0.7) * s])
            _fill_outlined(ci, pts3, col, dark)
        "ring":
            ci.draw_arc(c, s * 0.8, 0.0, TAU, 32, dark, s * 0.55, true)
            ci.draw_arc(c, s * 0.8, 0.0, TAU, 32, col, s * 0.35, true)
        "cross":
            var pts4 := PackedVector2Array([c + Vector2(-0.3, -1.0) * s, c + Vector2(0.3, -1.0) * s,
                c + Vector2(0.3, -0.3) * s, c + Vector2(1.0, -0.3) * s, c + Vector2(1.0, 0.3) * s,
                c + Vector2(0.3, 0.3) * s, c + Vector2(0.3, 1.0) * s, c + Vector2(-0.3, 1.0) * s,
                c + Vector2(-0.3, 0.3) * s, c + Vector2(-1.0, 0.3) * s, c + Vector2(-1.0, -0.3) * s,
                c + Vector2(-0.3, -0.3) * s])
            _fill_outlined(ci, pts4, col, dark)


static func _fill_outlined(ci: CanvasItem, pts: PackedVector2Array, fill: Color, line: Color) -> void:
    ci.draw_colored_polygon(pts, fill)
    var o := pts.duplicate()
    o.append(pts[0])
    ci.draw_polyline(o, line, 1.2, true)


## Vertical strip of a disc (for kit patterns)
static func _disc_strip(c: Vector2, r: float, a0: float, a1: float, vertical: bool) -> PackedVector2Array:
    var pts := PackedVector2Array()
    var n := 8
    for i in n + 1:
        var u := lerpf(a0, a1, float(i) / n)
        var w := sqrt(maxf(0.0, r * r - u * u))
        pts.append(c + (Vector2(u, -w) if vertical else Vector2(-w, u)))
    for i in range(n, -1, -1):
        var u := lerpf(a0, a1, float(i) / n)
        var w := sqrt(maxf(0.0, r * r - u * u))
        pts.append(c + (Vector2(u, w) if vertical else Vector2(w, u)))
    return pts


static func draw_kit(ci: CanvasItem, c: Vector2, r: float, primary: Color, secondary: Color, pattern: String) -> void:
    ci.draw_circle(c, r, primary, true, -1.0, true)
    match pattern:
        "stripes":
            ci.draw_colored_polygon(_disc_strip(c, r, -r * 0.55, -r * 0.2, true), secondary)
            ci.draw_colored_polygon(_disc_strip(c, r, r * 0.2, r * 0.55, true), secondary)
        "halves":
            ci.draw_colored_polygon(_disc_strip(c, r, 0.0, r, true), secondary)
        "hoops":
            ci.draw_colored_polygon(_disc_strip(c, r, -r * 0.55, -r * 0.2, false), secondary)
            ci.draw_colored_polygon(_disc_strip(c, r, r * 0.2, r * 0.55, false), secondary)
        "band":
            ci.draw_colored_polygon(_disc_strip(c, r, -r * 0.3, r * 0.3, true), secondary)


static func text_color_on(bg: Color) -> Color:
    return Color.BLACK if bg.get_luminance() > 0.55 else Color.WHITE
