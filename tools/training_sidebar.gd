extends PanelContainer
## Training sidebar of tools/watch_training.tscn: live numbers of the training run (parsed from logs/<tag>.out), charts
## over the run, which checkpoint is playing, how it does in the matches you watch, and the Pi's load.
## It is a normal panel next to the match area (nothing overlaps). F3 hides it and the match fills the window.

const WIDTH := 230.0
const CKPT_DIR := "res://out_5v5/ckpt"
const CKPT_EVERY := 25            # selfplay.py --ckpt_every used for the run
const STALE_S := 300              # no log activity for this long = training is not running
const FALLBACK := "res://data/models/rl_5v5_arena_v5.json"   # default weights played until the run saves its first checkpoint
const GOOD := "6fd08c"
const OK := "ffd54a"
const BAD := "ff6b6b"
const BLUE := "6ab0ff"
const MUTED := "8a93a3"

var tag := ""
var fallback := FALLBACK         # weights the net server plays before the run saves a checkpoint (its --model)
var playing := ""                 # checkpoint of the match on screen (set by the viewer at each kickoff)
var _text: RichTextLabel
var _charts: Array = []          # {ctrl, title, series: [[history column, colour]...], fixed: Vector2 or null}
var _history: Array = []          # per log line: [update, pts rules, pts benchmark, pts league (NAN while unknown), reward, entropy, elapsed s]
var _matches := 0                 # matches watched since the viewer started
var _record: Dictionary = {}      # checkpoint name -> [wins, draws, losses, goals for, goals against] of watched matches
var _log_time := -1
var _re := RegEx.create_from_string(
    "upd (\\d+) \\| pts/m vs rules (\\S+) \\| vs frozen benchmark (\\S+) \\| vs league (\\S+) \\| rew/step (\\S+) \\| ent (\\S+) \\| pool (\\d+) \\| (\\d+) dec/s sim (\\S+)s learn (\\S+)s \\| (\\d+)s")


## Path of the newest checkpoint of a run (highest update number), or the shipped model before the first one exists.
static func newest_checkpoint(run_tag: String, fallback: String = FALLBACK) -> String:
    var best := -1
    var best_name := ""
    var dir := DirAccess.open(CKPT_DIR)
    if dir != null:
        for f in dir.get_files():
            if f.begins_with(run_tag + "_u") and f.ends_with(".json"):
                var n := int(f.trim_prefix(run_tag + "_u").trim_suffix(".json"))
                if n > best:
                    best = n
                    best_name = f
    return CKPT_DIR + "/" + best_name if best_name != "" else fallback


func start(run_tag: String, start_weights: String = FALLBACK) -> void:
    tag = run_tag
    fallback = start_weights
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
    _add_chart(box, "POINTS OVER TIME", [[1, GOOD], [2, OK], [3, BLUE]], Vector2(0, 3), 62)
    _add_chart(box, "REWARD / STEP", [[4, GOOD]], null, 46)
    _add_chart(box, "ENTROPY", [[5, OK]], null, 46)
    var timer := Timer.new()
    timer.wait_time = 2.0
    timer.autostart = true
    timer.timeout.connect(_refresh)
    add_child(timer)
    _refresh()


## Call when a match ends: keeps a win/draw/loss record per checkpoint (team 0 = the trained net).
func record_result(goals_for: int, goals_against: int) -> void:
    _matches += 1
    var r: Array = _record.get(playing, [0, 0, 0, 0, 0])
    r[0 if goals_for > goals_against else (2 if goals_for < goals_against else 1)] += 1
    r[3] += goals_for
    r[4] += goals_against
    _record[playing] = r


func _unhandled_key_input(event: InputEvent) -> void:
    if event is InputEventKey and event.pressed and event.keycode == KEY_F3:
        visible = not visible


