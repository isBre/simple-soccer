extends RefCounted
## Everything the training viewer shows, parsed from files and shared by its pages (no UI here):
## the training log (logs/<tag>.out), the checkpoints (out_5v5/ckpt), the evaluations (logs/sp_eval/<tag>_u<N>.txt, written
## by rl/eval_checkpoint.py), the machine's load, and the matches watched in this window.

const CKPT_DIR := "res://out_5v5/ckpt"
const EVAL_DIR := "res://logs/sp_eval"
const FALLBACK := "res://data/models/rl_5v5_arena_v5.json"   # default weights played until the run saves its first checkpoint
const CKPT_EVERY := 25            # selfplay.py --ckpt_every of the run
const EVAL_EVERY := 100           # selfplay.py --eval_every of the run
const STALE_S := 300              # no log activity for this long = training is not running
const GOOD := "6fd08c"
const OK := "ffd54a"
const BAD := "ff6b6b"
const BLUE := "6ab0ff"
const MUTED := "8a93a3"

var tag := ""
var fallback := FALLBACK          # weights the net server plays before the first checkpoint (its --model)
var playing := ""                 # checkpoint of the match on screen
var matches := 0                  # matches watched since the viewer started
var record: Dictionary = {}       # checkpoint name -> [wins, draws, losses, goals for, goals against] of watched matches
var history: Array = []           # one Dictionary per log line: upd, rules, bench, league, rew, ent, pool, dec, sim, learn, elapsed
var _log_time := -1
var _terms_time := -1
var _terms: Array = []            # one Dictionary per update: upd + the reward terms
var _re := RegEx.create_from_string(
    "upd (\\d+) \\| pts/m vs rules (\\S+) \\| vs frozen benchmark (\\S+) \\| vs league (\\S+) \\| rew/step (\\S+) \\| ent (\\S+) \\| pool (\\d+) \\| (\\d+) dec/s sim (\\S+)s learn (\\S+)s \\| (\\d+)s")


func setup(run_tag: String, start_weights: String = FALLBACK) -> void:
    tag = run_tag
    fallback = start_weights
    refresh()


## Path of the newest checkpoint of a run (highest update number), or `fallback` before the first one exists.
static func newest_checkpoint(run_tag: String, fallback_path: String = FALLBACK) -> String:
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
    return CKPT_DIR + "/" + best_name if best_name != "" else fallback_path


func newest_name() -> String:
    return newest_checkpoint(tag, fallback).get_file().get_basename()


## Call when a match ends (team 0 = the trained net): keeps a win/draw/loss record per checkpoint.
func record_result(goals_for: int, goals_against: int) -> void:
    matches += 1
    var r: Array = record.get(playing, [0, 0, 0, 0, 0])
    r[0 if goals_for > goals_against else (2 if goals_for < goals_against else 1)] += 1
    r[3] += goals_for
    r[4] += goals_against
    record[playing] = r


# ---------------------------------------------------------------- training log

func _log_path() -> String:
    return ProjectSettings.globalize_path("res://logs/%s.out" % tag)


## Reloads the log when it changed.
func refresh() -> void:
    var path := _log_path()
    var mod := int(FileAccess.get_modified_time(path))
    if mod == _log_time or not FileAccess.file_exists(path):
        return
    _log_time = mod
    history.clear()
    for line in FileAccess.get_file_as_string(path).split("\n"):
        var m := _re.search(line)
        if m != null:
            history.append({"upd": int(m.get_string(1)), "rules": _num(m.get_string(2)), "bench": _num(m.get_string(3)),
                    "league": _num(m.get_string(4)), "rew": _num(m.get_string(5)), "ent": _num(m.get_string(6)), "pool": int(m.get_string(7)),
                    "dec": int(m.get_string(8)), "sim": _num(m.get_string(9)), "learn": _num(m.get_string(10)), "elapsed": int(m.get_string(11))})


func last() -> Dictionary:
    return history[-1] if not history.is_empty() else {}


func is_running() -> bool:
    return int(Time.get_unix_time_from_system()) - int(FileAccess.get_modified_time(_log_path())) < STALE_S


## Seconds per update over the last ~10 log lines (0 until the log has two lines).
func seconds_per_update() -> float:
    var n := history.size()
    if n < 2:
        return 0.0
    var a: Dictionary = history[maxi(n - 10, 0)]
    var b: Dictionary = history[n - 1]
    return float(b.elapsed - a.elapsed) / maxf(float(b.upd - a.upd), 1.0)


