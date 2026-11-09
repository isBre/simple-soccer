class_name UIKit
extends RefCounted
## Small helpers to build a consistent dark UI from code.

const BG := Color("12161d")
const PANEL := Color("1c222c")
const PANEL2 := Color("272f3d")
const PANEL3 := Color("323c4e")
const ACCENT := Color("ffd54a")
const TEXT := Color("e8ecf2")
const MUTED := Color("8d98ab")
const GOOD := Color("62d26f")
const BAD := Color("ef6a5b")
const LINE := Color("2d3646")
const PANEL_ALT := Color("20262f")    # zebra row
const HILITE := Color("3a3a30")       # highlighted row (accent tint over PANEL)

# type scale (see DESIGN.md)
const FS_DISPLAY := 60
const FS_H1 := 32
const FS_H2 := 22
const FS_BODY := 18
const FS_CAPTION := 14
const FS_COLHEAD := 13

# spacing (4-pt grid)
const SP_4 := 4
const SP_8 := 8
const SP_12 := 12
const SP_16 := 16
const SP_24 := 24
const SP_32 := 32

const ROW_H := 44
const HEAD_H := 36


static func box(col: Color, radius: int = 8, pad: int = 12) -> StyleBoxFlat:
    var sb := StyleBoxFlat.new()
    sb.bg_color = col
    sb.set_corner_radius_all(radius)
    sb.content_margin_left = pad + 2
    sb.content_margin_right = pad + 2
    sb.content_margin_top = pad - 4
    sb.content_margin_bottom = pad - 4
    return sb


static func make_theme() -> Theme:
    var t := Theme.new()
    t.default_font_size = 18
    t.set_stylebox("normal", "Button", box(PANEL2))
    t.set_stylebox("hover", "Button", box(PANEL3))
    t.set_stylebox("pressed", "Button", box(ACCENT.darkened(0.35)))
    t.set_stylebox("disabled", "Button", box(PANEL))
    t.set_stylebox("focus", "Button", _focus_ring())
    t.set_color("font_color", "Button", TEXT)
    t.set_color("font_hover_color", "Button", Color.WHITE)
    t.set_color("font_disabled_color", "Button", MUTED)
    t.set_color("font_color", "Label", TEXT)
    t.set_stylebox("panel", "PanelContainer", box(PANEL, 10, 14))
    t.set_color("font_color", "OptionButton", TEXT)
    t.set_color("font_color", "CheckBox", TEXT)
    t.set_color("font_color", "TabBar", MUTED)
    t.set_color("font_selected_color", "TabBar", ACCENT)
    t.set_color("font_hovered_color", "TabBar", Color.WHITE)
    t.set_color("font_unselected_color", "TabContainer", MUTED)
    t.set_color("font_selected_color", "TabContainer", ACCENT)
    t.set_stylebox("panel", "TabContainer", box(Color(0, 0, 0, 0), 4, 6))

    # button variants: PrimaryButton (one per screen) and GhostButton
    t.add_type("PrimaryButton")
    t.set_type_variation("PrimaryButton", "Button")
    t.set_stylebox("normal", "PrimaryButton", box(ACCENT))
    t.set_stylebox("hover", "PrimaryButton", box(ACCENT.lightened(0.18)))
    t.set_stylebox("pressed", "PrimaryButton", box(ACCENT.darkened(0.2)))
    t.set_stylebox("disabled", "PrimaryButton", box(PANEL2))
    t.set_color("font_color", "PrimaryButton", BG)
    t.set_color("font_hover_color", "PrimaryButton", BG)
    t.set_color("font_pressed_color", "PrimaryButton", BG)
    t.set_color("font_disabled_color", "PrimaryButton", MUTED)
    t.add_type("GhostButton")
    t.set_type_variation("GhostButton", "Button")
    t.set_stylebox("normal", "GhostButton", box(Color(0, 0, 0, 0)))
    t.set_stylebox("hover", "GhostButton", box(PANEL2))
    t.set_stylebox("pressed", "GhostButton", box(PANEL3))
    t.set_color("font_color", "GhostButton", MUTED)
    t.set_color("font_hover_color", "GhostButton", Color.WHITE)
    # selected tab pill
    t.add_type("TabActiveButton")
    t.set_type_variation("TabActiveButton", "Button")
    for st in ["normal", "hover", "pressed"]:
        t.set_stylebox(st, "TabActiveButton", box(PANEL3))
    for c in ["font_color", "font_hover_color", "font_pressed_color"]:
        t.set_color(c, "TabActiveButton", ACCENT)
    return t