func _refresh() -> void:
    var path := ProjectSettings.globalize_path("res://logs/%s.out" % tag)
    _load_history(path)
    var m := _re.search(_last_update_line(path))
    var t := "[b]TRAINING[/b]  %s" % tag
    if m == null:
        _text.text = t + "\n[color=#%s]no training log yet (logs/%s.out)[/color]\n\n%s" % [MUTED, tag, _weights_section(0)]
        return
    var upd := int(m.get_string(1))
    var running := int(Time.get_unix_time_from_system()) - int(FileAccess.get_modified_time(path)) < STALE_S
    t += "   [color=#%s][b]%s[/b][/color]\n" % [GOOD if running else BAD, "RUNNING" if running else "STOPPED"]
    t += "update [b]%d[/b]  ·  %s  ·  %s dec/s\n\n" % [upd, _hms(int(m.get_string(11))), m.get_string(8)]
    t += _section("POINTS PER MATCH (3 = win)", [["[color=#%s]●[/color] rule-based teams" % GOOD, _points(m.get_string(2))],
            ["[color=#%s]●[/color] RL Team 5 (start)" % OK, _points(m.get_string(3))],
            ["[color=#%s]●[/color] past snapshots" % BLUE, _points(m.get_string(4))]])
    t += _section("LEARNING", [["reward / step", m.get_string(5)], ["entropy", m.get_string(6)], ["opponent pool", m.get_string(7)],
            ["sim / learn time", "%ss / %ss" % [m.get_string(9), m.get_string(10)]]])
    t += _weights_section(upd)
    t += _section("SYSTEM", _system_rows())
    _text.text = t
    for c in _charts:
        c.ctrl.queue_redraw()


func _section(title: String, rows: Array) -> String:
    var s := "[color=#%s]%s[/color]\n[table=2]" % [MUTED, title]
    for row in rows:
        s += "[cell][color=#%s]%s   [/color][/cell][cell]%s[/cell]" % [MUTED, row[0], row[1]]
    return s + "[/table]\n\n"


func _weights_section(upd: int) -> String:
    var newest := newest_checkpoint(tag, fallback).get_file().get_basename()
    var cur := playing if playing != "" else "-"
    var rows := [["playing", "[b]%s[/b]" % cur], ["newest", newest]]
    var saved := int(FileAccess.get_modified_time(newest_checkpoint(tag, fallback)))
    if saved > 0:
        rows.append(["saved", _ago(int(Time.get_unix_time_from_system()) - saved)])
    if upd > 0:
        var left := CKPT_EVERY - upd % CKPT_EVERY
        var per := _seconds_per_update()
        rows.append(["next save", "%d upd%s" % [left, " (~%s)" % _ago_short(int(left * per)) if per > 0.0 else ""]])
    rows.append(["matches seen", str(_matches)])
    var r: Array = _record.get(playing, [])
    if not r.is_empty():
        rows.append(["these weights", "%dW %dD %dL  (%d-%d)" % r])
    var s := _section("WEIGHTS", rows)
    if playing != "" and cur != newest:
        s += "[color=#%s]newer weights load at the next kickoff[/color]\n" % OK
    return s


## Seconds per update over the last ~10 log lines (0 until the log has two lines).
func _seconds_per_update() -> float:
    var n := _history.size()
    if n < 2:
        return 0.0
    var a: Array = _history[maxi(n - 10, 0)]
    var b: Array = _history[n - 1]
    return float(b[6] - a[6]) / maxf(float(b[0] - a[0]), 1.0)


## CPU load, temperature, memory and the viewer's own frame rate (what matters on a Raspberry Pi).
func _system_rows() -> Array:
    var rows := []
    var load := _read_lines("/proc/loadavg")
    if not load.is_empty():
        rows.append(["cpu load", "%s / %d cores" % [load[0].split(" ")[0], OS.get_processor_count()]])
    var temp := _read_lines("/sys/class/thermal/thermal_zone0/temp")
    if not temp.is_empty() and temp[0].is_valid_float():
        var c := float(temp[0]) / 1000.0
        rows.append(["temperature", "[color=#%s]%.1f °C[/color]" % [BAD if c >= 80.0 else (OK if c >= 70.0 else GOOD), c]])
    var mem := {}
    for line in _read_lines("/proc/meminfo"):
        var kv := line.split(":")
        if kv.size() == 2:
            mem[kv[0]] = int(kv[1].strip_edges().split(" ")[0])
    if mem.has("MemTotal") and mem.has("MemAvailable"):
        rows.append(["memory", "%.1f / %.1f GB" % [(mem["MemTotal"] - mem["MemAvailable"]) / 1048576.0, mem["MemTotal"] / 1048576.0]])
    var fps := Engine.get_frames_per_second()
    var target := float(Engine.max_fps) if Engine.max_fps > 0 else 60.0          # colour against the frame cap
    rows.append(["viewer fps", "[color=#%s]%d[/color]" % [GOOD if fps >= 0.9 * target else (OK if fps >= 0.6 * target else BAD), fps]])
    return rows


## Lines of a /proc or /sys file (Godot reports their length as 0, so get_file_as_string would return nothing).
static func _read_lines(path: String) -> PackedStringArray:
    var lines := PackedStringArray()
    var f := FileAccess.open(path, FileAccess.READ)
    if f == null:
        return lines
    while not f.eof_reached():
        lines.append(f.get_line())
    return lines


