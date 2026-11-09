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


func decide(sim: MatchSim, p: SimPlayer) -> void:
    var out := net.forward(features(sim, p, net.sizes[0] > 49))
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
