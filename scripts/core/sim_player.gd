class_name SimPlayer
extends Disc
## A player disc inside a MatchSim.

var team := 0
var slot := 0
var uid := 0                 # team * 16 + slot
var role := "MID"            # GK / DEF / MID / FWD
var def: PlayerDef
var is_human := false
var controller: BotController = null
var ps: PlayerMatchStats

var home := Vector2.ZERO     # formation position in the attack frame (-1 own goal line .. +1 opp goal line)
var spawn := Vector2.ZERO    # world kickoff position

# Inputs (set by a human or by a BotController)
var input_dir := Vector2.ZERO   # length <= 1
var input_kick := false
var kick_used := false
var kick_intent := ""        # set by bots: pass / shoot / clear / long (humans leave it empty)
var in_contact := false
var rec_tick := -999

# Fixed Haxball movement constants (attributes never change these)
var accel := 0.1
var kick_accel := 0.07

# AI-only attribute effects, cached
var reaction_delay := 0      # ticks of delayed ball perception
var err_finish := 0.0        # radians (std dev) aim error when shooting
var err_pass := 0.0          # radians (std dev) aim error when passing
var pos_noise := 0.0         # px of positioning inaccuracy
var defend_q := 0.5          # 0..1 from the defending attribute: marking tightness, interceptions
var vision := 0.5            # 0..1 from passing / positioning / reaction: how much of the play he reads
var think_ticks := 10        # ticks between two decisions of the ball carrier (better players decide faster)


## Maps an attribute (0-100) to a 0..1 quality: 40 -> 0, 95 -> 1.
static func quality(attr: float) -> float:
    return clampf((attr - 40.0) / 55.0, 0.0, 1.0)


func _init() -> void:
    radius = 15.0
    inv_mass = 0.5
    damping = 0.96
    b_coef = 0.5
    kind = Disc.KIND_PLAYER
