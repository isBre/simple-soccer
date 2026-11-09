class_name PitchDef
extends RefCounted
## Pitch geometry + look. Loaded from data/pitches/*.json.

var id := "classic"
var name := "Classic"
var sizes: Array = [3]            # recommended team sizes
var half_w := 370.0               # goal line x
var half_h := 170.0               # touch line y
var goal_half := 64.0
var net_depth := 40.0
var out_x := 420.0                # players-only outer bounds
var out_y := 200.0
var center_r := 75.0
var post_r := 8.0
var box_depth := 0.0              # visual penalty area (0 = none)
var box_half := 0.0
var stripes := 0
var obstacles: Array = []         # [[x, y, r], ...] static discs
var walls: Array = []             # extra walls: {a: Vector2, b: Vector2, ball: bool, player: bool, bc: float}
var color_pitch := Color("718c5a")
var color_outer := Color("5b7347")
var color_line := Color("c7e6bd")


static func from_dict(d: Dictionary) -> PitchDef:
    var p := PitchDef.new()
    p.id = str(d.get("id", "pitch"))
    p.name = str(d.get("name", p.id))
    p.sizes = d.get("sizes", [3])
    for k in ["half_w", "half_h", "goal_half", "net_depth", "out_x", "out_y", "center_r", "post_r",
            "box_depth", "box_half"]:
        p.set(k, float(d.get(k, p.get(k))))
    p.stripes = int(d.get("stripes", 0))
    p.obstacles = d.get("obstacles", [])
    for w in d.get("walls", []):
        p.walls.append({"a": Vector2(w["a"][0], w["a"][1]), "b": Vector2(w["b"][0], w["b"][1]),
            "ball": bool(w.get("ball", true)), "player": bool(w.get("player", false)),
            "bc": float(w.get("bc", 1.0))})
    var c: Dictionary = d.get("colors", {})
    p.color_pitch = Color.html(str(c.get("pitch", "718c5a")))
    p.color_outer = Color.html(str(c.get("outer", "5b7347")))
    p.color_line = Color.html(str(c.get("line", "c7e6bd")))
    return p


func recommended_size() -> int:
    if sizes.is_empty():
        return 3
    return int(sizes[sizes.size() - 1])
