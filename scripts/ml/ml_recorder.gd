class_name MLRecorder
extends RefCounted
## Collects (observation, action) pairs from a bot during a match (imitation learning data).

var xs := PackedFloat32Array()
var ym := PackedInt32Array()
var yk := PackedInt32Array()
var n_in := 0
