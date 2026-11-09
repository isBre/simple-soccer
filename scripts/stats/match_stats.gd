class_name MatchStats
extends RefCounted
## Per-player statistics collected during a MatchSim.

var by_uid: Dictionary = {}
var possession_ticks: Array[int] = [0, 0]


func get_player(uid: int) -> PlayerMatchStats:
    if not by_uid.has(uid):
        by_uid[uid] = PlayerMatchStats.new()
    return by_uid[uid]
