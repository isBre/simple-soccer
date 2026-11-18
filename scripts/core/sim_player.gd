class_name SimPlayer
extends Disc
## A player as the UI sees it, mirrored from the match core (soccer/match.py) by MatchClient: where he is and what to draw.

var team := 0
var slot := 0
var uid := 0                 # team * 16 + slot
var role := "MID"            # GK / DEF / MID / FWD
var def: PlayerDef
var is_human := false        # controlled from the keyboard
var input_kick := false      # kick button held (drawn as a white outline)
var kick_used := false


func _init() -> void:
    radius = 15.0
    kind = Disc.KIND_PLAYER
