extends PanelContainer
## Compact training panel next to the live match: status, points per match, checkpoints, machine load and one chart.
## The full numbers are on the TRAINING / EVALUATION / RECAP pages (tools/training_page.gd).

const Data := preload("res://tools/training_data.gd")
const LineChart := preload("res://tools/line_chart.gd")
const WIDTH := 230.0

var data: Data
var _text: RichTextLabel
var _chart: LineChart


func start(training_data: Data) -> void:
    data = training_data
    custom_minimum_size = Vector2(WIDTH, 0)
    var sb := StyleBoxFlat.new()
    sb.bg_color = Color.BLACK
    sb.set_content_margin_all(10)
    add_theme_stylebox_override("panel", sb)
    var box := VBoxContainer.new()
    add_child(box)
    _text = RichTextLabel.new()
    _text.bbcode_enabled = true
    _text.fit_content = true
    _text.scroll_active = false
    _text.add_theme_font_size_override("normal_font_size", 12)
    _text.add_theme_font_size_override("bold_font_size", 12)
    box.add_child(_text)
    _chart = LineChart.new()
    _chart.title = "POINTS OVER TIME"
    _chart.rows = data.history
    _chart.series = [["rules", Data.GOOD], ["bench", Data.OK], ["league", Data.BLUE]]
    _chart.fixed = Vector2(0, 3)
    _chart.custom_minimum_size = Vector2(0, 70)
    box.add_child(_chart)
    refresh()


func refresh() -> void:
    var l := data.last()
    var t := "[b]%s[/b]" % data.tag
    if l.is_empty():
        _text.text = t + "\n[color=#%s]no training log yet[/color]\n\n" % Data.MUTED + _checkpoint_rows(0)
        return
    t += "   [color=#%s][b]%s[/b][/color]\n" % [data.state_colour(), data.state_text()]
    t += "update [b]%d[/b]  ·  %s\n\n" % [l.upd, Data.hms(l.elapsed)]
    t += Data.section("POINTS PER MATCH", [["[color=#%s]●[/color] rule-based" % Data.GOOD, Data.points(l.rules)],
            ["[color=#%s]●[/color] RL Team 5" % Data.OK, Data.points(l.bench)], ["[color=#%s]●[/color] snapshots" % Data.BLUE, Data.points(l.league)]])
    t += _checkpoint_rows(l.upd)
    t += Data.section("SYSTEM", data.system_rows())
    _text.text = t
    _chart.queue_redraw()


func _checkpoint_rows(upd: int) -> String:
    var rows := [["playing", "[b]%s[/b]" % (data.playing if data.playing != "" else "-")], ["newest", data.newest_name()]]
    if upd > 0:
        rows.append(["next save", "%d upd" % (Data.CKPT_EVERY - upd % Data.CKPT_EVERY)])
    var evs := data.evaluations()
    if not evs.is_empty():
        rows.append(["last eval", "%s: %s" % [evs[-1].name.trim_prefix(data.tag + "_"), Data.points(evs[-1].league.get("all", [NAN])[0])]])
    var r: Array = data.record.get(data.playing, [])
    if not r.is_empty():
        rows.append(["watched", "%dW %dD %dL" % [r[0], r[1], r[2]]])
    var s := Data.section("WEIGHTS", rows)
    if data.playing != "" and data.playing != data.newest_name():
        s += "[color=#%s]newer weights load at the next kickoff[/color]\n\n" % Data.OK
    return s
