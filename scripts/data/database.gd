extends Node
## Autoload: loads pitches, styles and teams from JSON (res://data and user://).
## Drop a new .json file into data/pitches, data/styles or data/teams (or into
## user://teams) and it shows up in the game - no code changes needed.

var pitches: Dictionary = {}
var styles: Dictionary = {}
var teams: Dictionary = {}


func _ready() -> void:
    reload()


func reload() -> void:
    pitches.clear()
    styles.clear()
    teams.clear()
    for d in _load_dir("res://data/pitches"):
        var p := PitchDef.from_dict(d)
        pitches[p.id] = p
    for d in _load_dir("res://data/styles"):
        var s := StyleDef.from_dict(d)
        styles[s.id] = s
    for dir in ["res://data/teams", "user://teams"]:
        for d in _load_dir(dir):
            var t := TeamDef.from_dict(d)
            teams[t.id] = t
    for t: TeamDef in teams.values():
        t.style = styles.get(t.style_id, styles.get("balanced", StyleDef.new()))


func _load_dir(path: String) -> Array:
    var out: Array = []
    if not DirAccess.dir_exists_absolute(path):
        return out
    var files := DirAccess.get_files_at(path)
    var sorted_files := Array(files)
    sorted_files.sort()
    for f: String in sorted_files:
        if f.ends_with(".json"):
            var data = read_json(path.path_join(f))
            if data is Dictionary:
                out.append(data)
    return out


func read_json(path: String) -> Variant:
    var f := FileAccess.open(path, FileAccess.READ)
    if f == null:
        return null
    return JSON.parse_string(f.get_as_text())


func write_json(path: String, data: Variant) -> bool:
    DirAccess.make_dir_recursive_absolute(path.get_base_dir())
    var f := FileAccess.open(path, FileAccess.WRITE)
    if f == null:
        return false
    f.store_string(JSON.stringify(data, "  "))
    return true


func team_list() -> Array[TeamDef]:
    var out: Array[TeamDef] = []
    for t: TeamDef in teams.values():
        out.append(t)
    out.sort_custom(func(a: TeamDef, b: TeamDef) -> bool: return a.name < b.name)
    return out


func pitch_list() -> Array[PitchDef]:
    var out: Array[PitchDef] = []
    for p: PitchDef in pitches.values():
        out.append(p)
    out.sort_custom(func(a: PitchDef, b: PitchDef) -> bool: return a.half_w < b.half_w)
    return out


func make_config(team_a: String, team_b: String, pitch_id: String, size: int, duration: float = 180.0,
        seed_value: int = 1) -> MatchConfig:
    var c := MatchConfig.new()
    c.pitch = pitches.get(pitch_id, pitches.values()[0])
    c.teams = [teams[team_a], teams[team_b]]
    c.team_size = size
    c.duration = duration
    c.match_seed = seed_value
    c.resolve_kits()
    return c
