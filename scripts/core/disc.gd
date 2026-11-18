class_name Disc
extends RefCounted
## A circle on the pitch as the UI draws it (ball, post, obstacle, player), mirrored from the match core (soccer/match.py).

const KIND_BALL := 1
const KIND_PLAYER := 2
const KIND_STATIC := 4

var pos := Vector2.ZERO
var vel := Vector2.ZERO
var radius := 10.0
var kind := KIND_BALL
