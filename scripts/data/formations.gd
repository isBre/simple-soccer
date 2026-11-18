class_name Formations
extends RefCounted
## Formation slots: [role, fx, fy] in the "attack frame": fx -1 = own goal line,
## +1 = opponent goal line (play shape stays mostly in own half); fy -1..1 across the pitch.
## The data lives in data/formations.json, shared with the match core (soccer/data.py); the UI uses it for the pickers.

static var _data: Dictionary = {}
static var _defaults: Dictionary = {}


static func _load() -> void:
    if not _data.is_empty():
        return
    var d = JSON.parse_string(FileAccess.get_file_as_string("res://data/formations.json"))
    if d is Dictionary:
        _data = d.get("formations", {})
        _defaults = d.get("defaults", {})


static func slots(name: String) -> Array:
    _load()
    return _data.get(name, [])


static func size_of(name: String) -> int:
    return slots(name).size()


static func default_for(size: int) -> String:
    _load()
    return str(_defaults.get(str(size), "1-2-1-1"))


static func options_for(size: int) -> Array:
    _load()
    var out: Array = []
    for k in _data:
        if size_of(k) == size:
            out.append(k)
    return out