## Seconds until the run reaches `update` (0 if unknown).
func eta_to(update: int) -> int:
    var l := last()
    return int(maxi(update - int(l.get("upd", 0)), 0) * seconds_per_update()) if not l.is_empty() else 0


## Settings of the run (logs/<tag>_config.json, written by selfplay.py at start); empty if the run predates it.
func run_config() -> Dictionary:
    var path := ProjectSettings.globalize_path("res://logs/%s_config.json" % tag)
    if not FileAccess.file_exists(path):
        return {}
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
    return parsed if parsed is Dictionary else {}


## What the reward was made of, per update (logs/<tag>_terms.jsonl, written by selfplay.py): {upd, term: mean reward per agent-decision}.
func terms_history() -> Array:
    var path := ProjectSettings.globalize_path("res://logs/%s_terms.jsonl" % tag)
    var mod := int(FileAccess.get_modified_time(path))
    if mod == _terms_time or not FileAccess.file_exists(path):
        return _terms
    _terms_time = mod
    _terms.clear()
    for line in FileAccess.get_file_as_string(path).split("\n"):
        var d: Variant = JSON.parse_string(line) if line.strip_edges() != "" else null
        if d is Dictionary:
            var row := {"upd": int(d.upd)}
            for k in d.terms:
                row[k] = float(d.terms[k])
            _terms.append(row)
    return _terms


## Moving average over `window` rows of the given terms (missing terms count as 0), for charts.
func smoothed_terms(keys: Array, window: int = 5) -> Array:
    var src := terms_history()
    var out := []
    for i in src.size():
        var row := {"upd": src[i].upd}
        for k in keys:
            var sum := 0.0
            var n := 0
            for j in range(maxi(i - window + 1, 0), i + 1):
                sum += float(src[j].get(k, 0.0))
                n += 1
            row[k] = sum / n
        out.append(row)
    return out


# ---------------------------------------------------------------- evaluations

## Completed evaluations of this run, oldest first. Each Dictionary: name, update, age (s), league {key: [pts/m, GF, GA, matches]},
## teams [{id, tier, strength, held, w, d, l, pts, gf, ga}], h2h {opponent: [W, D, L, pts/m, GF, GA]}, rl / rule {metric: value}.
func evaluations() -> Array:
    var out := []
    var dir := DirAccess.open(EVAL_DIR)
    if dir == null:
        return out
    var re_sum := RegEx.create_from_string("SUMMARY (\\w+)\\s*: pts/m (\\S+)\\s+GF (\\S+) GA (\\S+)\\s+\\((\\d+) matches\\)")
    var re_h2h := RegEx.create_from_string("H2H (.+?): W (\\d+) D (\\d+) L (\\d+) \\| pts/m (\\S+) \\| GF/GA (\\S+)/(\\S+)")
    var re_team := RegEx.create_from_string("^(\\w+)\\s+(weak|average|strong|elite)\\s+([\\d.]+)\\s+(yes\\s+)?(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+([\\d.]+)\\s+([\\d.]+)/([\\d.]+)")
    for f in dir.get_files():
        if not (f.begins_with(tag + "_u") and f.ends_with(".txt")):
            continue
        var path := EVAL_DIR + "/" + f
        var ev := {"name": f.get_basename(), "update": int(f.get_basename().trim_prefix(tag + "_u")),
                "age": int(Time.get_unix_time_from_system()) - int(FileAccess.get_modified_time(path)),
                "league": {}, "teams": [], "h2h": {}, "rl": {}, "rule": {}, "heat": {},
                "greedy": {"league": {}, "teams": [], "rl": {}, "rule": {}}}
        for raw in FileAccess.get_file_as_string(path).split("\n"):
            var is_greedy := raw.begins_with("greedy ")                    # the same net playing its best move (see eval_checkpoint.py)
            var line := raw.trim_prefix("greedy ")
            var t: Dictionary = ev.greedy if is_greedy else ev
            var m := re_sum.search(line)
            if m != null:
                t.league[m.get_string(1)] = [_num(m.get_string(2)), _num(m.get_string(3)), _num(m.get_string(4)), int(m.get_string(5))]
                continue
            m = re_h2h.search(line)
            if m != null:
                ev.h2h[m.get_string(1)] = [int(m.get_string(2)), int(m.get_string(3)), int(m.get_string(4)), _num(m.get_string(5)), _num(m.get_string(6)), _num(m.get_string(7))]
                continue
            m = re_team.search(line)
            if m != null:
                t.teams.append({"id": m.get_string(1), "tier": m.get_string(2), "strength": m.get_string(3), "held": m.get_string(4) != "",
                        "w": int(m.get_string(5)), "d": int(m.get_string(6)), "l": int(m.get_string(7)), "pts": _num(m.get_string(8)),
                        "gf": _num(m.get_string(9)), "ga": _num(m.get_string(10))})
                continue
            if line.begins_with("HEAT "):
                var parts := line.split(" ")
                if parts.size() > 5:
                    var vals := PackedFloat32Array()
                    for k in range(5, parts.size()):
                        vals.append(float(parts[k]))
                    ev.heat[parts[1]] = {"role": parts[2], "w": int(parts[3]), "h": int(parts[4]), "v": vals}
                continue
            if line.begins_with("RL Team:") or line.begins_with("rule-based:"):
                _parse_behaviour(line, t.rl if line.begins_with("RL Team:") else t.rule)
        out.append(ev)
    out.sort_custom(func(a, b): return a.update < b.update)
    return out