static func _focus_ring() -> StyleBoxFlat:
    var sb := StyleBoxFlat.new()
    sb.draw_center = false
    sb.set_border_width_all(2)
    sb.border_color = ACCENT
    sb.set_corner_radius_all(8)
    return sb


static func label(text: String, size: int = 18, color: Color = TEXT,
        align: HorizontalAlignment = HORIZONTAL_ALIGNMENT_LEFT) -> Label:
    var l := Label.new()
    l.text = text
    l.add_theme_font_size_override("font_size", size)
    l.add_theme_color_override("font_color", color)
    l.horizontal_alignment = align
    return l


static func button(text: String, cb: Callable, min_size: Vector2 = Vector2(0, 44)) -> Button:
    var b := Button.new()
    b.text = text
    b.custom_minimum_size = min_size
    b.pressed.connect(cb)
    return b


static func primary_button(text: String, cb: Callable, min_size: Vector2 = Vector2(0, 52)) -> Button:
    var b := button(text, cb, min_size)
    b.theme_type_variation = "PrimaryButton"
    return b


static func ghost_button(text: String, cb: Callable, min_size: Vector2 = Vector2(0, 44)) -> Button:
    var b := button(text, cb, min_size)
    b.theme_type_variation = "GhostButton"
    return b


static func vbox(sep: int = 8) -> VBoxContainer:
    var v := VBoxContainer.new()
    v.add_theme_constant_override("separation", sep)
    return v


static func hbox(sep: int = 8) -> HBoxContainer:
    var h := HBoxContainer.new()
    h.add_theme_constant_override("separation", sep)
    return h


static func panel(child: Control = null) -> PanelContainer:
    var p := PanelContainer.new()
    if child != null:
        p.add_child(child)
    return p


static func margin(child: Control, m: int = 24) -> MarginContainer:
    var mc := MarginContainer.new()
    mc.add_theme_constant_override("margin_left", m)
    mc.add_theme_constant_override("margin_right", m)
    mc.add_theme_constant_override("margin_top", m)
    mc.add_theme_constant_override("margin_bottom", m)
    mc.add_child(child)
    return mc


static func spacer(expand: bool = true) -> Control:
    var c := Control.new()
    if expand:
        c.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        c.size_flags_vertical = Control.SIZE_EXPAND_FILL
    return c


static func option(items: Array, selected: int, on_change: Callable) -> OptionButton:
    var o := OptionButton.new()
    for it in items:
        o.add_item(str(it))
    o.select(selected)
    o.custom_minimum_size = Vector2(240, 40)
    o.item_selected.connect(on_change)
    return o


static func rating_color(r: float) -> Color:
    if r >= 7.5:
        return GOOD
    if r >= 6.5:
        return Color("b9e36a")
    if r >= 5.8:
        return ACCENT
    return BAD


static func clock_text(seconds: float) -> String:
    var s := int(seconds)
    return "%d:%02d" % [floori(s / 60.0), s % 60]


## Form field: small muted caption above a control.
static func field(caption: String, c: Control) -> Control:
    var v := vbox(SP_4)
    v.add_child(label(caption, FS_CAPTION, MUTED))
    c.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    c.custom_minimum_size.y = ROW_H
    v.add_child(c)
    return v


## Screen title (H1) with an optional muted subtitle.
static func screen_header(title: String, subtitle: String = "") -> Control:
    var v := vbox(0)
    v.add_child(label(title, FS_H1, TEXT))
    if subtitle != "":
        v.add_child(label(subtitle, FS_BODY, MUTED))
    return v


## Segmented tab bar (pills). Calls on_select(index) when a tab is clicked.
static func tab_bar(titles: Array, current: int, on_select: Callable) -> Control:
    var h := hbox(SP_8)
    for i in titles.size():
        var b := button(str(titles[i]), on_select.bind(i), Vector2(120, 40))
        b.theme_type_variation = "TabActiveButton" if i == current else "GhostButton"
        h.add_child(b)
    return h


# ------------------------------------------------------------------ card

