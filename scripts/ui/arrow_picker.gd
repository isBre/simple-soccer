extends Control
## Arrow selector:  ‹  Current item  ›   Focus it and press Left / Right (or click the chevrons).
## Mirrors the bits of OptionButton the screens use (`selected`, `select()`, `clear()`,
## `add_item()`, `get_item_text()`), plus wrap-around stepping.
## No class_name on purpose: load it with preload("res://scripts/ui/arrow_picker.gd").

signal changed(index: int)

var items: Array = []
var selected := 0
var show_count := false

var _name: Label
var _count: Label


## Round chevron button, drawn (no font glyphs needed).
class Chevron extends Control:
    signal pressed
    var dir := 1
    var _hover := false
    var _down := false

    func _init(d: int) -> void:
        dir = d
        custom_minimum_size = Vector2(36, 40)
        mouse_filter = Control.MOUSE_FILTER_STOP
        mouse_entered.connect(func() -> void: _hover = true; queue_redraw())
        mouse_exited.connect(func() -> void: _hover = false; _down = false; queue_redraw())

    func _gui_input(e: InputEvent) -> void:
        if e is InputEventMouseButton and e.button_index == MOUSE_BUTTON_LEFT:
            _down = e.pressed
            queue_redraw()
            if e.pressed:
                pressed.emit()
            accept_event()

    func _draw() -> void:
        # bare chevron: no background, brightens on hover, nudges outward when pressed
        var c := size * 0.5
        var col := UIKit.ACCENT if _hover else UIKit.MUTED
        if _down:
            col = UIKit.ACCENT.lightened(0.3)
        var w := 6.0
        var h := 11.0
        var x := c.x - dir * w * 0.5 + (dir * 2.0 if _down else 0.0)
        draw_polyline(PackedVector2Array([Vector2(x - dir * w, c.y - h), Vector2(x + dir * w, c.y), Vector2(x - dir * w, c.y + h)]),
            col, 3.5, true)


func setup(item_list: Array, start: int, on_change: Callable, with_count: bool = false) -> Control:
    items = item_list.duplicate()
    show_count = with_count
    selected = clampi(start, 0, maxi(0, items.size() - 1))
    if on_change.is_valid():
        changed.connect(on_change)
    focus_mode = Control.FOCUS_ALL
    custom_minimum_size = Vector2(240, 52 if with_count else 46)

    var row := UIKit.hbox(UIKit.SP_4)
    row.set_anchors_preset(Control.PRESET_FULL_RECT)
    row.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(row)
    row.add_child(_chev(-1))
    var mid := UIKit.vbox(0)
    mid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    mid.alignment = BoxContainer.ALIGNMENT_CENTER
    mid.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _name = UIKit.label("", UIKit.FS_BODY, UIKit.TEXT, HORIZONTAL_ALIGNMENT_CENTER)
    _name.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _name.clip_text = true
    mid.add_child(_name)
    if with_count:
        _count = UIKit.label("", 12, UIKit.MUTED, HORIZONTAL_ALIGNMENT_CENTER)
        _count.mouse_filter = Control.MOUSE_FILTER_IGNORE
        mid.add_child(_count)
    row.add_child(mid)
    row.add_child(_chev(1))

    focus_entered.connect(queue_redraw)
    focus_exited.connect(queue_redraw)
    mouse_entered.connect(queue_redraw)
    mouse_exited.connect(queue_redraw)
    _refresh()
    return self


func _chev(dir: int) -> Control:
    var c := Chevron.new(dir)
    c.size_flags_vertical = Control.SIZE_SHRINK_CENTER
    c.pressed.connect(func() -> void: grab_focus(); step(dir))
    c.mouse_entered.connect(queue_redraw)
    c.mouse_exited.connect(queue_redraw)
    return c


func step(dir: int) -> void:
    if items.size() < 2:
        return
    selected = posmod(selected + dir, items.size())
    _refresh()
    changed.emit(selected)


# --- OptionButton-compatible bits
func select(i: int) -> void:
    selected = clampi(i, 0, maxi(0, items.size() - 1))
    _refresh()


func clear() -> void:
    items.clear()
    selected = 0
    _refresh()


func add_item(text: String) -> void:
    items.append(text)
    _refresh()


func get_item_text(i: int) -> String:
    return str(items[i]) if i >= 0 and i < items.size() else ""


func _refresh() -> void:
    if _name == null:
        return
    _name.text = get_item_text(selected)
    if _count != null:
        _count.text = "%d / %d" % [selected + 1, items.size()] if items.size() > 0 else ""


func _gui_input(e: InputEvent) -> void:
    if e.is_action_pressed("ui_left"):
        step(-1)
        accept_event()
    elif e.is_action_pressed("ui_right"):
        step(1)
        accept_event()


func _draw() -> void:
    var sb := UIKit.box(UIKit.PANEL2, 10, 8)
    if has_focus():
        sb.border_color = UIKit.ACCENT
        sb.set_border_width_all(2)
    elif get_global_rect().has_point(get_global_mouse_position()):
        sb.bg_color = UIKit.PANEL3
    draw_style_box(sb, Rect2(Vector2.ZERO, size))
