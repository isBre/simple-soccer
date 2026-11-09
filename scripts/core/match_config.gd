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
var ml_models: Array = [null, null]    # optional MLP per team: drives all outfield players
var ml_keeper := false                 # true -> the ML net also drives the goalkeeper slot (no rule-based keeper)
var ml_temperature := 1.0               # sampling temperature of the ML bots (lower = greedier)
var dagger: Array = [null, null]       # optional {rec, net, beta, temp}: teacher labels, student (net) acts with prob 1-beta
var legacy_bot: Array = [false, false]    # benchmark: team plays with the frozen pre-rework bot
var recorders: Array = [null, null]    # optional MLRecorder per team: records the StyleBot outfield players
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
