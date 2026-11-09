class_name Disc
extends RefCounted
## A circle with Haxball-style physical properties.

const KIND_BALL := 1
const KIND_PLAYER := 2
const KIND_STATIC := 4

var pos := Vector2.ZERO
var vel := Vector2.ZERO
var radius := 10.0
var inv_mass := 1.0
var damping := 0.99
var b_coef := 0.5
var kind := KIND_BALL
