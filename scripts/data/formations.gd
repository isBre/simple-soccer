class_name Formations
extends RefCounted
## Formation slots: [role, fx, fy] in the "attack frame": fx -1 = own goal line,
## +1 = opponent goal line (play shape stays mostly in own half); fy -1..1 across the pitch.

const DATA := {
    "solo": [["FWD", -0.3, 0.0]],
    "duo": [["GK", -0.92, 0.0], ["FWD", -0.3, 0.0]],
    "1-1-1": [["GK", -0.92, 0.0], ["DEF", -0.58, 0.0], ["FWD", -0.22, 0.0]],
    "1-2": [["GK", -0.92, 0.0], ["MID", -0.43, -0.42], ["MID", -0.43, 0.42]],
    "1-2-1": [["GK", -0.92, 0.0], ["DEF", -0.6, -0.45], ["DEF", -0.6, 0.45], ["FWD", -0.22, 0.0]],
    "1-1-2": [["GK", -0.92, 0.0], ["DEF", -0.6, 0.0], ["FWD", -0.26, -0.45], ["FWD", -0.26, 0.45]],
    "1-3": [["GK", -0.92, 0.0], ["MID", -0.5, -0.55], ["MID", -0.4, 0.0], ["MID", -0.5, 0.55]],
    "1-2-1-1": [["GK", -0.92, 0.0], ["DEF", -0.66, -0.42], ["DEF", -0.66, 0.42], ["MID", -0.42, 0.0], ["FWD", -0.2, 0.0]],
    "1-2-2": [["GK", -0.92, 0.0], ["DEF", -0.66, -0.42], ["DEF", -0.66, 0.42], ["FWD", -0.26, -0.45], ["FWD", -0.26, 0.45]],
    "1-1-2-1": [["GK", -0.92, 0.0], ["DEF", -0.66, 0.0], ["MID", -0.42, -0.5], ["MID", -0.42, 0.5], ["FWD", -0.2, 0.0]],
    "1-3-1": [["GK", -0.92, 0.0], ["DEF", -0.6, -0.5], ["MID", -0.45, 0.0], ["DEF", -0.6, 0.5], ["FWD", -0.2, 0.0]],
}

const DEFAULTS := {1: "solo", 2: "duo", 3: "1-2", 4: "1-2-1", 5: "1-2-1-1"}


static func slots(name: String) -> Array:
    return DATA.get(name, [])


static func size_of(name: String) -> int:
    return slots(name).size()


static func default_for(size: int) -> String:
    return DEFAULTS.get(size, "1-2-1-1")


static func options_for(size: int) -> Array:
    var out: Array = []
    for k in DATA:
        if size_of(k) == size:
            out.append(k)
    return out
