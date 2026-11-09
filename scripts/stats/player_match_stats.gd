class_name PlayerMatchStats
extends RefCounted
## Raw per-player match counters. Grades are derived from these in Rating.

var touches := 0
var passes_ok := 0
var passes_failed := 0
var passes_received := 0
var progressive_passes := 0   # completed passes that gained a lot of ground towards the opponent goal
var key_passes := 0           # passes that led to a shot by the receiver
var pass_value := 0.0         # sum of per-pass impact (progress, pressure, where it was lost)
var shots := 0
var shots_on_target := 0
var goals := 0
var assists := 0
var own_goals := 0
var xg := 0.0                 # expected goals of the shots taken (chance quality)
var xa := 0.0                 # expected goals of the shots created by this player's passes
var big_chances := 0          # shots with xg >= 0.3
var big_scored := 0
var tackles := 0              # took the ball off an opponent who was dribbling
var interceptions := 0        # cut out an opponent's pass / shot-less kick
var recoveries := 0           # won a loose ball
var clearances := 0
var blocks := 0
var saves := 0
var save_xg := 0.0            # sum of xg of the shots saved (harder saves are worth more)
var conceded_xg := 0.0        # keeper only: xg of the goals let in
var dribbles := 0             # successful take-ons / carries that beat pressure and gained ground
var carry_dist := 0.0         # px gained towards goal while dribbling (units: px)
var dispossessed := 0         # lost the ball to a tackle while dribbling
var conceded := 0             # goals conceded while on the pitch
var scored_for := 0           # team goals scored while on the pitch
var keeper_ticks := 0         # ticks played as the team's goalkeeper
var distance := 0.0
var rating := 6.0


func passes() -> int:
    return passes_ok + passes_failed


func pass_accuracy() -> float:
    var n := passes()
    return 1.0 if n == 0 else float(passes_ok) / float(n)


## tackles + interceptions + loose ball recoveries (kept as one number for compact tables)
func defensive_actions() -> int:
    return tackles + interceptions + recoveries


func duels_won() -> int:
    return tackles + dribbles


func duels_lost() -> int:
    return dispossessed


func to_dict() -> Dictionary:
    return {"touches": touches, "passes_ok": passes_ok, "passes_failed": passes_failed,
        "passes_received": passes_received, "progressive_passes": progressive_passes,
        "key_passes": key_passes, "shots": shots, "shots_on_target": shots_on_target,
        "goals": goals, "assists": assists, "own_goals": own_goals,
        "xg": snappedf(xg, 0.01), "xa": snappedf(xa, 0.01), "big_chances": big_chances,
        "big_scored": big_scored, "tackles": tackles, "interceptions": interceptions,
        "recoveries": recoveries, "clearances": clearances, "blocks": blocks, "saves": saves,
        "save_xg": snappedf(save_xg, 0.01), "conceded_xg": snappedf(conceded_xg, 0.01),
        "dribbles": dribbles, "dispossessed": dispossessed, "conceded": conceded,
        "keeper_ticks": keeper_ticks, "distance": snappedf(distance / 10.0, 0.1),
        "def_actions": defensive_actions(), "rating": rating}
