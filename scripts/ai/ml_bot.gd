class_name MLBot
extends BotController
## Neural-net policy: observation -> (move, kick). Drop-in replacement for StyleBot.

var net: MLP
var rng: RandomNumberGenerator
var temperature := 1.0      # < 1 = greedier, 0 = argmax


func _init(n: MLP, r: RandomNumberGenerator = null) -> void:
    net = n
    rng = r


## Raw observation + ball/goal relative to the player (fine scale, so kick range is learnable).
static func features(sim: MatchSim, p: SimPlayer, with_slot: bool = false) -> PackedFloat32Array:
    var f := sim.get_observation(p)
    var s := sim.attack_dir(p.team)
    var rel := (sim.ball.pos - p.pos)
    var rx := clampf(rel.x * s / 40.0, -6.0, 6.0)
    var ry := clampf(rel.y / 40.0, -6.0, 6.0)
    f.append(rx)
    f.append(ry)
    f.append(clampf(rel.length() / 40.0, 0.0, 6.0))
    var goal := Vector2(s * sim.pitch.half_w, 0.0)
    f.append((goal.x - p.pos.x) * s / 400.0)
    f.append((goal.y - p.pos.y) / 400.0)
    if with_slot:                  # one-hot of the player's slot: lets roles (keeper / defender / attacker) emerge
        for k in 5:
            f.append(1.0 if p.slot == k else 0.0)
    return f


const TEAM_OBS := 46        # size of the role-free team observation (features_team)


## Role-free observation (46 numbers, no player ID): the same picture for every player, from its own point of view (the pitch is
## mirrored so the team always attacks to the right). Me, my 4 teammates NEAREST FIRST, the 5 opponents NEAREST FIRST (position and
## speed each, scaled by the pitch and by 5), the ball (position and speed), kickoff on (0/1), goal celebration on (0/1).
## Sorting by distance instead of by slot is what keeps a player from knowing which "role" it has: it acts on the situation.
static func features_team(sim: MatchSim, p: SimPlayer) -> PackedFloat32Array:
    var s := sim.attack_dir(p.team)
    var f := PackedFloat32Array()
    sim._push_disc(f, p, s)
    var mates: Array = []
    for m: SimPlayer in sim.team_lists[p.team]:
        if m != p:
            mates.append(m)
    for group: Array in [mates, sim.team_lists[1 - p.team].duplicate()]:
        group.sort_custom(func(a: SimPlayer, b: SimPlayer) -> bool:
            var da := a.pos.distance_squared_to(p.pos)
            var db := b.pos.distance_squared_to(p.pos)
            return da < db or (da == db and a.uid < b.uid))
        for d: SimPlayer in group:
            sim._push_disc(f, d, s)
    sim._push_disc(f, sim.ball, s)
    f.append(1.0 if sim.kickoff_active else 0.0)
    f.append(1.0 if sim.state == MatchSim.State.GOAL else 0.0)
    return f


## The observation a net of this input size expects (46 = team observation; 49 / 54 = the older ego layouts).
static func features_for(sim: MatchSim, p: SimPlayer, n_in: int) -> PackedFloat32Array:
    return features_team(sim, p) if n_in == TEAM_OBS else features(sim, p, n_in > 49)


func decide(sim: MatchSim, p: SimPlayer) -> void:
    var out := net.forward(features_for(sim, p, net.sizes[0]))
    var best := 0
    for k in range(1, 9):
        if out[k] > out[best]:
            best = k
    if rng != null and temperature > 0.0:      # sample from softmax(logits / T)
        var w := PackedFloat32Array()
        var sum := 0.0
        for k in 9:
            var e := exp((out[k] - out[best]) / temperature)
            w.append(e)
            sum += e
        var r := rng.randf() * sum
        for k in 9:
            r -= w[k]
            if r <= 0.0:
                best = k
                break
    var kick := false
    var zk := out[9] + net.kick_bias
    if rng != null and temperature > 0.0:
        kick = rng.randf() < 1.0 / (1.0 + exp(-zk))
    else:
        kick = zk > 0.0
    sim.set_action(p, best, kick)
    p.kick_intent = ""
