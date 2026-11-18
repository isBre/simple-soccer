class_name MatchConfig
extends RefCounted
## Everything needed to set up one match.

enum ControlMode { NONE, SINGLE, TEAM }

var pitch: PitchDef
var teams: Array[TeamDef] = [null, null]     # [0] attacks right (left side), [1] attacks left
var team_size := 3
var duration := 180.0            # seconds of play
var score_limit := 0             # 0 = no limit
var allow_draw := true           # false -> golden goal overtime, then shootout
var overtime := 60.0
var match_seed := 1
var control := ControlMode.NONE
var human_team := 0
var auto_switch := false         # TEAM control: auto switch to the player nearest to the ball
var formations: Array[String] = ["", ""]
var style_override: Array = [null, null]     # optional StyleDef per team (experiments)
## Optional neural net per team, played by the match core (soccer/); it drives the whole team, goalkeeper included:
## {"model": absolute path of a game-model JSON} or {"port": n} (a running tools/net_server.py). null = the team's own
## ml_model if it has one, else rule-based.
var nets: Array = [null, null]
var net_temperature := 1.0             # sampling temperature of the net teams (0 = always the best move)
var kits: Array = []             # resolved by resolve_kits(): [[primary, secondary], [primary, secondary]]


func get_style(team: int) -> StyleDef:
    var o = style_override[team]
    if o != null:
        return o
    if teams[team].style != null:
        return teams[team].style
    return StyleDef.new()


## Picks kit colors so the two teams never look the same.
func resolve_kits() -> void:
    var a := teams[0]
    var b := teams[1]
    var ka := [a.color_primary, a.color_secondary]
    var kb := [b.color_primary, b.color_secondary]
    if _color_dist(ka[0], kb[0]) < 0.35:
        kb = [b.color_secondary, b.color_primary]
        if _color_dist(ka[0], kb[0]) < 0.35:
            kb = [Color("e8e8e8"), b.color_primary]
    kits = [ka, kb]


static func _color_dist(c1: Color, c2: Color) -> float:
    return Vector3(c1.r - c2.r, c1.g - c2.g, c1.b - c2.b).length()