static func _ago(secs: int) -> String:
    return _ago_short(secs) + " ago"


static func _ago_short(secs: int) -> String:
    return "%ds" % secs if secs < 90 else ("%d min" % roundi(secs / 60.0) if secs < 5400 else "%.1f h" % (secs / 3600.0))


## Points per match with a colour: green > 2, yellow >= 1, red below. "-" while no match has finished.
func _points(raw: String) -> String:
    if not raw.is_valid_float():
        return "[color=#%s]-[/color]" % MUTED
    var v := float(raw)
    return "[color=#%s][b]%.2f[/b][/color]" % [GOOD if v > 2.0 else (OK if v >= 1.0 else BAD), v]


func _add_chart(parent: Control, title: String, series: Array, fixed, height: float) -> void:
    var c := Control.new()
    c.custom_minimum_size = Vector2(0, height)
    var idx := _charts.size()
    c.draw.connect(func(): _draw_chart(idx))
    parent.add_child(c)
    _charts.append({"ctrl": c, "title": title, "series": series, "fixed": fixed})


## One line chart over the whole run. fixed = Vector2(min, max) or null for auto range (with gridlines at 1 and 2 for points).
func _draw_chart(idx: int) -> void:
    var cfg: Dictionary = _charts[idx]
    var c: Control = cfg.ctrl
    var w := c.size.x
    var h := c.size.y
    c.draw_string(ThemeDB.fallback_font, Vector2(0, 10), cfg.title, HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(MUTED))
    var top := 16.0
    var plot := h - top - 2.0
    c.draw_rect(Rect2(0, top, w, plot), Color(1, 1, 1, 0.05))
    if _history.size() < 2:
        return
    var lo := INF
    var hi := -INF
    for sr in cfg.series:
        for row in _history:
            if not is_nan(row[sr[0]]):
                lo = minf(lo, row[sr[0]])
                hi = maxf(hi, row[sr[0]])
    if cfg.fixed != null:
        lo = cfg.fixed.x
        hi = cfg.fixed.y
    if lo == INF:
        return
    if hi - lo < 1e-6:
        hi = lo + 1.0
    if cfg.fixed != null:
        for g in [1.0, 2.0]:
            var gy: float = top + plot * (1.0 - (g - lo) / (hi - lo))
            c.draw_line(Vector2(0, gy), Vector2(w, gy), Color(1, 1, 1, 0.12))
    var u0: float = _history[0][0]
    var span := maxf(float(_history[-1][0]) - u0, 1.0)
    for sr in cfg.series:
        var pts := PackedVector2Array()
        for row in _history:
            if not is_nan(row[sr[0]]):
                pts.append(Vector2((float(row[0]) - u0) / span * w, top + plot * (1.0 - (row[sr[0]] - lo) / (hi - lo))))
        if pts.size() >= 2:
            c.draw_polyline(pts, Color(sr[1]), 1.5)
    if cfg.fixed == null:                                    # auto range: print the range so the line means something
        c.draw_string(ThemeDB.fallback_font, Vector2(0, 10), "%s .. %s" % [snappedf(lo, 0.001), snappedf(hi, 0.001)], HORIZONTAL_ALIGNMENT_RIGHT, w, 10, Color(MUTED))


func _load_history(path: String) -> void:
    var mod := int(FileAccess.get_modified_time(path))
    if mod == _log_time or not FileAccess.file_exists(path):
        return
    _log_time = mod
    _history.clear()
    for line in FileAccess.get_file_as_string(path).split("\n"):
        var m := _re.search(line)
        if m != null:
            _history.append([int(m.get_string(1)), _num(m.get_string(2)), _num(m.get_string(3)), _num(m.get_string(4)),
                    _num(m.get_string(5)), _num(m.get_string(6)), int(m.get_string(11))])


static func _num(raw: String) -> float:
    return float(raw) if raw.is_valid_float() else NAN


func _last_update_line(path: String) -> String:
    if not FileAccess.file_exists(path):
        return ""
    var f := FileAccess.open(path, FileAccess.READ)
    f.seek(maxi(f.get_length() - 4000, 0))          # the tail is enough
    var found := ""
    for line in f.get_as_text().split("\n"):
        if " upd " in line:
            found = line
    return found


static func _hms(s: int) -> String:
    return "%dh%02dm" % [s / 3600, (s % 3600) / 60]
