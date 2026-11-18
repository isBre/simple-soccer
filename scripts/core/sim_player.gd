class_name SimPlayer
extends Disc
## A player disc inside a MatchSim.

var team := 0
var slot := 0
var uid := 0                 # team * 16 + slot
var role := "MID"            # GK / DEF / MID / FWD
var def: PlayerDef
var is_human := false
var bot := true              # driven by the brain server (brain/); false = a human or an external controller (RL training)
var ai_seed := 0             # seed of this player's random numbers in the brain server
var ps: PlayerMatchStats

var home := Vector2.ZERO     # formation position in the attack frame (-1 own goal line .. +1 opp goal line)
var spawn := Vector2.ZERO    # world kickoff position

# Inputs (set by a human, by the brain server or by the RL trainer)
var input_dir := Vector2.ZERO   # length <= 1
var input_kick := false
var kick_used := false
var kick_intent := ""        # set by the bots: pass / shoot / clear / long (humans leave it empty); used for the stats
var in_contact := false
var rec_tick := -999

# Fixed Haxball movement constants (attributes never change these)
var accel := 0.1
var kick_accel := 0.07

func _init() -> void:
    radius = 15.0
    inv_mass = 0.5
    damping = 0.96
    b_coef = 0.5
    kind = Disc.KIND_PLAYER
