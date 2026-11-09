class_name StyleDef
extends RefCounted
## Team-level tactical parameters used by StyleBot / TeamBrain. All 0..1 unless noted.

const KEYS := ["line_height", "compactness", "width", "press", "marking", "directness",
    "shoot_range", "pass_bias", "risk", "keeper_sweep", "forward_stay", "support_dist", "fluidity", "attack_commit", "intercept", "counter_press", "long_shot", "switch_play"]

var id := "balanced"
var name := "Balanced"
var description := ""
var line_height := 0.5      # how far up the pitch the defensive line sits
var compactness := 0.5      # how much the team shape follows the ball
var width := 1.0            # lateral stretch multiplier (~0.7 .. 1.4)
var press := 0.5            # number/intensity of chasers when out of possession
var marking := 0.4          # man-marking vs zonal
var directness := 0.5       # 0 = short passes, 1 = long balls
var shoot_range := 0.55     # shoot within this fraction of half-pitch length from goal
var pass_bias := 0.6        # tendency to pass instead of dribbling
var risk := 0.4             # appetite for forward / risky passes
var keeper_sweep := 0.3     # how far the keeper plays off his line
var forward_stay := 0.3     # attackers stay forward when defending (counter-attack)
var support_dist := 150.0   # px in front of the carrier for supporting runs
var fluidity := 0.6         # 0 = fixed goalkeeper slot, 1 = whoever is rearmost keeps goal
var attack_commit := 0.4    # how many players (defenders too) push forward when attacking
var intercept := 0.5        # how eagerly off-ball players run onto the path of an opponent's pass / shot
var counter_press := 0.0    # after losing the ball: extra chasers for a few seconds (gegenpress)
var long_shot := 0.0        # willingness to shoot from long range when the lane is open
var switch_play := 0.0      # preference for passes to the far side of the pitch


static func from_dict(d: Dictionary) -> StyleDef:
    var s := StyleDef.new()
    s.id = str(d.get("id", "balanced"))
    s.name = str(d.get("name", s.id))
    s.description = str(d.get("description", ""))
    for k in KEYS:
        s.set(k, float(d.get(k, s.get(k))))
    return s


func to_dict() -> Dictionary:
    var d := {"id": id, "name": name, "description": description}
    for k in KEYS:
        d[k] = get(k)
    return d


func duplicate_style() -> StyleDef:
    return StyleDef.from_dict(to_dict())