## One flat row per evaluation for charts and tables.
func evaluation_rows(evs: Array) -> Array:
    var rows := []
    for e in evs:
        rows.append({"update": e.update, "all": e.league.get("all", [NAN])[0], "held": e.league.get("held", [NAN])[0],
                "rl4": e.h2h.get("RL Team 4", [0, 0, 0, NAN])[3], "rl5": e.h2h.get("RL Team 5", [0, 0, 0, NAN])[3],
                "dir": e.rl.get("dir", NAN), "key": e.rl.get("key", NAN), "keeper": e.rl.get("keeper", NAN)})
    return rows


static func _parse_behaviour(line: String, into: Dictionary) -> void:
    for pair in [["dir changes/s ([\\d.]+)", "dir"], ["kick presses/s ([\\d.]+)", "kick"], ["keeper dist from own goal (\\d+)", "keeper"],
            ["passes/match ([\\d.]+) \\((\\d+)% ok\\)", "passes"], ["shots/match ([\\d.]+)", "shots"], ["key passes/match ([\\d.]+)", "key"]]:
        var m := RegEx.create_from_string(pair[0]).search(line)
        if m != null:
            into[pair[1]] = float(m.get_string(1))
            if pair[1] == "passes":
                into["acc"] = float(m.get_string(2))


# ---------------------------------------------------------------- machine

## CPU load, temperature, memory and the viewer's own frame rate (what matters on a Raspberry Pi).
func system_rows() -> Array:
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


# ---------------------------------------------------------------- formatting (BBCode)

## "title" then a two-column table of [label, value] rows.
static func section(title: String, rows: Array) -> String:
    var s := "[color=#%s]%s[/color]\n[table=2]" % [MUTED, title]
    for row in rows:
        s += "[cell][color=#%s]%s   [/color][/cell][cell]%s[/cell]" % [MUTED, row[0], row[1]]
    return s + "[/table]\n\n"


## Points per match with a colour: green > 2, yellow >= 1, red below. "-" while unknown.
static func points(raw: Variant) -> String:
    var v := float(str(raw)) if str(raw).is_valid_float() else NAN
    if is_nan(v):
        return "[color=#%s]-[/color]" % MUTED
    return "[color=#%s][b]%.2f[/b][/color]" % [GOOD if v > 2.0 else (OK if v >= 1.0 else BAD), v]


static func num_text(v: float, fmt: String = "%.2f") -> String:
    return "-" if is_nan(v) else fmt % v


static func _num(raw: String) -> float:
    return float(raw) if raw.is_valid_float() else NAN


static func hms(s: int) -> String:
    return "%dh%02dm" % [s / 3600, (s % 3600) / 60]


static func ago(secs: int) -> String:
    return duration(secs) + " ago"


static func duration(secs: int) -> String:
    return "%ds" % secs if secs < 90 else ("%d min" % roundi(secs / 60.0) if secs < 5400 else "%.1f h" % (secs / 3600.0))