## Card: PANEL surface, radius 12, padding 16. Optional H2 title.
static func card(child: Control = null, title: String = "") -> PanelContainer:
    var p := PanelContainer.new()
    p.add_theme_stylebox_override("panel", box(PANEL, 12, 20))
    var v := vbox(SP_12)
    p.add_child(v)
    if title != "":
        v.add_child(label(title, FS_H2, TEXT))
    if child != null:
        v.add_child(child)
    return p


# ----------------------------------------------------------------- table

static func _h_align(a: String) -> HorizontalAlignment:
    match a:
        "r":
            return HORIZONTAL_ALIGNMENT_RIGHT
        "c":
            return HORIZONTAL_ALIGNMENT_CENTER
    return HORIZONTAL_ALIGNMENT_LEFT


## Table cell with a team logo and a name.
static func team_cell(team: TeamDef, text: String, color: Color = TEXT, logo_px: float = 28.0) -> Control:
    var h := hbox(SP_12)
    var lg := LogoView.new(team, logo_px)
    lg.size_flags_vertical = Control.SIZE_SHRINK_CENTER
    h.add_child(lg)
    var l := label(text, FS_BODY, color)
    l.size_flags_vertical = Control.SIZE_EXPAND_FILL
    l.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
    l.clip_text = true
    l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    h.add_child(l)
    return h


## DataTable (see DESIGN.md). One shared look for every table.
## cols: [{"title": "Team", "w": 0, "align": "l"}, ...]   w = fixed px, 0 = expand; align l / r / c.
## rows: [{"cells": [...], "highlight": bool, "zone": Color, "color": Color}, ...]
##   a cell is a String, a Control, or {"text": String, "color": Color, "size": int}.
##   highlight = accent bar + tinted background; zone = coloured bar only (e.g. qualification).
static func table(cols: Array, rows: Array) -> Control:
    var root := vbox(0)
    root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    root.add_child(_table_row(cols, {}, true, 0, false))
    for i in rows.size():
        root.add_child(_table_row(cols, rows[i], false, i, i == rows.size() - 1))
    return root


static func _table_row(cols: Array, row: Dictionary, header: bool, index: int, last: bool) -> Control:
    var highlight: bool = row.get("highlight", false)
    var sb := StyleBoxFlat.new()
    sb.content_margin_left = 14
    sb.content_margin_right = 14
    sb.content_margin_top = 0
    sb.content_margin_bottom = 0
    sb.border_width_left = 4
    sb.border_color = Color(0, 0, 0, 0)
    if header:
        sb.bg_color = PANEL2
        sb.corner_radius_top_left = 8
        sb.corner_radius_top_right = 8
    else:
        sb.bg_color = HILITE if highlight else (PANEL if index % 2 == 0 else PANEL_ALT)
        if highlight:
            sb.border_color = ACCENT
        elif row.has("zone"):
            sb.border_color = row["zone"]
        if last:
            sb.corner_radius_bottom_left = 8
            sb.corner_radius_bottom_right = 8
    var p := PanelContainer.new()
    p.add_theme_stylebox_override("panel", sb)
    p.custom_minimum_size = Vector2(0, HEAD_H if header else ROW_H)
    var h := hbox(SP_8)
    p.add_child(h)
    var default_col: Color = row.get("color", TEXT)
    for i in cols.size():
        var col: Dictionary = cols[i]
        var align := _h_align(str(col.get("align", "l")))
        var cell: Control
        if header:
            cell = label(str(col["title"]).to_upper(), FS_COLHEAD, MUTED, align)
        else:
            var spec: Variant = row["cells"][i]
            if spec is Control:
                cell = spec
            else:
                var txt := ""
                var color := default_col
                var fsize := FS_BODY
                if spec is Dictionary:
                    txt = str(spec.get("text", ""))
                    color = spec.get("color", default_col)
                    fsize = int(spec.get("size", FS_BODY))
                else:
                    txt = str(spec)
                cell = label(txt, fsize, color, align)
        var w := int(col.get("w", 0))
        if w > 0:
            cell.custom_minimum_size.x = w
            cell.size_flags_horizontal = Control.SIZE_FILL
        else:
            cell.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        if cell is Label:
            cell.size_flags_vertical = Control.SIZE_EXPAND_FILL
            cell.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
            cell.clip_text = true
        h.add_child(cell)
    return p
