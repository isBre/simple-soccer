extends Control
## Star rating (0..5 in half steps) with the numeric rating above it.
## No class_name on purpose: load it with preload("res://scripts/ui/stars_view.gd").

var stars := 0.0
var rating := 0.0
var star_size := 22.0
var show_number := true
var number_size := 32

var _num: Label


func setup(team: TeamDef, size_px: float = 22.0, number_px: int = 32, with_number: bool = true) -> Control:
    star_size = size_px
    number_size = number_px
    show_number = with_number
    set_team(team)
    return self


func set_team(team: TeamDef) -> void:
    rating = team.strength()
    stars = team.stars()
    _update()


func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_IGNORE
    _update()


func _update() -> void:
    var h := star_size + 4.0
    var w := star_size * 5.0 + 4.0 * 4.0
    custom_minimum_size = Vector2(w, h)
    if show_number:
        if _num == null:
            _num = UIKit.label("", number_size, UIKit.ACCENT, HORIZONTAL_ALIGNMENT_CENTER)
            _num.mouse_filter = Control.MOUSE_FILTER_IGNORE
            add_child(_num)
        _num.text = "%.0f" % rating
        _num.add_theme_font_size_override("font_size", number_size)
        _num.position = Vector2(0, 0)
        _num.size = Vector2(w, number_size + 8)
        custom_minimum_size.y = h + number_size + 8.0
    queue_redraw()


func _star_poly(c: Vector2, r: float) -> PackedVector2Array:
    var pts := PackedVector2Array()
    for i in 10:
        var ang := -PI / 2.0 + i * PI / 5.0
        var rr := r if i % 2 == 0 else r * 0.42
        pts.append(c + Vector2(cos(ang), sin(ang)) * rr)
    return pts


func _draw() -> void:
    var y0 := 2.0 + ((number_size + 8.0) if show_number else 0.0)
    var r := star_size * 0.5
    for i in 5:
        var c := Vector2(r + i * (star_size + 4.0), y0 + r)
        var poly := _star_poly(c, r)
        draw_colored_polygon(poly, UIKit.PANEL3)
        var fill := clampf(stars - i, 0.0, 1.0)
        if fill >= 1.0:
            draw_colored_polygon(poly, UIKit.ACCENT)
        elif fill > 0.0:
            var clip := PackedVector2Array([
                Vector2(c.x - r - 1, c.y - r - 1), Vector2(c.x - r + 2.0 * r * fill, c.y - r - 1),
                Vector2(c.x - r + 2.0 * r * fill, c.y + r + 1), Vector2(c.x - r - 1, c.y + r + 1)])
            for part in Geometry2D.intersect_polygons(poly, clip):
                draw_colored_polygon(part, UIKit.ACCENT)
